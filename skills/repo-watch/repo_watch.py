"""repo-watch — the deterministic half of a watch pass.

The SKILL.md carries the procedure an agent follows. This module carries the parts
that must be the SAME every pass, because they are the parts a careful agent gets
wrong differently each time: how a repo's owner is resolved from the graph, what
counts as a duplicate of an existing bead, and what the flood cap does when a pass
finds more than it is allowed to mint.

Design notes that are load-bearing, not decoration:

* **No network or filesystem I/O.** Text in, data out; invalid sweep setup warns. The agent
  runs the HTTP and git; this module only builds queries and judges results. That is
  what makes the whole thing testable offline, which is the skein convention.

* **No internal identifiers.** Hosts, namespaces, repo names and owners arrive as
  arguments resolved at run time. Nothing internal is baked in — this file ships to a
  public mirror.
"""

from __future__ import annotations

import json
import re
import warnings
from dataclasses import dataclass, field

#: Ordered, and the order is the point. Plans establish intent; beads say what is
#: already claimed; docs state what was promised; code says what is true; the sweep
#: says what the forge is holding that none of them mention. Reading them in this
#: order means every later lens can cite an earlier one, and a gap is always phrased
#: as "X promises, Y delivers" rather than a bare complaint.
#:
#: The sweep is LAST deliberately: it is the only lens whose findings come from
#: outside the repository, so running it after the other four means an open issue
#: that the code or docs already answer is recognised as such rather than minted.
LENSES = ("plans", "beads", "docs", "code", "sweep")

#: A pass may not mint more than this without an explicit override. A watcher that
#: floods the board is worse than one that misses something: the misses stay
#: findable, the flood buries everything else.
DEFAULT_MINT_CAP = 7


class ResolutionError(Exception):
    """The graph could not name an owner for this repo.

    Deliberately fatal rather than defaulted. A watch pass whose owner is a guess
    mints beads at the wrong person, and an unowned repo is a real, recorded state
    here — not an accident to paper over.
    """


@dataclass
class Resolution:
    """What the graph knows about one repo, resolved at run time."""

    repo: str
    owner: str | None = None
    ownership_state: str | None = None
    remotes: list[str] = field(default_factory=list)

    @property
    def ruled(self) -> bool:
        return self.owner is not None and self.ownership_state == "RULED"


# --------------------------------------------------------------------------- #
# Resolution
# --------------------------------------------------------------------------- #

def resolve_query(name: str, ns: str) -> str:
    """SPARQL resolving one repo name to owner, ownership state and remotes.

    Three properties of this query are deliberate and each one was paid for:

    1. **Bidirectional alias closure.** For each ownership assertion, check
       whether ``(owl:sameAs|^owl:sameAs)*`` reaches an exact label or altLabel.
       Zero hops preserves direct ownership; either direction supports one-way
       knots without writing inverse edges or relying on materialisation.
       FILTER EXISTS seeds each traversal with its ownership entity. A path
       joined to a label UNION can instead expand the whole graph on the target
       endpoint, even for a missing label.

    2. **DISTINCT.** Denormalisation means a name frequently matches BOTH the label
       and an altLabel of the same entity, so the un-deduplicated form returns the
       same owner two or three times. Nothing is wrong when that happens, but a
       caller counting rows would read it as ambiguity.

    3. **OPTIONAL on state and remotes.** A repo with an owner but no recorded
       ownership state must still resolve. Making these required turns a partially
       described repo into an unresolvable one, which reads as "the resolver is
       broken" instead of "the graph is incomplete here".

    One line on purpose: the query endpoint takes JSON, and a JSON string cannot
    carry literal newlines.
    """
    if not name or not name.strip():
        raise ValueError("repo name is required")
    if '"' in name or "\\" in name:
        # The name is interpolated into a SPARQL literal. Anything that could close
        # that literal is refused rather than escaped — a watch pass never has a
        # legitimate reason to look up a name containing a quote.
        raise ValueError(f"refusing unsafe repo name: {name!r}")
    return (
        "PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#> "
        "PREFIX skos: <http://www.w3.org/2004/02/skos/core#> "
        "PREFIX owl: <http://www.w3.org/2002/07/owl#> "
        f"PREFIX a: <{ns}> "
        "SELECT DISTINCT ?owner ?state ?remote WHERE { "
        "?e a:owned_by ?owner . "
        "FILTER EXISTS { ?e (owl:sameAs|^owl:sameAs)* ?match . "
        f'{{ ?match rdfs:label "{name}" }} UNION {{ ?match skos:altLabel "{name}" }} }} '
        "OPTIONAL { ?e a:ownershipState ?state } "
        "OPTIONAL { ?e a:hasRemoteHost ?remote } "
        "} LIMIT 50"
    )


