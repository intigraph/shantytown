"""gate_verdict — signed review verdicts in Quipu, in place of GitHub approvals
(aegis-c01c.7).

WHY. Every crew PR and every review comes from ONE shared GitHub account, so a
GitHub "APPROVE by someone other than the author" can never exist and the login
cannot tell the author from the reviewer. The approval therefore lives in Quipu
as a record that names the reviewing AGENT, and the merge gate believes it only
when Quipu's own verifier path says the record is signed by a registered key.

WHAT IS WRITTEN (the chaski #49 contract, docs/github-routing.md there):

    <gate>    a aegis:GateApproval ;               camayoc agent-memory-entities 1.3
              aegis:aboutGitHubEntity <aegis:github.<PR node_id>> ;
              aegis:commitSha  "<40-hex head the reviewer read>" ;
              aegis:outcome    "approve" | "changes" ;
              aegis:by         "<reviewing agent>" ;
              aegis:recordedAt "<RFC 3339>" ;
              aegis:authorAgent "<PR author agent>" ;   (when known)
              aegis:evidence   "<link to the review comment>" ;
              aegis:evidenceHash "sha256:<digest of every field above>" .
    <verdict> a aegis:Verdict ;                    quipu governance.ttl VerdictShape
              aegis:predicateId PREDICATE_ID ; aegis:targetRef "<gate IRI>" ;
              aegis:outcome "satisfied" | "unsatisfied" ; aegis:tier "committed" ;
              aegis:evidenceHash (same) ; aegis:verifier SIGNER ; aegis:signature "<hex>" .

Two nodes, not one, because the vocabularies disagree on `aegis:outcome`: the
GateApproval/Decision shape wants approve|changes and chaski reads those words,
while `aegis:signature` has `rdfs:domain aegis:Verdict` and VerdictShape wants
satisfied|unsatisfied. The signed Verdict is ABOUT the GateApproval (its
targetRef), and its evidence hash covers every GateApproval field, so editing
any of them breaks the signature.

THE SIGNATURE is quipu's v1 verdict signature, byte for byte: ed25519 over
`signing::verdict_message` = `v1|predicate|target|outcome|evidence_hash|tier|verifier`
(quipu src/signing.rs). The merge gate re-derives the evidence hash from the
stored fields and requires BOTH (a) a valid signature under a key pinned in
/etc/shantytown/verdict-signers.json, a root-owned file only a human can write,
and (b) `trusted: true` from Quipu's POST /verdict/verify with the stored
verdict's IRI. Quipu alone is not enough: today any agent can write an
`aegis:VerifierRegistration` and self-enroll a key (review of #408). Records
are read from ONE configured graph, never any named graph. An unsigned, forged
or self-enrolled record is simply not an approval.

KEY CUSTODY is quipu's v1 posture: a host file (PKCS#8, 0600), created on first
use and untrusted until a human registers its public key. The signer is st on
the host (it signs only for a process proven to BE the review job), not the
agent: ephemeral agents are named per spawn, so no human could register theirs.
The agent runs as the same Unix user and could read the file; that residual gap
is the same one its gh credentials already are (docs/ephemeral-agents.md).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

AEGIS = "http://aegis.gastown.local/ontology/"
#: What the signer's VerifierRegistration must `aegis:attests`.
PREDICATE_ID = "github-pr-gate-approval"
TIER = "committed"
CLASSES = ("GateApproval", "Decision")   # Decision read through the 1.3 migration
APPROVE_WORDS = {"approve", "approved", "accept", "accepted"}             # = chaski
CHANGES_WORDS = {"changes", "request-changes", "changes_requested", "reject", "rejected"}
SIGNED_OUTCOME = {"approve": "satisfied", "changes": "unsatisfied"}

_SHA = re.compile(r"[0-9a-f]{40}")
_NODE = re.compile(r"[A-Za-z0-9_-]+")
_AGENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")
_REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
_STAMP = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ")


class VerdictError(Exception):
    """The record could not be built, written or read. Never an approval."""


# --- ed25519 (RFC 8032), so st signs without a dependency ----------------------
# Pure Python reference arithmetic: one signature per review, so speed is moot.
# Interoperates with quipu's `ring` verifier (RFC 8032 test vectors in tests).

_P = 2 ** 255 - 19
_L = 2 ** 252 + 27742317777372353535851937790883648493
_D = -121665 * pow(121666, _P - 2, _P) % _P
_SQRT_M1 = pow(2, (_P - 1) // 4, _P)


def _inv(x):
    return pow(x, _P - 2, _P)


def _add(a, b):
    x1, y1, z1, t1 = a
    x2, y2, z2, t2 = b
    aa = (y1 - x1) * (y2 - x2) % _P
    bb = (y1 + x1) * (y2 + x2) % _P
    cc = 2 * t1 * t2 * _D % _P
    dd = 2 * z1 * z2 % _P
    e, f, g, h = bb - aa, dd - cc, dd + cc, bb + aa
    return (e * f % _P, g * h % _P, f * g % _P, e * h % _P)


def _mul(s, p):
    q = (0, 1, 1, 0)
    while s > 0:
        if s & 1:
            q = _add(q, p)
        p = _add(p, p)
        s >>= 1
    return q


def _equal(a, b):
    return ((a[0] * b[2] - b[0] * a[2]) % _P == 0
            and (a[1] * b[2] - b[1] * a[2]) % _P == 0)


def _recover_x(y, sign):
    if y >= _P:
        return None
    x2 = (y * y - 1) * _inv(_D * y * y + 1)
    if x2 % _P == 0:
        return None if sign else 0
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P != 0:
        x = x * _SQRT_M1 % _P
    if (x * x - x2) % _P != 0:
        return None
    if (x & 1) != sign:
        x = _P - x
    return x


_GY = 4 * _inv(5) % _P
_GX = _recover_x(_GY, 0)
_G = (_GX, _GY, 1, _GX * _GY % _P)


def _compress(p):
    zinv = _inv(p[2])
    x, y = p[0] * zinv % _P, p[1] * zinv % _P
    return int.to_bytes(y | ((x & 1) << 255), 32, "little")


def _decompress(raw):
    if len(raw) != 32:
        return None
    y = int.from_bytes(raw, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    x = _recover_x(y, sign)
    return None if x is None else (x, y, 1, x * y % _P)


def _h(data):
    return int.from_bytes(hashlib.sha512(data).digest(), "little")


def _expand(seed):
    if len(seed) != 32:
        raise VerdictError("an ed25519 seed is 32 bytes")
    digest = hashlib.sha512(seed).digest()
    a = int.from_bytes(digest[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, digest[32:]


def public_key(seed: bytes) -> bytes:
    a, _prefix = _expand(seed)
    return _compress(_mul(a, _G))


def sign(seed: bytes, message: bytes) -> bytes:
    a, prefix = _expand(seed)
    pub = _compress(_mul(a, _G))
    r = _h(prefix + message) % _L
    rs = _compress(_mul(r, _G))
    s = (r + _h(rs + pub + message) * a) % _L
    return rs + int.to_bytes(s, 32, "little")


def verify(pub: bytes, message: bytes, signature: bytes) -> bool:
    """A local check, for tests and diagnostics. The merge gate never trusts
    this: trust needs the registry, which only Quipu holds."""
    if len(signature) != 64:
        return False
    a, r = _decompress(pub), _decompress(signature[:32])
    s = int.from_bytes(signature[32:], "little")
    if a is None or r is None or s >= _L:
        return False
    k = _h(signature[:32] + pub + message) % _L
    return _equal(_mul(s, _G), _add(r, _mul(k, a)))


def verdict_message(predicate_id, target_ref, outcome, evidence_hash, tier, verifier) -> bytes:
    """quipu src/signing.rs `verdict_message`, byte for byte."""
    return f"v1|{predicate_id}|{target_ref}|{outcome}|{evidence_hash}|{tier}|{verifier}".encode()


# --- key custody: quipu's v1 host file, in ring's PKCS#8 v2 layout --------------

_PKCS8_V2 = bytes.fromhex("3053020101300506032b657004220420")
_PKCS8_V1 = bytes.fromhex("302e020100300506032b657004220420")
_PKCS8_PUB = bytes.fromhex("a123032100")


def default_key_path() -> Path:
    if os.environ.get("ST_VERDICT_KEY"):
        return Path(os.environ["ST_VERDICT_KEY"])
    base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state")
    return base / "shantytown" / "verdict-signer.pk8"


def _seed_of(raw: bytes) -> bytes:
    if raw.startswith(_PKCS8_V2) and len(raw) == 85 and raw[48:53] == _PKCS8_PUB:
        seed = raw[16:48]
        if raw[53:] != public_key(seed):
            raise VerdictError("signing key file is inconsistent (public half does not match)")
        return seed
    if raw.startswith(_PKCS8_V1) and len(raw) == 48:
        return raw[16:48]
    raise VerdictError("signing key file is not an ed25519 PKCS#8 key")


def load_or_generate(path: Path) -> bytes:
    """The signer's 32-byte seed. Generated (0600, O_EXCL) on first use, like
    quipu's verifier.pk8; useless to anyone until a human registers its public key."""
    path = Path(path)
    if path.is_symlink():
        raise VerdictError(f"signing key {path} is a symlink; refused")
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        seed = secrets.token_bytes(32)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(_PKCS8_V2 + seed + _PKCS8_PUB + public_key(seed))
        return seed
    if path.stat().st_mode & 0o077:
        raise VerdictError(f"signing key {path} is readable by others; chmod 600 it")
    return _seed_of(path.read_bytes())


