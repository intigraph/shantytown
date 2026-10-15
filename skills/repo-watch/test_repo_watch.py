"""Proof that repo-watch's deterministic half behaves, including when it must refuse.

skein convention: a check that has never returned every one of its outcomes is not a
check. So each refusal below is exercised on purpose, not just the happy path — an
unresolvable repo, an ambiguous one, a duplicate, and a cap that bites.

The names used here are invented. This file ships to a public mirror, and a test
fixture is the easiest place for a real internal name to slip through.

Stdlib unittest — no pytest, no network, no graph. Run: python3 -m unittest
"""
import unittest

import repo_watch as rw

NS = "https://example.invalid/ontology/"


def compact(*rows):
    """The query endpoint's default response shape."""
    return {"count": len(rows), "rows": list(rows)}


def w3c(*rows):
    """The W3C SPARQL-results shape, returned when Accept asks for it."""
    return {
        "head": {"vars": ["owner", "state", "remote"]},
        "results": {
            "bindings": [
                {k: {"type": "uri", "value": v} for k, v in r.items()} for r in rows
            ]
        },
    }


class TestResolveQuery(unittest.TestCase):
    def test_is_one_line(self):
        # A JSON string cannot carry literal newlines, so a multi-line query fails
        # with a JSON parse error that says nothing about SPARQL.
        self.assertNotIn("\n", rw.resolve_query("alpha", NS))

    def test_carries_prefixes(self):
        # Bare rdfs:/skos: is a hard parse error; the endpoint declares nothing.
        q = rw.resolve_query("alpha", NS)
        self.assertIn("PREFIX rdfs:", q)
        self.assertIn("PREFIX skos:", q)
        self.assertIn(f"PREFIX a: <{NS}>", q)

    def test_is_distinct(self):
        # Denormalised aliases mean a name matches both label and altLabel of one
        # entity; without DISTINCT that reads as ambiguity.
        self.assertIn("SELECT DISTINCT", rw.resolve_query("alpha", NS))

    def test_uses_bidirectional_alias_closure(self):
        self.assertIn("(owl:sameAs|^owl:sameAs)*", rw.resolve_query("alpha", NS))

    def test_state_and_remotes_are_optional(self):
        # A repo with an owner but no recorded state must still resolve.
        q = rw.resolve_query("alpha", NS)
        self.assertIn("OPTIONAL { ?e a:ownershipState ?state }", q)
        self.assertIn("OPTIONAL { ?e a:hasRemoteHost ?remote }", q)

    def test_refuses_quote_injection(self):
        for bad in ['al"pha', "back\\slash"]:
            with self.assertRaises(ValueError):
                rw.resolve_query(bad, NS)

    def test_refuses_empty(self):
        with self.assertRaises(ValueError):
            rw.resolve_query("   ", NS)


try:
    import rdflib
except ImportError:
    rdflib = None