def rows_of(payload: dict) -> list[dict]:
    """Rows out of either response shape the query endpoint can return.

    The default compact shape is ``{"rows":[{var: value}]}``; with
    ``Accept: application/sparql-results+json`` it is W3C
    ``{"results":{"bindings":[{var:{"value":...}}]}}``. Accepting both means a caller
    that adds an Accept header for some other reason does not silently start reading
    zero rows — which is the failure mode this whole skill exists to catch, one level
    down.
    """
    if not isinstance(payload, dict):
        return []
    if isinstance(payload.get("rows"), list):
        return [r for r in payload["rows"] if isinstance(r, dict)]
    bindings = payload.get("results", {}).get("bindings")
    if isinstance(bindings, list):
        return [
            {k: v.get("value") for k, v in b.items() if isinstance(v, dict)}
            for b in bindings
            if isinstance(b, dict)
        ]
    return []


def local_name(iri: str | None) -> str | None:
    """Return the local name from an absolute IRI, CURIE, or bare name."""
    if not iri:
        return None
    return re.split(r"[/#:]", iri.rstrip("/#:"))[-1] or None


def resolution_of(name: str, payload: dict) -> Resolution:
    """Fold a query response into one Resolution.

    Raises ResolutionError when no owner comes back. The message names the two
    causes that actually occur and are not distinguishable from the empty result —
    the repo is genuinely unowned in the graph, or its owner is recorded only as
    prose in a comment, which a SPARQL resolver cannot see. Both are graph writes by
    the ownership-map owner, not something a watch pass should invent.
    """
    owners, states, remotes = [], [], []
    for row in rows_of(payload):
        if (o := local_name(row.get("owner"))) and o not in owners:
            owners.append(o)
        if (s := row.get("state")) and s not in states:
            states.append(s)
        if (r := row.get("remote")) and r not in remotes:
            remotes.append(r)

    if not owners:
        raise ResolutionError(
            f"no owner in the graph for {name!r}. Either the repo is genuinely "
            f"unowned, or its owner exists only as prose in a comment — a resolver "
            f"cannot see prose. Both are ownership-map writes; do not guess an owner."
        )
    if len(owners) > 1:
        raise ResolutionError(
            f"{name!r} resolves to {len(owners)} owners ({', '.join(sorted(owners))}). "
            f"That is an alias collision or a genuine dispute; either way a watch pass "
            f"must not pick one."
        )
    return Resolution(
        repo=name,
        owner=owners[0],
        ownership_state=states[0] if states else None,
        remotes=sorted(remotes),
    )


# --------------------------------------------------------------------------- #
# Dedupe before mint
# --------------------------------------------------------------------------- #

#: Words carried by so many bead titles that sharing them means nothing.
_STOP = frozenset(
    """a an the and or but if is are was were be been being to of in on at for with
    from by as it its this that these those not no do does did can could should
    would may might must will shall have has had we you they i""".split()
)

_WORD = re.compile(r"[a-z0-9]+")