# --- the record -----------------------------------------------------------------

def pr_iri(node_id: str) -> str:
    """camayoc github_ingress.node_name: the same node chaski's facts are about."""
    if _NODE.fullmatch(node_id or ""):
        return f"{AEGIS}github.{node_id}"
    return f"{AEGIS}github.b" + hashlib.sha256((node_id or "").encode()).hexdigest()[:32]


def outcome_word(verdict: str | None) -> str | None:
    word = (verdict or "").strip().lower()
    return "approve" if word in APPROVE_WORDS else "changes" if word in CHANGES_WORDS else None


def now_stamp(now: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))


@dataclass(frozen=True)
class GateApproval:
    repo: str
    pr: int
    pr_node: str
    head: str
    outcome: str            # approve | changes
    by: str                 # the reviewing agent
    recorded_at: str        # YYYY-MM-DDTHH:MM:SSZ
    evidence: str = ""      # link to the review (the PR comment)
    author_agent: str | None = None

    def check(self) -> None:
        if not _REPO.fullmatch(self.repo or "") or not isinstance(self.pr, int) or self.pr < 1:
            raise VerdictError("repo must be owner/name and pr a positive number")
        if not _SHA.fullmatch(self.head or ""):
            raise VerdictError("head must be the full 40-hex SHA that was reviewed")
        if self.outcome not in SIGNED_OUTCOME:
            raise VerdictError("outcome must be approve or changes")
        if not _AGENT.fullmatch(self.by or ""):
            raise VerdictError("by must be an agent name")
        if self.author_agent is not None and not _AGENT.fullmatch(self.author_agent):
            raise VerdictError("author agent must be an agent name")
        if not self.pr_node:
            raise VerdictError("the PR's GitHub node id is required")
        if not _STAMP.fullmatch(self.recorded_at or ""):
            raise VerdictError("recorded_at must be YYYY-MM-DDTHH:MM:SSZ")
        if any(c in (self.evidence or "") for c in '\n\r"\\<>'):
            raise VerdictError("evidence must be a plain link")
        if self.author_agent and self.author_agent.lower() == self.by.lower():
            raise VerdictError("the PR's author agent cannot review it")

    @property
    def pr_iri(self) -> str:
        return pr_iri(self.pr_node)

    def _suffix(self) -> str:
        return hashlib.sha256(
            f"{self.pr_iri}|{self.head}|{self.by}|{self.recorded_at}".encode()).hexdigest()[:32]

    @property
    def iri(self) -> str:
        return f"{AEGIS}gate_approval.{self._suffix()}"

    @property
    def verdict_iri(self) -> str:
        return f"{AEGIS}gate_verdict.{self._suffix()}"

    def evidence_hash(self) -> str:
        """Every GateApproval field, so the signature over it seals them all."""
        fields = (("repo", self.repo), ("pr", str(self.pr)), ("pr_iri", self.pr_iri),
                  ("head", self.head), ("outcome", self.outcome), ("by", self.by),
                  ("author_agent", self.author_agent or ""), ("evidence", self.evidence or ""),
                  ("recorded_at", self.recorded_at))
        canon = "aegis-gate-approval-v1\n" + "".join(f"{k}={v}\n" for k, v in fields)
        return "sha256:" + hashlib.sha256(canon.encode()).hexdigest()

    def message(self, verifier: str) -> bytes:
        return verdict_message(PREDICATE_ID, self.iri, SIGNED_OUTCOME[self.outcome],
                               self.evidence_hash(), TIER, verifier)

    def turtle(self, verifier: str | None = None, signature: str | None = None) -> str:
        """Both nodes. Without a signature only the GateApproval is built: that
        is all a forger without the key can honestly write."""
        self.check()
        lit = json.dumps
        gate = ["a aegis:GateApproval", f"aegis:aboutGitHubEntity <{self.pr_iri}>",
                f"aegis:commitSha {lit(self.head)}", f"aegis:outcome {lit(self.outcome)}",
                f"aegis:by {lit(self.by)}", f"aegis:recordedAt {lit(self.recorded_at)}",
                f"aegis:evidenceHash {lit(self.evidence_hash())}"]
        if self.evidence:
            gate.append(f"aegis:evidence {lit(self.evidence)}")
        if self.author_agent:
            gate.append(f"aegis:authorAgent {lit(self.author_agent)}")
        out = f"@prefix aegis: <{AEGIS}> .\n<{self.iri}> " + " ;\n    ".join(gate) + " .\n"
        if signature is not None:
            ver = ["a aegis:Verdict", f"aegis:predicateId {lit(PREDICATE_ID)}",
                   f"aegis:targetRef {lit(self.iri)}",
                   f"aegis:outcome {lit(SIGNED_OUTCOME[self.outcome])}",
                   f"aegis:evidenceHash {lit(self.evidence_hash())}", f"aegis:tier {lit(TIER)}",
                   f"aegis:verifier {lit(verifier)}", f"aegis:signature {lit(signature)}"]
            out += f"<{self.verdict_iri}> " + " ;\n    ".join(ver) + " .\n"
        return out