@unittest.skipUnless(rdflib, "graph regression: uv run --with rdflib python -m unittest")
class TestResolveGraph(unittest.TestCase):
    """Execute generated SPARQL over one-way aliases, without inference."""

    def setUp(self):
        self.graph = rdflib.Graph().parse(data='''
            @prefix a: <https://example.invalid/ontology/> .
            @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
            @prefix skos: <http://www.w3.org/2004/02/skos/core#> .
            @prefix owl: <http://www.w3.org/2002/07/owl#> .
            a:canonical rdfs:label "canonical" ; a:owned_by a:ada ;
                a:ownershipState "RULED" ; a:hasRemoteHost "forge.invalid" ;
                owl:sameAs a:alias .
            a:alias rdfs:label "alias" ; skos:altLabel "short" .
            a:forward rdfs:label "forward" ; owl:sameAs a:canonical .
            a:chain rdfs:label "chain" ; owl:sameAs a:alias .
            a:unowned rdfs:label "unowned" .
        ''', format="turtle")

    def resolve(self, name):
        rows = [{str(k): str(v) for k, v in row.asdict().items()}
                for row in self.graph.query(rw.resolve_query(name, NS))]
        return rw.resolution_of(name, compact(*rows))

    def test_direct_forward_reverse_altlabel_and_mixed_chain(self):
        before = set(self.graph)
        for name in ("canonical", "forward", "alias", "short", "chain"):
            with self.subTest(name=name):
                result = self.resolve(name)
                self.assertEqual(result.owner, "ada")
                self.assertTrue(result.ruled)
                self.assertEqual(result.remotes, ["forge.invalid"])
        self.assertEqual(set(self.graph), before)

    def test_unowned_and_missing_still_refuse(self):
        for name in ("unowned", "missing"):
            with self.subTest(name=name), self.assertRaises(rw.ResolutionError):
                self.resolve(name)

    def test_conflicting_owner_across_alias_refuses(self):
        self.graph.add((rdflib.URIRef(NS + "alias"),
                        rdflib.URIRef(NS + "owned_by"), rdflib.URIRef(NS + "bo")))
        with self.assertRaisesRegex(rw.ResolutionError, "2 owners"):
            self.resolve("canonical")

    def test_cycle_and_repeated_owner_do_not_make_ambiguity(self):
        self.graph.add((rdflib.URIRef(NS + "alias"), rdflib.OWL.sameAs,
                        rdflib.URIRef(NS + "canonical")))
        self.graph.add((rdflib.URIRef(NS + "alias"),
                        rdflib.URIRef(NS + "owned_by"), rdflib.URIRef(NS + "ada")))
        self.assertEqual(self.resolve("chain").owner, "ada")


class TestRowsOf(unittest.TestCase):
    def test_reads_compact_shape(self):
        self.assertEqual(rw.rows_of(compact({"owner": "x"})), [{"owner": "x"}])

    def test_reads_w3c_shape(self):
        self.assertEqual(rw.rows_of(w3c({"owner": "x"})), [{"owner": "x"}])

    def test_empty_and_junk_are_no_rows_not_a_crash(self):
        for junk in [{}, {"rows": None}, [], None, {"results": {}}]:
            self.assertEqual(rw.rows_of(junk), [])


class TestResolution(unittest.TestCase):
    def test_resolves_owner_state_and_remotes(self):
        r = rw.resolution_of(
            "alpha",
            compact(
                {"owner": NS + "ada", "state": "RULED", "remote": "forge.invalid"},
                {"owner": NS + "ada", "state": "RULED", "remote": "mirror.invalid"},
            ),
        )
        self.assertEqual(r.owner, "ada")
        self.assertEqual(r.ownership_state, "RULED")
        self.assertEqual(r.remotes, ["forge.invalid", "mirror.invalid"])
        self.assertTrue(r.ruled)

    def test_duplicate_rows_are_one_owner(self):
        # The un-deduplicated store genuinely returns the same owner repeatedly.
        r = rw.resolution_of("alpha", compact(*[{"owner": NS + "ada"}] * 3))
        self.assertEqual(r.owner, "ada")

    def test_owner_without_state_still_resolves_but_is_not_ruled(self):
        r = rw.resolution_of("alpha", compact({"owner": NS + "ada"}))
        self.assertEqual(r.owner, "ada")
        self.assertFalse(r.ruled)

    def test_no_owner_refuses_and_names_the_prose_cause(self):
        # The entity can exist, be well-formed, and still carry its owner only as
        # prose in a comment — which is invisible to SPARQL and looks like absence.
        with self.assertRaises(rw.ResolutionError) as e:
            rw.resolution_of("alpha", compact({"remote": "forge.invalid"}))
        self.assertIn("prose", str(e.exception))

    def test_empty_response_refuses(self):
        with self.assertRaises(rw.ResolutionError):
            rw.resolution_of("alpha", compact())

    def test_two_owners_refuses_rather_than_picking(self):
        with self.assertRaises(rw.ResolutionError) as e:
            rw.resolution_of(
                "alpha", compact({"owner": NS + "ada"}, {"owner": NS + "bo"})
            )
        self.assertIn("2 owners", str(e.exception))