def tokens(title: str) -> frozenset[str]:
    """Comparable words of a title: lowercased, stop-words and bead ids dropped.

    Bead ids are stripped deliberately. A gap bead's title frequently cites the bead
    it came from, and two candidates citing the SAME source are not thereby the same
    gap — leaving ids in makes unrelated findings look alike, which suppresses real
    work. That is the expensive direction of this error.
    """
    lowered = title.lower()
    lowered = re.sub(r"\b[a-z]{2,8}-[a-z0-9]{3,6}\b", " ", lowered)
    return frozenset(w for w in _WORD.findall(lowered) if w not in _STOP and len(w) > 2)


def similarity(a: str, b: str) -> float:
    """Jaccard overlap of two titles' comparable words, 0.0 - 1.0."""
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


#: A forge object reference: the repo name and the issue/PR number. `#99`, `PR 99`,
#: `pull request 99` and `issue #99` all denote the same object, and a bead written
#: by a human will use whichever reads best in its sentence.
_FORGE_NUM = re.compile(r"(?:#|\b(?:pr|issue|pull\s+request)\s+#?)(\d{1,6})\b", re.I)


def forge_refs(text: str) -> set[str]:
    """Every issue/PR number mentioned in a piece of text, as strings.

    Deliberately number-only and repo-agnostic: the repo is checked separately, and
    forcing both into one pattern means a bead that names the repo in its title and
    the number in its description matches neither half.
    """
    return {m.group(1) for m in _FORGE_NUM.finditer(text or "")}


def refers_to_forge_object(bead: dict, repo: str, number: str) -> bool:
    """Does this bead TRACK that forge object — not merely mention it?

    Title and description only. **Comments are deliberately excluded**, and that
    exclusion is the whole rule: a bead states its SUBJECT in its title and
    description, while its comments discuss whatever came up. Including comments
    made a bead about branch-protection policy — which mentioned a PR in passing
    while discussing trigger behaviour — dedupe a genuine sweep candidate away.

    Measured on real data: a sweep candidate for PR #99 matched a branch-protection
    policy bead that named the PR only in a comment, instead of the bead whose title
    was literally "Track <repo> PR #99". Both "refer to" the object; only one tracks
    it. Deduping against a mention SUPPRESSES REAL WORK, which is the expensive
    direction — a duplicate is visible and cheap to close, a suppressed finding is
    neither.

    Description is still included, because a tracking bead written by a human
    routinely names the repo in the title and the number in the body.
    """
    blob = "\n".join([str(bead.get("title") or ""), str(bead.get("description") or "")])
    if repo.lower() not in blob.lower():
        return False
    return number in forge_refs(blob)


def conflicting_forge_mention(candidate: str, bead: dict, repo: str | None) -> bool:
    """A description reference whose title explicitly tracks another object."""
    if not repo:
        return False
    title = str(bead.get("title") or "")
    # A short repository name is normal in human-written tracking titles.
    name = repo.rsplit("/", 1)[-1]
    if not re.search(r"(?<![\w.-])" + re.escape(name) + r"(?![\w.-])", title, re.I):
        return False
    qualified = re.findall(r"[\w.-]+/" + re.escape(name) + r"(?![\w.-])", title, re.I)
    if "/" in repo and qualified and repo.lower() not in {r.lower() for r in qualified}:
        return False
    titled = forge_refs(title)
    mentioned = forge_refs(str(bead.get("description") or ""))
    return bool(titled and (forge_refs(candidate) & mentioned) - titled)


