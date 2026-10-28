"""Signed review verdicts in Quipu stand in for GitHub approvals (aegis-c01c.7).

One shared GitHub account means a non-author GitHub APPROVE never exists, so
the guarded merge accepts a GateApproval record signed through quipu's verdict
path. Every rule gets a test that shows it saying NO: an unsigned, forged,
tampered, author-written or wrong-head verdict must never approve.

The fake Quipu below runs the real SPARQL (rdflib) and verifies exactly as
quipu's `tool_verdict_verify` does: the verdict message of signing.rs, a key
registered to the verifier FOR the predicate, and a signature that the store
actually recorded on the named verdict."""
from __future__ import annotations

import json
import os
import stat

import pytest

rdflib = pytest.importorskip("rdflib")

from shantytown import cli, config  # noqa: E402
from shantytown import ephemeral as eph  # noqa: E402
from shantytown import gate_verdict as gv  # noqa: E402
from shantytown import pr_preflight  # noqa: E402

HEAD = "a" * 40
NODE = "PR_kwDOExample42"
GRAPH = "urn:aegis:graph:gate-approvals"
SEED = bytes(range(32))
OTHER_SEED = bytes(range(1, 33))
SIGNER = "st-review.testhost"
NOW = 1_800_000_000.0
REAL_TRUSTED_SIGNERS = gv.trusted_signers     # before the autouse pin below patches it


class FakeQuipu:
    def __init__(self):
        self.ds = rdflib.Dataset()
        self.registry = {}          # verifier -> (public key hex, predicate)
        self.knots = []

    def register(self, verifier, seed, predicate=gv.PREDICATE_ID):
        self.registry[verifier] = (gv.public_key(seed).hex(), predicate)

    def knot(self, turtle, graph):
        self.knots.append((turtle, graph))
        self.ds.graph(rdflib.URIRef(graph or "urn:x-root")).parse(data=turtle, format="turtle")

    def query(self, sparql):
        rows = []
        for r in self.ds.query(sparql):
            rows.append({k: (None if v is None else str(v)) for k, v in r.asdict().items()})
        return rows

    def verify(self, p):
        # quipu witness_from: the verdict must carry exactly this signature.
        recorded = any(True for _ in self.ds.quads((rdflib.URIRef(p["verdict"]),
                                                    rdflib.URIRef(gv.AEGIS + "signature"),
                                                    rdflib.Literal(p["signature"]), None)))
        if not recorded:
            raise gv.VerdictError("verdict has no recorded aegis:signature with that value")
        key = self.registry.get(p["verifier"])
        msg = gv.verdict_message(p["predicate_id"], p["target_ref"], p["outcome"],
                                 p["evidence_hash"], p.get("tier", "committed"), p["verifier"])
        try:
            sig = bytes.fromhex(p["signature"])
        except ValueError:
            sig = b""
        ok = bool(key) and key[1] == p["predicate_id"] and gv.verify(bytes.fromhex(key[0]), msg, sig)
        return {"signature_valid": ok, "trusted": ok, "as_of": {"basis": "recorded"}}


def _record(**kw):
    base = dict(repo="o/n", pr=5, pr_node=NODE, head=HEAD, outcome="approve",
                by="eph-review-aaaaaa", recorded_at="2026-10-28T08:00:00Z",
                evidence="https://github.com/o/n/pull/5#issuecomment-1", author_agent="lex")
    base.update(kw)
    return gv.GateApproval(**base)


@pytest.fixture
def q():
    quipu = FakeQuipu()
    quipu.register(SIGNER, SEED)
    return quipu


PINNED = {SIGNER: gv.public_key(SEED).hex()}


def _approval(q, head=HEAD, signers=PINNED, graph=GRAPH):
    return gv.approval(q, repo="o/n", pr=5, node_id=NODE, head=head, graph=graph,
                       signers=signers)


# --- the signature is quipu's ---------------------------------------------------

def test_ed25519_matches_rfc8032_vectors_so_quipus_ring_verifier_agrees():
    s1 = bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60")
    assert gv.public_key(s1).hex() == "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
    assert gv.sign(s1, b"").hex() == (
        "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155"
        "5fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b")
    s2 = bytes.fromhex("4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb")
    sig2 = gv.sign(s2, b"\x72")
    assert sig2.hex() == ("92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da"
                          "085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00")
    assert gv.verify(gv.public_key(s2), b"\x72", sig2)
    assert not gv.verify(gv.public_key(s2), b"\x73", sig2)