class TestLocalName(unittest.TestCase):
    def test_splits_slash_and_hash(self):
        self.assertEqual(rw.local_name("https://example.invalid/o/ada"), "ada")
        self.assertEqual(rw.local_name("https://example.invalid/o#ada"), "ada")

    def test_splits_a_compact_iri(self):
        self.assertEqual(rw.local_name("aegis:ada"), "ada")

    def test_passes_through_a_bare_name(self):
        self.assertEqual(rw.local_name("ada"), "ada")

    def test_none_stays_none(self):
        self.assertIsNone(rw.local_name(None))
        self.assertIsNone(rw.local_name(""))


class TestTokens(unittest.TestCase):
    def test_drops_stop_words_and_short_words(self):
        # "the", "is" and "of" go as stop-words; "out" stays, because it carries
        # meaning in plenty of titles and the expensive direction of this error is
        # dropping signal, not keeping noise.
        self.assertEqual(rw.tokens("the readme is out of date"), {"readme", "out", "date"})

    def test_drops_bead_ids(self):
        # Two findings citing the same source bead are not the same finding.
        self.assertNotIn("abcd-1x2y", rw.tokens("abcd-1x2y: readme drift"))

    def test_is_case_insensitive(self):
        self.assertEqual(rw.tokens("README Drift"), rw.tokens("readme drift"))


class TestDedupe(unittest.TestCase):
    CORPUS = [
        {"id": "x-1", "title": "README claims negation is rejected after it shipped"},
        {"id": "x-2", "title": "Signing banner says nothing built while v1 is live"},
        {"id": "x-3", "title": "Track pull request 99: release v0.3.28", "status": "closed"},
    ]

    def test_near_identical_title_is_a_duplicate(self):
        hit = rw.find_duplicate(
            "README still claims negation is rejected after it shipped", self.CORPUS
        )
        self.assertIsNotNone(hit)
        self.assertEqual(hit["id"], "x-1")

    def test_unrelated_title_is_not_a_duplicate(self):
        self.assertIsNone(
            rw.find_duplicate("Container disk usage crosses its threshold", self.CORPUS)
        )

    def test_closed_beads_still_count_as_duplicates(self):
        # A gap fixed last week must not be re-minted this week.
        hit = rw.find_duplicate("Track pull request 99: release v0.3.28", self.CORPUS)
        self.assertIsNotNone(hit)
        self.assertEqual(hit["status"], "closed")

    def test_corpus_entries_without_titles_are_survivable(self):
        self.assertIsNone(rw.find_duplicate("anything at all here", [{"id": "x"}, {}]))

    def test_empty_corpus_means_nothing_is_a_duplicate(self):
        self.assertIsNone(rw.find_duplicate("README drift", []))


class TestTriage(unittest.TestCase):
    CORPUS = [{"id": "x-1", "title": "README claims negation is rejected"}]

    def test_splits_new_from_duplicate(self):
        r = rw.triage(
            ["README claims negation is rejected", "Disk threshold crossed on the host"],
            self.CORPUS,
        )
        self.assertEqual(r.mint, ["Disk threshold crossed on the host"])
        self.assertEqual(len(r.duplicate), 1)
        self.assertEqual(r.held, [])

    def test_dedupe_runs_before_the_cap(self):
        # If the cap were applied first, duplicates would eat the budget and the
        # pass would report "capped" while minting nothing new.
        r = rw.triage(
            ["README claims negation is rejected", "Genuinely new finding here"],
            self.CORPUS, cap=1)
        self.assertEqual(r.mint, ["Genuinely new finding here"])
        self.assertEqual(len(r.duplicate), 1)
        self.assertEqual(r.held, [])

    def test_overflow_is_held_not_dropped(self):
        cands = [f"Distinct finding number {n} about widgets" for n in range(5)]
        r = rw.triage(cands, [], cap=2)
        self.assertEqual(len(r.mint), 2)
        self.assertEqual(len(r.held), 3)
        self.assertEqual(r.mint + r.held, cands)

    def test_zero_cap_mints_nothing_but_still_reports(self):
        r = rw.triage(["Some finding about widgets"], [], cap=0)
        self.assertEqual(r.mint, [])
        self.assertEqual(len(r.held), 1)

    def test_negative_cap_refuses(self):
        with self.assertRaises(ValueError):
            rw.triage([], [], cap=-1)