def find_duplicate(
    candidate: str, corpus: list[dict], threshold: float = 0.6,
    repo: str | None = None
) -> dict | None:
    """The existing bead a candidate gap would duplicate, or None.

    ``corpus`` is the FULL bead corpus — every bead, not the ready pool and not a
    title search. Two reasons, both measured on this fleet: the ready listing
    truncates by default, so an absence read from it is frequently an artefact of the
    limit; and the store's own search matches titles only, so it reports a phrase
    living in a description or comment as simply not present.

    Closed beads count as duplicates. A gap that was found and fixed last week should
    not be re-minted this week — if it has regressed, that is a different bead with a
    different argument, and it deserves to be written as one.
    """
    # Conflicting description mentions must not re-enter through fuzzy matching.
    corpus = [b for b in corpus if not conflicting_forge_mention(candidate, b, repo)]
    # STRONGEST SIGNAL FIRST: an exact forge-object reference.
    #
    # Fuzzy title overlap CANNOT do this job and quietly fails at it. Measured on
    # real data: candidate "<repo> PR #99 untracked: chore: release v1.2.3" against
    # the bead already tracking it, "Track <repo> PR #99: release v1.2.3",
    # scores **0.333** — nowhere near any usable threshold — because the two are
    # written by different authors for different readers and share almost no
    # vocabulary. The one thing they DO share, the number, is exactly what the
    # tokenizer drops (`#99` -> `99`, two characters, below the length floor).
    #
    # So the identity of a forge object is (repo, number), not its prose. Lowering
    # the fuzzy threshold instead would have been the tempting fix and the wrong
    # one: it buys this case at the cost of collapsing unrelated findings together,
    # which suppresses real work rather than merely duplicating it.
    if repo:
        for number in sorted(forge_refs(candidate)):
            # TITLE first: a bead that TRACKS an object names it in the title, while
            # one that merely works on the same area may name it in the description.
            # Without this ordering the winner is whichever bead the corpus happens
            # to list first, and the report then attributes the dedupe to a bead that
            # has little to do with the finding — right outcome, misleading record.
            for titled in (True, False):
                for bead in corpus:
                    if titled and number not in forge_refs(str(bead.get("title") or "")):
                        continue
                    if refers_to_forge_object(bead, repo, number):
                        return bead

    best, best_score = None, threshold
    for bead in corpus:
        title = bead.get("title") or ""
        if not title:
            continue
        score = similarity(candidate, title)
        if score >= best_score:
            best, best_score = bead, score
    return best


#: Labels every minted watch bead carries, plus the repo label added at run time.
WATCH_LABELS = ("repo-watch", "needs-triage")


@dataclass
class Triage:
    """What a pass decided to do about each candidate gap.

    Five outcomes, and the report names all five. A candidate that vanishes without
    appearing in one of these lists is indistinguishable from one that was never
    found, which is the failure this whole structure exists to prevent.
    """

    mint: list[str] = field(default_factory=list)
    #: (candidate, the OPEN watch bead it should update instead of duplicating)
    update: list[tuple[str, dict]] = field(default_factory=list)
    #: (candidate, the existing bead that makes it a duplicate)
    duplicate: list[tuple[str, dict]] = field(default_factory=list)
    #: (candidate, possible covering bead); requires explicit human adjudication
    ambiguous: list[tuple[str, dict]] = field(default_factory=list)
    #: over the cap — withheld, never discarded
    held: list[str] = field(default_factory=list)

    def withheld_line(self, cap: int) -> str:
        """One log line naming what the cap withheld, or that it withheld nothing.

        Required, not optional. A cap that silently drops findings is a filter
        nobody can audit; the pass must say the number AND the subjects, because
        "held 3" with no titles cannot be checked against the next pass.
        """
        if not self.held:
            return f"cap {cap}: nothing withheld ({len(self.mint)} minted)"
        subjects = "; ".join(self.held)
        return (f"cap {cap}: WITHHELD {len(self.held)} of "
                f"{len(self.mint) + len(self.held)} eligible — {subjects}")