def test_the_signed_message_is_quipus_verdict_message_byte_for_byte():
    # quipu src/signing.rs: format!("v1|{predicate_id}|{target_ref}|{outcome}|{evidence_hash}|{tier}|{verifier}")
    assert gv.verdict_message("p", "t", "satisfied", "sha256:x", "committed", "v") == \
        b"v1|p|t|satisfied|sha256:x|committed|v"
    r = _record()
    assert r.message(SIGNER) == (f"v1|{gv.PREDICATE_ID}|{r.iri}|satisfied|"
                                 f"{r.evidence_hash()}|committed|{SIGNER}").encode()


def test_signer_key_file_is_private_ring_pkcs8_and_round_trips(tmp_path):
    path = tmp_path / "k" / "verdict-signer.pk8"
    seed = gv.load_or_generate(path)
    raw = path.read_bytes()
    assert len(raw) == 85 and raw[53:] == gv.public_key(seed)       # ring's v2 layout
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert gv.load_or_generate(path) == seed
    os.chmod(path, 0o644)
    with pytest.raises(gv.VerdictError, match="readable by others"):
        gv.load_or_generate(path)


# --- what counts as an approval --------------------------------------------------

def test_a_signed_verdict_from_a_non_author_agent_approves_its_head(q):
    gv.write(_record(), quipu=q, graph=GRAPH, seed=SEED, verifier=SIGNER)
    turtle, graph = q.knots[0]
    assert graph == GRAPH and "aegis:GateApproval" in turtle and "aegis:Verdict" in turtle
    out = _approval(q)
    assert out["approved"] and out["author_agent"] == "lex"
    assert [a["by"] for a in out["approvals"]] == ["eph-review-aaaaaa"]


def test_a_forged_unsigned_verdict_is_ignored(q):
    """The forger writes a perfect GateApproval but has no key: no Verdict node."""
    q.knot(_record().turtle(), GRAPH)
    out = _approval(q)
    assert not out["approved"] and out["approvals"] == []
    assert "no trusted signature" in out["ignored"][0]["why"]


def test_a_verdict_signed_with_an_unregistered_key_is_ignored(q):
    gv.write(_record(), quipu=q, graph=GRAPH, seed=OTHER_SEED, verifier=SIGNER)
    assert not _approval(q)["approved"]
    q2 = FakeQuipu()
    q2.register("someone-else", SEED)                      # key registered, wrong verifier
    gv.write(_record(), quipu=q2, graph=GRAPH, seed=SEED, verifier=SIGNER)
    assert not _approval(q2)["approved"]
    q3 = FakeQuipu()
    q3.register(SIGNER, SEED, predicate="some-other-predicate")   # not authorized for it
    gv.write(_record(), quipu=q3, graph=GRAPH, seed=SEED, verifier=SIGNER)
    assert not _approval(q3)["approved"]


def test_a_garbage_signature_on_a_verdict_node_is_ignored(q):
    r = _record()
    q.knot(r.turtle(SIGNER, "00" * 64), GRAPH)
    assert not _approval(q)["approved"]


def test_editing_a_signed_record_breaks_it(q):
    """Approve-then-sneak-in: the evidence hash seals every field."""
    r = _record()
    gv.write(r, quipu=q, graph=GRAPH, seed=SEED, verifier=SIGNER)
    g = q.ds.graph(rdflib.URIRef(GRAPH))
    g.set((rdflib.URIRef(r.iri), rdflib.URIRef(gv.AEGIS + "authorAgent"), rdflib.Literal("mallory")))
    assert not _approval(q)["approved"]
    q2 = FakeQuipu()
    q2.register(SIGNER, SEED)
    gv.write(r, quipu=q2, graph=GRAPH, seed=SEED, verifier=SIGNER)
    g2 = q2.ds.graph(rdflib.URIRef(GRAPH))
    g2.set((rdflib.URIRef(r.iri), rdflib.URIRef(gv.AEGIS + "by"), rdflib.Literal("eph-review-bbbbbb")))
    assert not _approval(q2)["approved"]