class TestDedupeProvenBothWays(unittest.TestCase):
    """The bead's falsifiable criterion: dedupe must be shown to FIRE, not just to pass.

    A dedupe that has never been observed minting the duplicate when disabled is
    indistinguishable from a dedupe that silently never matches anything.
    """

    CORPUS = [{"id": "x-1", "title": "README claims negation is rejected"}]
    DUP = "README still claims negation is rejected"

    def test_with_dedupe_the_duplicate_is_not_minted(self):
        r = rw.triage([self.DUP], self.CORPUS)
        self.assertEqual(r.mint, [])
        self.assertEqual(len(r.duplicate), 1)

    def test_POSITIVE_CONTROL_without_dedupe_it_IS_minted(self):
        r = rw.triage([self.DUP], self.CORPUS, dedupe=False)
        self.assertEqual(r.mint, [self.DUP])
        self.assertEqual(r.duplicate, [])


class TestUpdateInsteadOfRemint(unittest.TestCase):
    OPEN_WATCH = {"id": "w-1", "title": "alpha PR #99 untracked: release v0.3.28",
                  "status": "open", "labels": ["repo-watch", "needs-triage"]}

    def test_re_finding_an_open_watch_bead_updates_it(self):
        r = rw.triage(["alpha PR #99 untracked: release v0.3.28"], [self.OPEN_WATCH])
        self.assertEqual(r.mint, [])
        self.assertEqual(len(r.update), 1)
        self.assertEqual(r.update[0][1]["id"], "w-1")

    def test_a_CLOSED_watch_bead_is_a_duplicate_not_an_update(self):
        # The gap was dealt with. A regression deserves a new bead with a new
        # argument, not a silent reopening of the old one.
        closed = dict(self.OPEN_WATCH, status="closed")
        r = rw.triage(["alpha PR #99 untracked: release v0.3.28"], [closed])
        self.assertEqual(r.update, [])
        self.assertEqual(len(r.duplicate), 1)

    def test_a_HUMAN_bead_is_never_updated_by_the_watcher(self):
        human = dict(self.OPEN_WATCH, labels=["bug"])
        r = rw.triage(["alpha PR #99 untracked: release v0.3.28"], [human])
        self.assertEqual(r.update, [])
        self.assertEqual(len(r.duplicate), 1)

    def test_a_string_label_field_is_survivable(self):
        odd = dict(self.OPEN_WATCH, labels="repo-watch")
        self.assertTrue(rw.is_open_watch_bead(odd))


class TestWithheldLine(unittest.TestCase):
    def test_names_the_subjects_it_withheld(self):
        r = rw.triage([f"Finding number {n} about widgets" for n in range(4)], [], cap=1)
        line = r.withheld_line(1)
        self.assertIn("WITHHELD 3", line)
        # the SUBJECTS, not just the count — a count alone cannot be checked
        self.assertIn("Finding number 3 about widgets", line)

    def test_says_so_when_it_withheld_nothing(self):
        r = rw.triage(["One finding about widgets"], [], cap=7)
        self.assertIn("nothing withheld", r.withheld_line(7))