def is_open_watch_bead(bead: dict) -> bool:
    """An OPEN bead this watcher minted — the thing to UPDATE rather than re-mint.

    Both halves matter. A CLOSED watch bead must not be reopened by a re-find: the
    gap was dealt with, and if it has genuinely regressed that deserves a new bead
    with a new argument. A bead a HUMAN wrote about the same subject must not be
    updated either — a watcher editing someone else's bead is how a report stops
    being trustworthy.
    """
    if (bead.get("status") or "").lower() == "closed":
        return False
    labels = bead.get("labels") or []
    if isinstance(labels, str):
        labels = [labels]
    return "repo-watch" in {str(x).lower() for x in labels}


def triage(candidates: list[str], corpus: list[dict],
           cap: int = DEFAULT_MINT_CAP, dedupe: bool = True,
           repo: str | None = None) -> Triage:
    """Decide mint / update / duplicate / ambiguous / held for every candidate gap.

    **Dedupe runs BEFORE the cap.** Reversed, duplicates consume the budget and push
    real findings into the held pile — the pass then reports that it hit the cap
    while minting nothing new, the worst of both outcomes.

    **`corpus` is the FULL bead corpus, and it must not come from a title search.**
    The store's search matches TITLES ONLY and reports that blindness in the exact
    words of a true absence, while every directive and finding on this fleet is
    prose in a description or a comment. A title-only dedupe is therefore
    structurally blind to precisely what it is checking for — it would report "no
    duplicates" most confidently for the subjects most discussed. Export the JSONL
    and pass it here.

    `dedupe=False` exists ONLY as the positive control for the check itself: a
    dedupe that has never been observed to FIRE is not a proven dedupe, and the
    cheapest proof is the same pass minting the duplicate when the check is off.
    Never run a real pass with it disabled.
    """
    if cap < 0:
        raise ValueError("cap must not be negative")
    if repo is None and any(re.search(r"\b(?:issue|PR) #\d+ untracked:", c) for c in candidates):
        warnings.warn("Forge sweep candidates require repo= for identity deduplication",
                      RuntimeWarning, stacklevel=2)
    out = Triage()
    for c in candidates:
        hit = find_duplicate(c, corpus, repo=repo) if dedupe else None
        if hit is None:
            conflicts = [b for b in corpus if conflicting_forge_mention(c, b, repo)] if dedupe else []
            if conflicts:
                out.ambiguous.extend((c, b) for b in conflicts)
            else:
                out.mint.append(c)
        elif is_open_watch_bead(hit):
            out.update.append((c, hit))
        else:
            out.duplicate.append((c, hit))
    out.held = out.mint[cap:]
    out.mint = out.mint[:cap]
    return out


# --------------------------------------------------------------------------- #
# The GH/PR sweep lens
# --------------------------------------------------------------------------- #

class ForgeListingError(Exception):
    """A forge answered a listing with something that is not a list: CANNOT TELL.

    A forge refuses in-band. Forgejo answers a token that lacks ``read:issue``
    with HTTP 200-shaped JSON — an OBJECT, ``{"message": ..., "url": ...}`` —
    where a listing is an ARRAY. Counted with ``len()`` that object is "2 open
    issues"; iterated, it is "no open issues". Both are numbers read off an
    error. The only honest report is that this repo's open objects could not
    be read, with the forge's own words for why (internal-ref.1).
    """


def forge_items(payload: object, repo: str) -> list:
    """The items of a forge listing, or ForgeListingError when it is not one."""
    if isinstance(payload, list):
        return payload
    message = payload.get("message") if isinstance(payload, dict) else None
    raise ForgeListingError(
        f"{repo}: CANNOT TELL: the forge returned a {type(payload).__name__}, not a "
        f"listing" + (f": {message}" if message else "")
    )