def test_the_author_agent_can_never_approve_its_own_pr(q):
    with pytest.raises(gv.VerdictError, match="author agent cannot review"):
        _record(by="lex").check()
    # Declared authorship beats a verdict that claims a different author.
    gv.write_authorship(quipu=q, graph=GRAPH, node_id=NODE, agent="eph-review-aaaaaa")
    gv.write(_record(author_agent=None), quipu=q, graph=GRAPH, seed=SEED, verifier=SIGNER)
    out = _approval(q)
    assert not out["approved"] and out["ignored"][-1]["why"] == "by the PR's author agent"


def test_an_unknown_author_agent_approves_nothing(q):
    gv.write(_record(author_agent=None), quipu=q, graph=GRAPH, seed=SEED, verifier=SIGNER)
    out = _approval(q)
    assert not out["approved"] and out["author_agent_unknown"]


def test_a_verdict_on_another_head_counts_for_nothing(q):
    gv.write(_record(head="b" * 40), quipu=q, graph=GRAPH, seed=SEED, verifier=SIGNER)
    assert not _approval(q)["approved"]
    assert _approval(q, head="b" * 40)["approved"]


def test_a_later_changes_verdict_blocks_and_the_latest_word_per_reviewer_counts(q):
    gv.write(_record(), quipu=q, graph=GRAPH, seed=SEED, verifier=SIGNER)
    gv.write(_record(by="eph-review-bbbbbb", outcome="changes",
                     recorded_at="2026-10-28T08:05:00Z"), quipu=q, graph=GRAPH, seed=SEED,
             verifier=SIGNER)
    out = _approval(q)
    assert not out["approved"] and [b["by"] for b in out["blocking"]] == ["eph-review-bbbbbb"]
    gv.write(_record(by="eph-review-bbbbbb", recorded_at="2026-10-28T08:10:00Z"),
             quipu=q, graph=GRAPH, seed=SEED, verifier=SIGNER)
    assert _approval(q)["approved"]


# --- the guarded merge accepts it --------------------------------------------------

def _pr(**kw):
    pr = {"head": {"sha": HEAD}, "state": "open", "merged": False, "draft": False,
          "author_association": "MEMBER", "user": {"login": "scbrown"}, "node_id": NODE}
    pr.update(kw)
    return pr


GREEN = [{"name": "ci", "status": "completed", "conclusion": "success"}]
MERGE = {"name": "eph-merge-aaaaaa", "job": "merge", "state": eph.LIVE, "head": HEAD}
APPROVED = {"approved": True, "approvals": [{"by": "eph-review-aaaaaa"}], "blocking": []}


def test_merge_gate_takes_a_verified_verdict_instead_of_a_github_review():
    assert eph.merge_gate(MERGE, HEAD, _pr(), [], GREEN, APPROVED) == ""
    assert "no non-author APPROVE" in eph.merge_gate(MERGE, HEAD, _pr(), [], GREEN, None)
    assert "no non-author APPROVE" in eph.merge_gate(
        MERGE, HEAD, _pr(), [], GREEN, {"approved": False, "approvals": [], "blocking": []})
    assert "requests changes" in eph.merge_gate(
        MERGE, HEAD, _pr(), [], GREEN, dict(APPROVED, blocking=[{"by": "x"}]))
    # Same-login GitHub "approval" (the shared account) still never counts.
    self_review = [{"user": {"login": "scbrown"}, "state": "APPROVED", "commit_id": HEAD}]
    assert "no non-author APPROVE" in eph.merge_gate(MERGE, HEAD, _pr(), self_review, GREEN)


def test_merge_gate_merges_only_the_items_head():
    assert "exactly the item's head" in eph.merge_gate(
        dict(MERGE, head="c" * 40), HEAD, _pr(), [], GREEN, APPROVED)