class TestSweepLens(unittest.TestCase):
    def test_open_issue_becomes_a_candidate(self):
        c = rw.sweep_candidate({"state": "open", "number": 7, "title": "a bug"}, "alpha")
        self.assertEqual(c, "alpha issue #7 untracked: a bug")

    def test_pr_is_labelled_pr(self):
        c = rw.sweep_candidate(
            {"state": "open", "number": 99, "title": "release", "pull_request": {}}, "alpha")
        self.assertIn("PR #99", c)

    def test_EMPTY_pull_request_object_is_still_a_pr(self):
        # `{}` is falsy; a truthiness test relabels real PRs as issues for SOME
        # items only, which looks right in a sample.
        self.assertIn("PR", rw.sweep_candidate(
            {"state": "open", "number": 1, "title": "t", "pull_request": {}}, "a"))

    def test_forgejo_shape_is_understood_too(self):
        self.assertIn("PR", rw.sweep_candidate(
            {"state": "open", "number": 2, "title": "t", "head": {"ref": "x"}}, "a"))

    def test_closed_items_are_not_candidates(self):
        self.assertIsNone(rw.sweep_candidate(
            {"state": "closed", "number": 8, "title": "done"}, "alpha"))

    def test_titleless_or_numberless_items_are_skipped(self):
        self.assertIsNone(rw.sweep_candidate({"state": "open", "number": 3}, "a"))
        self.assertIsNone(rw.sweep_candidate({"state": "open", "title": "t"}, "a"))

    def test_listing_order_is_preserved(self):
        items = [{"state": "open", "number": n, "title": f"t{n}"} for n in (3, 2, 1)]
        got = rw.sweep_candidates(items, "a")
        self.assertEqual([c.split("#")[1][0] for c in got], ["3", "2", "1"])

    def test_junk_entries_do_not_break_the_sweep(self):
        self.assertEqual(rw.sweep_candidates(
            ["nonsense", None, {"state": "open", "number": 1, "title": "t"}], "a"),
            ["a issue #1 untracked: t"])


class TestForgeListing(unittest.TestCase):
    """internal-ref.1: a forge refusal is CANNOT TELL, never a count."""

    SCOPE_ERROR = {"message": "token does not have at least one of required scope(s): "
                              "[read:issue]", "url": "https://forge.example/api/swagger"}

    def test_a_scope_error_object_is_cannot_tell_not_two(self):
        # Before the fix len() of this read "2 open issues" and iterating it read
        # "none": both are numbers taken off an error.
        with self.assertRaises(rw.ForgeListingError) as cm:
            rw.sweep_candidates(self.SCOPE_ERROR, "owner/internal-repo")
        msg = str(cm.exception)
        self.assertIn("CANNOT TELL", msg)
        self.assertIn("read:issue", msg, "the forge's own words are kept")
        self.assertIn("owner/internal-repo", msg)

    def test_an_empty_listing_is_zero(self):
        self.assertEqual(rw.sweep_candidates([], "a"), [])

    def test_a_two_item_listing_is_two(self):
        items = [{"state": "open", "number": n, "title": f"t{n}"} for n in (1, 2)]
        self.assertEqual(len(rw.sweep_candidates(items, "a")), 2)

    def test_other_non_list_bodies_are_cannot_tell_too(self):
        for body in (None, "Not Found", 7, {}):
            with self.assertRaises(rw.ForgeListingError, msg=repr(body)):
                rw.sweep_candidates(body, "a")


class TestMintLabels(unittest.TestCase):
    def test_carries_the_fixed_pair_plus_the_repo(self):
        self.assertEqual(rw.mint_labels("alpha"), ("repo-watch", "needs-triage", "alpha"))

    def test_awkward_repo_names_are_slugged(self):
        self.assertEqual(rw.mint_labels("My.Repo")[-1], "my-repo")