def sweep_candidate(item: dict, repo: str) -> str | None:
    """One forge issue/PR -> the gap title a watch pass would mint for it.

    Shape-agnostic on purpose. GitHub's REST/`gh` JSON and Forgejo's API agree on
    `number`, `title` and `state` but disagree on almost everything else, and a
    lens that only understands one of them silently sweeps half the estate — which
    looks exactly like "the internal repos have no open issues".

    A PR is distinguished from an issue by the presence of a pull-request marker,
    which BOTH forges carry in some form. When neither is present the item is
    treated as an issue: mislabelling a PR as an issue costs a word in a title,
    while dropping it costs the whole finding.

    Returns None for anything not OPEN, and for items with no usable title. A
    closed issue is not a gap, and a gap with no subject cannot be deduplicated.
    """
    if (item.get("state") or "").lower() not in ("open", "opened"):
        return None
    title = (item.get("title") or "").strip()
    number = item.get("number")
    if not title or number is None:
        return None
    # PRESENCE of the marker, not its truthiness. `gh` emits `pull_request` as an
    # object that is EMPTY for some items, and `{}` is falsy — a truthiness test
    # therefore relabels real PRs as issues, silently and only for some of them,
    # which is worse than getting all of them wrong because the sample looks right.
    is_pr = any(k in item for k in ("pull_request", "head", "isPullRequest"))
    kind = "PR" if is_pr else "issue"
    return f"{repo} {kind} #{number} untracked: {title}"


def sweep_candidates(items: object, repo: str) -> list[str]:
    """Every open issue/PR in a forge listing, as candidate gap titles.

    ``items`` is the forge's parsed JSON as returned. Anything that is not a list
    raises ForgeListingError (CANNOT TELL): an error object must never become a
    count, and an empty result must stay distinguishable from an unread one.

    Order is preserved so a cap withholds the OLDEST-listed last rather than
    arbitrarily; forges list newest-first, so this keeps the cap biased toward
    reporting recent activity, which is what a watcher is for.
    """
    out = []
    for item in forge_items(items, repo):
        if isinstance(item, dict) and (c := sweep_candidate(item, repo)):
            out.append(c)
    return out