def signed_turtle(record: GateApproval, *, seed: bytes, verifier: str) -> str:
    record.check()
    if not verifier or any(c in verifier for c in '"\\\n|<>'):
        raise VerdictError("verifier must be a plain key id")
    return record.turtle(verifier, sign(seed, record.message(verifier)).hex())


# --- Quipu transport (injected in tests) ----------------------------------------

class Quipu:
    """The three calls this needs, over Quipu's public REST surface."""

    def __init__(self, server: str, *, timeout: float = 15.0, client: str = "st-gate-verdict"):
        self.server, self.timeout, self.client = server.rstrip("/"), timeout, client

    def _post(self, path: str, body: dict, headers: dict) -> dict:
        req = urllib.request.Request(self.server + path, data=json.dumps(body).encode(),
                                     headers={**headers, "X-Quipu-Client": self.client},
                                     method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                out = json.loads(resp.read(4_000_001))
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise VerdictError(f"quipu {path} failed: {exc}") from exc
        if not isinstance(out, dict) or out.get("error"):
            raise VerdictError(f"quipu {path} refused: {str(out)[:200]}")
        return out

    def query(self, sparql: str) -> list[dict]:
        from .quipu import request_headers
        out = self._post("/query", {"query": sparql, "verbose": True}, request_headers())
        if out.get("truncated") or not isinstance(out.get("rows"), list):
            raise VerdictError("quipu /query answer incomplete")
        return out["rows"]

    def knot(self, turtle: str, graph: str | None) -> None:
        from . import quipu_auth
        try:
            headers = quipu_auth.write_headers(self.server)
        except quipu_auth.CredentialRefused as exc:
            raise VerdictError(str(exc)) from None
        body = {"turtle": turtle, **({"graph": graph} if graph else {})}
        out = self._post("/knot", body, headers)
        if out.get("conforms") is False:   # a SHACL refusal has no "error" key (aegis-0v97)
            issues = "; ".join(f"{i.get('path', '?')}: {i.get('message', '?')}"
                               for i in (out.get("issues") or [])[:3])
            raise VerdictError(f"quipu refused the record (SHACL): {issues or out}")

    def verify(self, payload: dict) -> dict:
        from .quipu import request_headers
        return self._post("/verdict/verify", payload, request_headers())


def write(record: GateApproval, *, quipu, graph: str | None, seed: bytes, verifier: str) -> str:
    """Sign and store one verdict record; returns the GateApproval IRI."""
    quipu.knot(signed_turtle(record, seed=seed, verifier=verifier), graph)
    return record.iri


def write_authorship(*, quipu, graph: str | None, node_id: str, agent: str) -> str:
    """`<PR> aegis:authoredByAgent "<agent>"`: lets chaski and the merge gate
    tell the PR's author agent from its reviewer under one GitHub login."""
    if not _AGENT.fullmatch(agent or ""):
        raise VerdictError("author agent must be an agent name")
    iri = pr_iri(node_id)
    quipu.knot(f"@prefix aegis: <{AEGIS}> .\n<{iri}> aegis:authoredByAgent {json.dumps(agent)} .\n",
               graph)
    return iri


# --- the trust root: human-pinned signer keys ------------------------------------
#
# Review #408: quipu's /verdict/verify trusts ANY `aegis:VerifierRegistration`
# in ROOT, and an agent can write one (measured: a reviewer enrolled its own key
# with one unsigned write and the gate approved). So Quipu's "trusted" is never
# enough here. The signer's public key must ALSO be pinned in a file only root
# can write (the advise-signing policy pattern): a human sets it with sudo, and
# no agent, author or reviewer, can add a key. The signature is checked locally
# against that pinned key, so a registration in Quipu cannot widen trust.

TRUSTED_SIGNERS_PATH = Path("/etc/shantytown/verdict-signers.json")
TRUSTED_SIGNERS_OWNER = 0
_HEX_KEY = re.compile(r"[0-9a-f]{64}")


def trusted_signers(path: Path | None = None, owner: int | None = None) -> dict[str, str]:
    """{verifier id: public key hex} from the root-owned pin file, or {} (fail
    closed) when it is absent or not root-owned, private-to-root-writes and
    well-formed. Shape: {"version": 1, "signers": {"st-review.vati": "<64 hex>"}}."""
    from .advise_signing import _read
    path = TRUSTED_SIGNERS_PATH if path is None else Path(path)
    owner = TRUSTED_SIGNERS_OWNER if owner is None else owner
    try:
        doc = json.loads(_read(path, owner, 65536))
    except (OSError, ValueError):
        return {}
    signers = doc.get("signers") if isinstance(doc, dict) and doc.get("version") == 1 else None
    if not isinstance(signers, dict):
        return {}
    return {k: v for k, v in signers.items()
            if isinstance(k, str) and k and isinstance(v, str) and _HEX_KEY.fullmatch(v)}


# --- reading: the merge gate's approval source ----------------------------------

def _cell(row: dict, key: str) -> str | None:
    value = row.get(key)
    if isinstance(value, dict):
        value = value.get("value")
    return None if value is None else str(value)


def _local(value: str | None) -> str | None:
    if value is None:
        return None
    if value.startswith("http"):
        value = value.rstrip("/").rsplit("/", 1)[-1].rsplit("#", 1)[-1]
    elif value.startswith("aegis:"):
        value = value[len("aegis:"):]
    return value.lower() or None


def _graph(graph: str) -> str:
    if not graph or any(c in graph for c in ' <>"{}|\\^`\n'):
        raise VerdictError("verdict records are read from ONE configured graph IRI")
    return graph


def gates_query(pr: str, head: str, graph: str) -> str:
    classes = ", ".join(f"aegis:{c}" for c in CLASSES)
    return ("PREFIX aegis: <%s> SELECT (STR(?v) AS ?gate) ?outcome ?by ?at ?author ?evidence "
            "WHERE { GRAPH <%s> { ?v a ?t ; aegis:aboutGitHubEntity <%s> ; aegis:commitSha %s ; "
            "aegis:outcome ?outcome ; aegis:by ?by ; aegis:recordedAt ?at . "
            "OPTIONAL { ?v aegis:authorAgent ?author } OPTIONAL { ?v aegis:evidence ?evidence } "
            "FILTER(?t IN (%s)) } }" % (AEGIS, _graph(graph), pr, json.dumps(head), classes))


def verdicts_query(gates: list[str], graph: str) -> str:
    values = " ".join(json.dumps(g) for g in gates)
    return ("PREFIX aegis: <%s> SELECT (STR(?ver) AS ?verdict) ?target ?verifier ?sig WHERE { "
            "VALUES ?target { %s } GRAPH <%s> { ?ver aegis:targetRef ?target ; "
            "aegis:predicateId %s ; aegis:verifier ?verifier ; aegis:signature ?sig } }"
            % (AEGIS, values, _graph(graph), json.dumps(PREDICATE_ID)))


def authors_query(pr: str, graph: str) -> str:
    return ("PREFIX aegis: <%s> SELECT ?agent WHERE { GRAPH <%s> { <%s> aegis:authoredByAgent ?agent } }"
            % (AEGIS, _graph(graph), pr))


def author_agent(quipu, node_id: str, *, graph: str) -> str | None:
    """The PR's declared author agent, from the configured graph only; None
    when absent OR ambiguous."""
    agents = {_local(_cell(r, "agent"))
              for r in quipu.query(authors_query(pr_iri(node_id), graph))}
    agents.discard(None)
    return next(iter(agents)) if len(agents) == 1 else None


def approval(quipu, *, repo: str, pr: int, node_id: str, head: str, graph: str,
             signers: dict[str, str]) -> dict:
    """The verified agent-verdict approval state of exactly `head`.

    The rules are chaski #49's (`github_routes.approval`), plus the signature:
    only records Quipu reports `trusted` count at all; a verdict by the PR's
    author agent never counts; each other agent's latest word on the head
    counts; an approval with no `changes` approves; an unknown author agent
    approves nothing (fail closed). Raises VerdictError when Quipu cannot be
    read, which the caller treats as "not approved".

    Trust is BOTH Quipu's `trusted` and a valid signature under a key pinned in
    `signers` (trusted_signers()), whose id is not an agent in this PR. Every
    record is read from the one configured `graph`, never any named graph."""
    if not _SHA.fullmatch(head or ""):
        raise VerdictError("head must be the full 40-hex SHA")
    gates = {}
    for r in quipu.query(gates_query(pr_iri(node_id), head, graph)):
        gate = _cell(r, "gate")
        if gate:
            gates[gate] = r
    signed: dict[str, list[dict]] = {}
    if gates:
        for r in quipu.query(verdicts_query(sorted(gates), graph)):
            signed.setdefault(_cell(r, "target") or "", []).append(r)
    declared = author_agent(quipu, node_id, graph=graph)
    ignored, words, stated_authors = [], {}, set()
    for gate, r in sorted(gates.items()):
        author = _cell(r, "author")
        record = GateApproval(repo=repo, pr=pr, pr_node=node_id, head=head,
                              outcome=outcome_word(_cell(r, "outcome")) or "",
                              by=_cell(r, "by") or "", recorded_at=_cell(r, "at") or "",
                              evidence=_cell(r, "evidence") or "", author_agent=author)
        try:
            record.check()
        except VerdictError as exc:
            ignored.append({"record": gate, "why": f"malformed: {exc}"})
            continue
        if record.iri != gate:
            ignored.append({"record": gate, "why": "its IRI does not match its fields"})
            continue
        trusted, why_not = False, "no trusted signature (unsigned, forged, or the signer is not registered)"
        for v in signed.get(gate, []):
            verifier, sig = _cell(v, "verifier") or "", _cell(v, "sig") or ""
            pinned = signers.get(verifier)
            if pinned is None:
                why_not = f"signer {verifier!r} is not pinned in {TRUSTED_SIGNERS_PATH}"
                continue
            if verifier.lower() in {record.by.lower(), (author or "").lower(), (declared or "")}:
                why_not = "the signer id is an agent of this PR"
                continue
            try:
                ok = verify(bytes.fromhex(pinned), record.message(verifier), bytes.fromhex(sig))
            except ValueError:
                ok = False
            if not ok:
                why_not = "signature does not verify under the pinned key"
                continue
            answer = quipu.verify({
                "predicate_id": PREDICATE_ID, "target_ref": gate,
                "outcome": SIGNED_OUTCOME[record.outcome],
                "evidence_hash": record.evidence_hash(), "tier": TIER,
                "verifier": verifier, "signature": sig,
                "verdict": _cell(v, "verdict") or ""})
            if answer.get("trusted") is True:
                trusted = True
                break
            why_not = "quipu does not report the recorded signature as trusted"
        if not trusted:
            ignored.append({"record": gate, "why": why_not})
            continue
        if author:
            stated_authors.add(author.lower())
        key = record.by.lower()
        if key not in words or record.recorded_at >= words[key]["at"]:
            words[key] = {"by": key, "verdict": record.outcome, "at": record.recorded_at,
                          "record": gate}
    the_author = declared or (next(iter(stated_authors)) if len(stated_authors) == 1 else None)
    if the_author and the_author in words:
        ignored.append({"record": words.pop(the_author)["record"], "why": "by the PR's author agent"})
    approvals = [w for w in words.values() if w["verdict"] == "approve"]
    blocking = [w for w in words.values() if w["verdict"] == "changes"]
    return {"approved": bool(approvals) and not blocking and the_author is not None,
            "approvals": approvals, "blocking": blocking, "author_agent": the_author,
            "author_agent_unknown": the_author is None, "ignored": ignored}


def lane_release_argv(base: list[str], request_id: str, outcome: str) -> list[str]:
    """chaski-github-work's `lane release` (chaski #49), for a merge job that
    ended without merging. `base` is the configured command prefix."""
    if not re.fullmatch(r"[0-9a-f]{64}", request_id or ""):
        raise VerdictError("lane release needs the work request's 64-hex request_id")
    if outcome not in ("blocked", "failed", "stopped", "closed", "merged"):
        raise VerdictError(f"unknown lane outcome {outcome!r}")
    return [*base, "lane", "release", "--request", request_id, "--outcome", outcome]


def work_request(description: str | None) -> dict | None:
    """The chaski work request JSON a routed seeds item carries in its body
    (chaski #49 handoff contract), or None."""
    if not description:
        return None
    start = description.find("{")
    while start != -1:
        try:
            obj, _end = json.JSONDecoder().raw_decode(description[start:])
        except ValueError:
            obj = None
        if isinstance(obj, dict) and obj.get("schema") == "chaski.github.work-request/v1":
            return obj
        start = description.find("{", start + 1)
    return None