class TestAnchor(unittest.TestCase):
    def test_bootstrap_reads_no_range(self):
        # A first pass has no delta; claiming one restates the repo as findings.
        self.assertIsNone(rw.code_range(rw.Anchor("alpha"), "abc12345"))

    def test_unchanged_head_reads_no_range(self):
        self.assertIsNone(rw.code_range(rw.Anchor("alpha", sha="abc12345"), "abc12345"))

    def test_moved_head_reads_the_delta(self):
        self.assertEqual(
            rw.code_range(rw.Anchor("alpha", sha="aaa"), "bbb"), "aaa..bbb"
        )

    def test_run_name_is_deterministic_and_carries_the_sha(self):
        a = rw.run_name("alpha", "abc12345def", "20260830T0900Z")
        self.assertEqual(a, rw.run_name("alpha", "abc12345def", "20260830T0900Z"))
        self.assertEqual(a, "watch-alpha-abc12345-20260830T0900Z")

    def test_run_name_separates_two_passes_over_different_heads(self):
        self.assertNotEqual(
            rw.run_name("alpha", "aaaaaaaa", "t"), rw.run_name("alpha", "bbbbbbbb", "t")
        )

    def test_run_name_sanitises_awkward_repo_names(self):
        self.assertEqual(
            rw.run_name("Group/Repo.Name", "abc12345", "t"),
            "watch-group-repo-name-abc12345-t",
        )

    def test_run_name_refuses_an_unusable_repo_name(self):
        with self.assertRaises(ValueError):
            rw.run_name("///", "abc12345", "t")


class TestLenses(unittest.TestCase):
    def test_order_is_plans_beads_docs_code_sweep(self):
        # The order is the contract: every later lens can cite an earlier one, and
        # the sweep is last because it is the only lens sourced from OUTSIDE the
        # repo — an issue the code already answers should be recognised, not minted.
        self.assertEqual(rw.LENSES, ("plans", "beads", "docs", "code", "sweep"))




class TestForgeRefIdentity(unittest.TestCase):
    """Both of these were found on REAL data, after the fixture tests above passed.

    That is the point of the class: a candidate and the bead already tracking it are
    written by different authors for different readers, so they share almost no
    vocabulary. Fuzzy title overlap scored the real pair at 0.333 — nowhere near any
    usable threshold — while the fixtures, written by one person in one sitting,
    matched easily. The fixtures were self-confirming.
    """

    TRACKER = {"id": "t-1", "title": "Track Alpha PR #99: release v1.2.3",
               "status": "open", "labels": ["repo-watch"]}
    #: A policy bead that MENTIONS the PR while discussing something else.
    MENTIONER = {"id": "m-1", "title": "alpha required-green branch protection on main",
                 "description": "policy work", "notes": "see PR #99 for trigger behaviour",
                 "comments": "the trigger fired on PR #99", "status": "open"}

    def test_the_number_is_what_identifies_a_forge_object(self):
        # The tokenizer drops "99" (two chars), so fuzzy matching cannot see it.
        cand = "alpha PR #99 untracked: chore: release v1.2.3"
        self.assertLess(rw.similarity(cand, self.TRACKER["title"]), 0.6)
        self.assertIsNotNone(rw.find_duplicate(cand, [self.TRACKER], repo="alpha"))

    def test_without_the_repo_arg_the_forge_path_is_not_used(self):
        cand = "alpha PR #99 untracked: chore: release v1.2.3"
        self.assertIsNone(rw.find_duplicate(cand, [self.TRACKER]))

    def test_a_COMMENT_ONLY_mention_does_not_dedupe(self):
        # Suppressing a real finding is the expensive direction: a duplicate is
        # visible and cheap to close, a suppressed finding is neither.
        self.assertFalse(rw.refers_to_forge_object(self.MENTIONER, "alpha", "99"))

    def test_the_TRACKING_bead_wins_over_a_mentioner(self):
        cand = "alpha PR #99 untracked: chore: release v1.2.3"
        hit = rw.find_duplicate(cand, [self.MENTIONER, self.TRACKER], repo="alpha")
        self.assertEqual(hit["id"], "t-1")

    def test_the_tracker_wins_regardless_of_corpus_order(self):
        cand = "alpha PR #99 untracked: chore: release v1.2.3"
        hit = rw.find_duplicate(cand, [self.TRACKER, self.MENTIONER], repo="alpha")
        self.assertEqual(hit["id"], "t-1")

    def test_a_different_repo_with_the_same_number_is_not_a_match(self):
        cand = "beta PR #99 untracked: something else"
        self.assertIsNone(rw.find_duplicate(cand, [self.TRACKER], repo="beta"))

    def test_the_reference_spellings_people_actually_use(self):
        for text in ("#99", "PR 99", "PR #99", "issue #99", "pull request 99"):
            self.assertIn("99", rw.forge_refs(text), text)

    def test_a_bare_number_is_not_a_forge_reference(self):
        # "99 routes" or "v0.99" must not read as issue 99.
        self.assertEqual(rw.forge_refs("99 routes were checked"), set())

    def test_a_re_found_open_watch_bead_updates_even_when_deferred(self):
        # Measured live: the real tracking bead was `deferred`, not `open`. Only
        # CLOSED means "dealt with"; every other state is still outstanding.
        deferred = dict(self.TRACKER, status="deferred")
        r = rw.triage(["alpha PR #99 untracked: chore: release v1.2.3"],
                      [deferred], repo="alpha")
        self.assertEqual(r.mint, [])
        self.assertEqual(len(r.update), 1)