@pytest.fixture
def root(tmp_path, monkeypatch):
    r = tmp_path / ".shanty"
    (r / "crew").mkdir(parents=True)
    (r / "shantytown.toml").write_text(
        f'[ephemeral]\nmax_agents = 5\nverdict_graph = "{GRAPH}"\n'
        f'verdict_signer = "{SIGNER}"\nverdict_key = "{tmp_path / "signer.pk8"}"\n'
        'lane_release = ["chaski-github-work", "--config", "/etc/chaski/r.yaml"]\n')
    key = tmp_path / "signer.pk8"
    fd = os.open(key, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(gv._PKCS8_V2 + SEED + gv._PKCS8_PUB + gv.public_key(SEED))
    monkeypatch.delenv("SHANTY_AGENT", raising=False)
    return r


def _rec(root, **kw):
    job = kw.pop("job", "merge")
    req = eph.Request(job=job, item="it-1", repo="o/n", pr=5,
                      head=kw.pop("head", HEAD if job == "merge" else None),
                      request_id=kw.pop("request_id", None))
    rec = eph.plan(req, root=root, policy=config.Ephemeral(max_agents=10), actor=None,
                   administrator="boss", host=None, now=NOW, role_of=lambda n: None)
    rec.update(kw)
    eph.write(root, rec)
    return rec


def _args(root, *argv):
    a = cli._parse_args(["--root", str(root), "agent", "spawn", *argv])
    a.root = root
    return a


class _R:
    returncode, stdout, stderr = 0, "", ""


@pytest.fixture(autouse=True)
def _pinned(monkeypatch):
    monkeypatch.setattr(gv, "trusted_signers", lambda *a, **k: dict(PINNED))


def test_guarded_merge_merges_on_a_signed_verdict_with_no_github_review(root, q):
    gv.write(_record(), quipu=q, graph=GRAPH, seed=SEED, verifier=SIGNER)
    rec = _rec(root, state=eph.LIVE)
    reads = {"repos/o/n/pulls/5": _pr(), "repos/o/n/pulls/5/reviews?per_page=100": [],
             f"repos/o/n/commits/{HEAD}/check-runs?per_page=100": {"check_runs": GREEN}}
    ran = []
    a = _args(root, "--merge", "--head", HEAD)
    assert cli._spawn_merge(a, rec["name"], gh=reads.__getitem__, quipu=q,
                            run=lambda argv, **k: ran.append(argv) or _R()) == cli.OK
    assert ran == [["gh", "pr", "merge", "5", "--repo", "o/n", "--squash",
                    "--match-head-commit", HEAD]]


def test_guarded_merge_refuses_a_forged_unsigned_verdict(root, q):
    q.knot(_record().turtle(), GRAPH)
    rec = _rec(root, state=eph.LIVE)
    reads = {"repos/o/n/pulls/5": _pr(), "repos/o/n/pulls/5/reviews?per_page=100": [],
             f"repos/o/n/commits/{HEAD}/check-runs?per_page=100": {"check_runs": GREEN}}
    with pytest.raises(eph.Refused, match="no non-author APPROVE"):
        cli._spawn_merge(_args(root, "--merge", "--head", HEAD), rec["name"],
                         gh=reads.__getitem__, quipu=q, run=lambda *a, **k: 1 / 0)


# --- the review job writes the record ----------------------------------------------

def test_a_review_report_writes_a_signed_record_the_merge_gate_accepts(root, q):
    gv.write_authorship(quipu=q, graph=GRAPH, node_id=NODE, agent="lex")
    rec = _rec(root, job="review", state=eph.LIVE)
    note, problem = cli._spawn_write_verdict(
        _args(root, "--report"), rec, "approve", HEAD, "https://github.com/o/n/pull/5#c1",
        gh=lambda path: _pr(), quipu=q, now=NOW)
    assert problem == "" and "signed verdict record" in note
    out = _approval(q)
    assert out["approved"] and out["approvals"][0]["by"] == rec["name"]
    assert out["author_agent"] == "lex"


def test_review_verdict_writes_nothing_when_off_and_never_for_other_jobs(root, q, tmp_path):
    rec = _rec(root, job="review", state=eph.LIVE)
    assert cli._spawn_write_verdict(_args(root, "--report"), dict(rec, job="task"), "done",
                                    HEAD, "", gh=1 / 1, quipu=q) == ("", "")
    off = tmp_path / "off"
    (off / "crew").mkdir(parents=True)
    note, problem = cli._spawn_write_verdict(_args(off, "--report"), rec, "approve", HEAD, "",
                                             gh=lambda p: _pr(), quipu=q)
    assert "verdict_graph is unset" in problem and q.knots == []


def test_a_review_report_without_the_head_is_refused(root, monkeypatch, capsys):
    rec = _rec(root, job="review", state=eph.LIVE)
    monkeypatch.setattr(cli, "_spawn_inside", lambda a, **kw: rec["name"])
    assert cli.main(["--root", str(root), "agent", "spawn", "--report", "--verdict",
                     "approve", "--summary", "ok"]) == cli.REFUSED
    assert "--head" in capsys.readouterr().err


# --- the merge job: exact head, lane freed on no-merge ------------------------------

REQ_ID = "f" * 64


def test_a_merge_job_needs_a_pinned_head():
    with pytest.raises(eph.Refused, match="exactly the item's head"):
        eph.validate(eph.Request(job="merge", item="it-1", repo="o/n", pr=5))


def test_the_merge_head_comes_from_the_items_chaski_request(root, monkeypatch):
    body = "routed by chaski\n" + json.dumps({
        "schema": "chaski.github.work-request/v1", "request_id": REQ_ID, "kind": "merge",
        "repo": "o/n", "subject": "pr/5", "revision": HEAD, "facts": {"pr": 5}})
    assert gv.work_request(body)["revision"] == HEAD

    class Item:
        id, description = "it-1", body
    monkeypatch.setattr(cli, "_tracker", lambda a: type("T", (), {"get": lambda s, i: Item()})())
    a = _args(root, "--list")
    assert cli._spawn_merge_pin(a, None, "it-1", "o/n", 5) == (HEAD, REQ_ID)
    with pytest.raises(eph.Refused, match="Merge exactly the item's head"):
        cli._spawn_merge_pin(a, "b" * 40, "it-1", "o/n", 5)
    with pytest.raises(eph.Refused, match="not a merge of o/n#6"):
        cli._spawn_merge_pin(a, None, "it-1", "o/n", 6)


def test_a_merge_that_ended_without_merging_frees_the_lane(root):
    first = _rec(root)
    first.update(state=eph.DONE, ended_at=NOW, result={"verdict": "blocked", "cause": "report"})
    eph.write(root, first)
    assert eph.lane_refusal(root, "o/n", 10, NOW + 60) == ""        # no spacing behind it
    first["result"] = {"verdict": "merged", "cause": "report"}
    eph.write(root, first)
    assert "10m apart" in eph.lane_refusal(root, "o/n", 10, NOW + 60)


def test_an_unmerged_ending_releases_chaskis_lane_turn(root):
    rec = _rec(root, request_id=REQ_ID)
    calls = []

    def run(argv, **k):
        calls.append(argv)
        return _R()
    a = _args(root, "--list")
    assert cli._spawn_lane_release(a, dict(rec, result={"verdict": "blocked", "cause": "report"}),
                                   run=run) == ""
    assert cli._spawn_lane_release(a, dict(rec, result={"verdict": "failed", "cause": "stopped"}),
                                   run=run) == ""
    assert calls == [
        ["chaski-github-work", "--config", "/etc/chaski/r.yaml", "lane", "release",
         "--request", REQ_ID, "--outcome", "blocked"],
        ["chaski-github-work", "--config", "/etc/chaski/r.yaml", "lane", "release",
         "--request", REQ_ID, "--outcome", "stopped"]]
    # Never after a merge (chaski sees the merge fact), never without a request id.
    assert cli._spawn_lane_release(a, dict(rec, result={"verdict": "merged"}), run=1 / 1) == ""
    assert cli._spawn_lane_release(a, dict(rec, request_id=None,
                                           result={"verdict": "blocked"}), run=1 / 1) == ""
    failing = type("F", (), {"returncode": 1})()
    assert "NOT released" in cli._spawn_lane_release(
        a, dict(rec, result={"verdict": "blocked", "cause": "report"}), run=lambda *x, **k: failing)


# --- crew PRs record their author agent ----------------------------------------------

def test_st_repo_pr_records_authored_by_agent_for_chaski(q):
    policy = config.Ephemeral(verdict_graph=GRAPH)
    note = pr_preflight.record_authorship({"created": "u", "node_id": NODE}, actor="lex",
                                          quipu=q, policy=policy)
    assert "authoredByAgent lex" in note
    assert gv.author_agent(q, NODE, graph=GRAPH) == "lex"
    # chaski's author_query shape: ?pr aegis:authoredByAgent ?agent in a named graph.
    assert q.knots[-1][1] == GRAPH
    gv.write_authorship(quipu=q, graph=GRAPH, node_id=NODE, agent="other")
    assert gv.author_agent(q, NODE, graph=GRAPH) is None     # two authors: none (fail closed)


def test_authorship_is_off_by_default_and_needs_an_agent(q):
    assert pr_preflight.record_authorship({"created": "u", "node_id": NODE}, actor="lex",
                                          quipu=q, policy=config.Ephemeral()) == ""
    assert "no agent identity" in pr_preflight.record_authorship(
        {"created": "u", "node_id": NODE}, actor="", quipu=q,
        policy=config.Ephemeral(verdict_graph=GRAPH))
    assert q.knots == []


def test_config_reads_and_refuses_the_verdict_keys(tmp_path):
    (tmp_path / "shantytown.toml").write_text(
        f'[ephemeral]\nverdict_graph = "{GRAPH}"\nlane_release = ["c", "--config", "x"]\n')
    eph_cfg = config.load(tmp_path).ephemeral
    assert eph_cfg.verdict_graph == GRAPH and eph_cfg.lane_release == ("c", "--config", "x")
    (tmp_path / "shantytown.toml").write_text('[ephemeral]\nlane_release = "c lane"\n')
    with pytest.raises(config.ConfigError, match="lane_release"):
        config.load(tmp_path)
    (tmp_path / "shantytown.toml").write_text('[ephemeral]\nverdict_graph = "a b"\n')
    with pytest.raises(config.ConfigError, match="verdict_graph"):
        config.load(tmp_path)


# --- review #408: trust an agent cannot give itself ----------------------------------

def test_a_self_enrolled_signer_key_is_rejected_even_when_quipu_trusts_it(q):
    """The measured attack: the reviewer writes its own VerifierRegistration
    (one unsigned write), so quipu's /verdict/verify says trusted. The gate must
    still refuse: the key is not pinned by a human."""
    attacker = bytes(range(7, 39))
    q.register("eph-review-aaaaaa", attacker)            # self-enrolled in quipu
    gv.write(_record(), quipu=q, graph=GRAPH, seed=attacker, verifier="eph-review-aaaaaa")
    q.register("rogue-signer", attacker)
    gv.write(_record(recorded_at="2026-10-28T08:01:00Z"), quipu=q, graph=GRAPH, seed=attacker,
             verifier="rogue-signer")
    out = _approval(q)
    assert not out["approved"]
    assert all("not pinned" in i["why"] for i in out["ignored"])
    # With the attacker's verifier pinned, a signer id that IS an agent of the PR still never counts.
    out = _approval(q, signers={"eph-review-aaaaaa": gv.public_key(attacker).hex()})
    assert not out["approved"] and "agent of this PR" in out["ignored"][0]["why"]


def test_reusing_the_pinned_signer_name_with_a_self_enrolled_key_is_rejected():
    """Re-enroll the PINNED verifier id under the attacker's key in quipu: quipu
    trusts it, but the signature fails under the human-pinned key."""
    q = FakeQuipu()
    attacker = bytes(range(9, 41))
    q.register(SIGNER, attacker)
    gv.write(_record(), quipu=q, graph=GRAPH, seed=attacker, verifier=SIGNER)
    out = _approval(q)
    assert not out["approved"] and "pinned key" in out["ignored"][0]["why"]


def test_records_outside_the_configured_graph_are_never_read(q):
    gv.write(_record(), quipu=q, graph="urn:agent:scratch", seed=SEED, verifier=SIGNER)
    gv.write_authorship(quipu=q, graph="urn:agent:scratch", node_id=NODE, agent="mallory")
    assert not _approval(q)["approved"] and _approval(q)["ignored"] == []
    assert gv.author_agent(q, NODE, graph=GRAPH) is None
    assert _approval(q, graph="urn:agent:scratch")["approved"]       # only where configured
    with pytest.raises(gv.VerdictError, match="ONE configured graph"):
        _approval(q, graph="")


def test_the_pin_file_must_be_owned_by_root_and_not_writable_by_others(tmp_path):
    pin = tmp_path / "verdict-signers.json"
    pin.write_text(json.dumps({"version": 1, "signers": PINNED}))
    os.chmod(pin, 0o644)
    me = os.getuid()
    assert REAL_TRUSTED_SIGNERS(pin, owner=me) == PINNED
    assert REAL_TRUSTED_SIGNERS(pin, owner=me + 1) == {}         # not the owner the gate trusts
    os.chmod(pin, 0o666)
    assert REAL_TRUSTED_SIGNERS(pin, owner=me) == {}             # writable by others
    assert REAL_TRUSTED_SIGNERS(tmp_path / "absent.json", owner=me) == {}
    os.chmod(pin, 0o644)
    pin.write_text(json.dumps({"version": 1, "signers": {SIGNER: "not-hex"}}))
    assert REAL_TRUSTED_SIGNERS(pin, owner=me) == {}