def mint_labels(repo: str) -> tuple[str, ...]:
    """Labels every minted watch bead carries: the fixed pair plus the repo label.

    The repo label is what makes a per-repo sweep auditable after the fact — without
    it, "which of these came from watching X" is unanswerable once the titles age.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", repo.lower()).strip("-")
    return WATCH_LABELS + ((slug,) if slug else ())


# --------------------------------------------------------------------------- #
# The watch anchor
# --------------------------------------------------------------------------- #

class UnreachableAnchor(Exception):
    """The recorded anchor resolves in no clone of the canonical remote.

    Raised rather than returned because the alternative is the defect: an
    unreachable anchor makes the delta UNCOMPUTABLE, and an uncomputable delta is
    indistinguishable from a first pass. A pass that swallows it reports
    "BOOTSTRAP - no delta" and restates the repo's current state as new findings,
    which is a confident wrong answer on the repo with the most churn.
    """


@dataclass
class Anchor:
    """Where the last pass stopped. ``sha is None`` means no pass has ever run."""

    repo: str
    sha: str | None = None
    run: str | None = None
    #: The canonical remote this sha was taken from. Recorded BESIDE the sha so a
    #: repo that later changes forge (shantytown moved Forgejo -> GitHub,
    #: internal-ref) leaves evidence instead of a mystery.
    remote: str | None = None
    #: Is the sha reachable from the canonical remote? None means NOBODY ASKED,
    #: and it is deliberately not False: "we did not check" and "we checked and
    #: it is gone" must not render the same. `verify` sets it.
    reachable: bool | None = None

    @property
    def bootstrap(self) -> bool:
        return self.sha is None


def verify_anchor(anchor: Anchor, repo_path, run=None,
                  remote_ref: str = "origin/main") -> Anchor:
    """Fill in ``reachable`` and ``remote`` by asking git, and REFUSE a bad anchor.

    THE ANCHOR MUST COME FROM THE REMOTE, NOT FROM A CHECKOUT. The 2026-08-30
    shantytown pass anchored on a working checkout's HEAD while the tracked remote
    never had that commit, so the next pass had nothing to measure against. Record
    with `git rev-parse origin/main`, never `HEAD` - HEAD belongs to whoever last
    touched that checkout, and on a shared checkout that is not you.

    A FAILED FETCH LEAVES reachable=None, NOT False. "We could not ask" and "we
    asked and it is gone" have opposite remedies - one is re-run when the network
    is back, the other is re-anchor - and collapsing them would make an outage
    look like data loss. The caller decides what to do with None; this never
    invents an answer it did not get.
    """
    import subprocess

    # A bare sha is the natural thing to pass - the step before this one says to
    # record it with `git rev-parse` - and it used to die with "'str' object has no
    # attribute 'remote'", an error about nothing the caller wrote (internal-ref).
    # Refuse it by name instead of guessing a repo for it.
    if not isinstance(anchor, Anchor):
        raise TypeError(
            f"verify_anchor takes an Anchor, not {type(anchor).__name__} {anchor!r}: "
            f"wrap it as Anchor(repo=<name>, sha=<sha>)")

    def git(*args):
        return subprocess.run(["git", "-C", str(repo_path), *args],
                              capture_output=True, text=True)

    if run is not None:                      # injectable for tests
        git = run

    url = git("remote", "get-url", "origin")
    anchor.remote = (url.stdout or "").strip() or None
    if anchor.bootstrap:
        return anchor                        # nothing to reach yet; not a failure

    fetched = git("fetch", "origin", "--quiet")
    if fetched.returncode != 0:
        anchor.reachable = None              # could not ask - see docstring
        return anchor

    r = git("merge-base", "--is-ancestor", anchor.sha, remote_ref)
    anchor.reachable = (r.returncode == 0)
    if anchor.reachable is False:
        raise UnreachableAnchor(
            f"{anchor.repo}: anchor {anchor.sha} is not an ancestor of "
            f"{remote_ref} on {anchor.remote or 'origin'} - it exists in no "
            f"clone but the one that recorded it. Re-anchor from "
            f"`git rev-parse {remote_ref}`.")
    return anchor


def code_range(anchor: Anchor, head: str) -> str | None:
    """The git range a code/docs lens should read, or None when nothing moved.

    On a bootstrap pass this returns None rather than a range covering all history.
    A first pass has no delta to report; claiming one would restate the entire repo
    as new findings. The honest first pass records the anchor and reads the current
    state, which is what the plans and beads lenses do anyway.
    """
    if anchor.reachable is False:
        # NOT None. An anchor nobody else can resolve is not an anchor, and
        # returning None here would spell it "bootstrap" - the exact silent
        # degradation this guard exists to stop (internal-ref). Measured on
        # shantytown's 2026-08-30 pass: the anchor 5a301c7e was a LOCAL unpushed
        # commit on a side branch, present in 1 of 36 clones and in 0 remote
        # refs, so `git rev-list 5a301c7e..origin/main` could not be computed at
        # all and the pass would have reported a clean first look.
        raise UnreachableAnchor(
            f"{anchor.repo}: anchor {anchor.sha} is not reachable from "
            f"{anchor.remote or 'the canonical remote'} - the delta is "
            f"UNCOMPUTABLE, not empty. Re-anchor from a pushed commit "
            f"(`git rev-parse origin/main`), never from a working checkout's HEAD.")
    if anchor.bootstrap or anchor.sha == head:
        return None
    return f"{anchor.sha}..{head}"


def run_name(repo: str, head: str, stamp: str) -> str:
    """Deterministic shuttle run id: ``watch-<repo>-<sha8>-<stamp>``.

    Deterministic so that re-deriving it later finds the same run, and carrying the
    sha so two passes over an unchanged repo cannot collide into one run id.
    """
    safe = re.sub(r"[^a-z0-9]+", "-", repo.lower()).strip("-")
    if not safe:
        raise ValueError(f"repo name has no usable characters: {repo!r}")
    return f"watch-{safe}-{head[:8]}-{stamp}"