class TestConflictingForgeMention(unittest.TestCase):
    candidate = "example/alpha issue #1 untracked: precision layer"
    mention = {"id": "closed-other", "status": "closed",
               "title": "alpha #2: position variants",
               "description": "Then #1 precision layer is next for example/alpha"}

    def test_closed_other_object_is_reported_not_suppressed_or_minted(self):
        r = rw.triage([self.candidate], [self.mention], repo="example/alpha")
        self.assertEqual(r.ambiguous, [(self.candidate, self.mention)])
        self.assertEqual(r.mint + r.duplicate + r.update + r.held, [])

    def test_real_closed_tracker_wins_in_either_order(self):
        tracker = dict(self.mention, id="tracker", title="example/alpha #1: precision")
        for corpus in ([self.mention, tracker], [tracker, self.mention]):
            r = rw.triage([self.candidate], corpus, repo="example/alpha")
            self.assertEqual(r.duplicate, [(self.candidate, tracker)])
            self.assertEqual(r.ambiguous, [])

    def test_description_tracker_without_conflicting_number_still_counts(self):
        tracker = dict(self.mention, title="alpha precision work")
        r = rw.triage([self.candidate], [tracker], repo="example/alpha")
        self.assertEqual(r.duplicate, [(self.candidate, tracker)])

    def test_other_repository_number_is_not_a_conflict(self):
        other = dict(self.mention, title="beta #2: position variants")
        self.assertFalse(rw.conflicting_forge_mention(self.candidate, other, "example/alpha"))

    def test_ambiguity_does_not_consume_mint_budget(self):
        r = rw.triage([self.candidate, "Unrelated fresh finding"], [self.mention],
                      cap=1, repo="example/alpha")
        self.assertEqual(r.mint, ["Unrelated fresh finding"])
        self.assertEqual(len(r.ambiguous), 1)
        self.assertEqual(r.held, [])

    def test_missing_repo_warns(self):
        with self.assertWarnsRegex(RuntimeWarning, "require repo="):
            rw.triage([self.candidate], [])

    def test_different_owner_same_short_name_is_not_conflict(self):
        other = dict(self.mention, title="other/alpha #2: variants")
        self.assertFalse(rw.conflicting_forge_mention(self.candidate, other, "example/alpha"))


# --- an anchor no other clone can reach (internal-ref) ----------------------
# Measured on shantytown's 2026-08-30 pass: the anchor was a LOCAL unpushed
# commit on a side branch — present in 1 of 36 clones and 0 remote refs — so the
# delta was UNCOMPUTABLE and the pass would have reported a clean first look on
# the repo with the highest churn of the night.

