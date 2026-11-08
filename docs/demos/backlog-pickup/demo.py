"""Local library demonstration; graph, SDK and admission are isolated fixtures."""
from datetime import datetime, timezone

from shantytown.backlog_rank import next_after_anchor


def main():
    low = dict(id="owned-p2", revision=2, priority=2, status="open", assignee="worker")
    high = dict(id="ready-p1", revision=5, priority=1, status="open", assignee=None)
    items = {row["id"]: row for row in (low, high)}
    claims = []

    def reader(root, name, params, **bounds):
        return [dict(row, sampled_at=params["now"]) for row in (high, low)]

    def claim(row, owner):
        claims.append((row["id"], row["revision"], owner))
        return True

    args = dict(owner="worker", board="urn:fixture:board", read_current=items.__getitem__,
                claim=claim, admit=lambda rows: rows, reader=reader,
                now=datetime(2026, 11, 8, tzinfo=timezone.utc))
    print("Target: local library; graph order, native claim and admission are fixtures.")
    print("Input: completed anchor; owned P2 queue plus unowned ready P1.")
    print("Before (existing own-queue selection):", low["id"])
    selected, claimed = next_after_anchor(None, [low, high], [low], **args)
    assert selected == high and claimed
    assert claims == [("ready-p1", 5, "worker")]
    assert low["assignee"] == "worker" and low["status"] == "open"
    print("After (graph-ranked pickup):", selected["id"])
    print("Claim: ready-p1, observed revision 5; original owned-p2 retained.")

    def refused(*args, **kwargs):
        raise PermissionError("fixture query refused")

    claims.clear()
    try:
        next_after_anchor(None, [low, high], [low], **dict(args, reader=refused))
    except PermissionError:
        assert claims == []
        print("Negative control: refused query -> zero claims; no fallback authority.")
    else:
        raise AssertionError("query refusal must stop pickup")


if __name__ == "__main__":
    main()