def _fake_git(**codes):
    """A git stub keyed by subcommand; returns rc from `codes`, default 0."""
    import subprocess

    def run(*args):
        sub = args[0]
        rc = codes.get(sub, 0)
        out = codes.get(f"{sub}_out", "")
        return subprocess.CompletedProcess(args, rc, out, "")
    return run


class TestVerifyAnchor(unittest.TestCase):
    """Collected by `python -m unittest` too (internal-ref): as bare module-level
    functions these six anchor-safety tests ran under pytest only, so the suite the
    SKILL.md tells you to run skipped every one of them."""

    def test_an_unreachable_anchor_RAISES_and_does_not_spell_itself_bootstrap(self):
        a = rw.Anchor(repo="shantytown", sha="5a301c7e", reachable=False,
                   remote="git@github.com:scbrown/shantytown.git")
        try:
            rw.code_range(a, "deadbeef")
        except rw.UnreachableAnchor as e:
            assert "5a301c7e" in str(e) and "UNCOMPUTABLE" in str(e)
        else:
            raise AssertionError(
                "an unreachable anchor must REFUSE; returning None spells it "
                "'bootstrap', which is the defect")


    def test_a_reachable_anchor_is_unaffected(self):
        """CONTROL. Without it, raising unconditionally would pass the test above
        while breaking every healthy pass."""
        a = rw.Anchor(repo="r", sha="aaa", reachable=True)
        assert rw.code_range(a, "bbb") == "aaa..bbb"
        assert rw.code_range(rw.Anchor(repo="r", sha=None), "bbb") is None   # real bootstrap
        assert rw.code_range(rw.Anchor(repo="r", sha="aaa"), "aaa") is None  # nothing moved


    def test_an_UNCHECKED_anchor_still_computes_its_range(self):
        """reachable=None means nobody asked. That must not become a refusal — it
        would break every caller that has not adopted rw.verify_anchor yet."""
        assert rw.code_range(rw.Anchor(repo="r", sha="aaa"), "bbb") == "aaa..bbb"


    def test_verify_anchor_refuses_when_the_sha_is_not_an_ancestor(self):
        a = rw.Anchor(repo="shantytown", sha="5a301c7e")
        try:
            rw.verify_anchor(a, "/nowhere", run=_fake_git(**{"merge-base": 1}))
        except rw.UnreachableAnchor as e:
            assert "5a301c7e" in str(e)
        else:
            raise AssertionError("rw.verify_anchor must refuse a non-ancestor anchor")


    def test_a_FAILED_FETCH_leaves_reachable_None_not_False(self):
        """'Could not ask' and 'asked, it is gone' have OPPOSITE remedies — re-run vs
        re-anchor — so an outage must not render as data loss."""
        a = rw.Anchor(repo="r", sha="aaa")
        got = rw.verify_anchor(a, "/nowhere", run=_fake_git(fetch=1))
        assert got.reachable is None, "a failed fetch must not assert unreachable"
        assert rw.code_range(got, "bbb") == "aaa..bbb"


    def test_bootstrap_records_the_remote_without_claiming_reachability(self):
        a = rw.Anchor(repo="r", sha=None)
        got = rw.verify_anchor(a, "/nowhere",
                            run=_fake_git(**{"remote_out": "git@github.com:x/y.git\n"}))
        assert got.remote == "git@github.com:x/y.git"
        assert got.reachable is None

    def test_verify_anchor_REFUSES_a_bare_sha_with_a_TypeError_that_names_Anchor(self):
        """The SKILL.md recipe says "record with git rev-parse", then verify_anchor(anchor, ...).
        Passing that sha string died with AttributeError: 'str' object has no attribute
        'remote' (internal-ref) - an error about nothing the caller wrote."""
        with self.assertRaises(TypeError) as cm:
            rw.verify_anchor("b7014d8", "/nowhere", run=_fake_git())
        self.assertIn("Anchor(", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
