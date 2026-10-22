"""Small local observation for review routing; never the full crew census.

Identity comes from the configured registry. Availability is the existing pane,
hold and session-budget judgement. This is advisory, never dispatch authority.
Only a bounded set of pane-idle owners has its active plate checked. No capacity
census, peer fanout, tree scan or priority advice is read.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import hashlib
import shutil
import urllib.error
import urllib.request


class ReadBudgetExceeded(RuntimeError):
    pass


@contextmanager
def read_budget(limit=6):
    """Bound this single-threaded observation's actual Python HTTP reads.

    Remote reads use Python transports only. The configured store is proven by
    the existing local `sd where` metadata command, never an SDK data reader.
    A transport change must retain this property; unknown or write endpoints
    are refused before sending.
    """
    original = urllib.request.urlopen
    from . import seeds_plate
    plate_original = seeds_plate.urlopen
    usage = {"reads": 0, "timeouts": 0}

    def bounded(request, *args, **kwargs):
        if not isinstance(request, urllib.request.Request):
            raise ReadBudgetExceeded("unclassified routing transport")
        from urllib.parse import urlsplit
        path = urlsplit(request.full_url).path
        try:
            payload = json.loads(request.data or b"{}")
        except (ValueError, TypeError):
            raise ReadBudgetExceeded("unclassified routing body") from None
        query = payload.get("query", "").lstrip()
        # The registry's queries carry PREFIX declarations. No mutation keyword
        # is admitted: this profile only uses its known SELECT/ASK reader.
        import re
        query = re.sub(r"(?is)^\s*(?:PREFIX\s+\S+\s*<[^>]+>\s*)+", "", query)
        if path != "/query" or not query.upper().startswith(("SELECT ", "ASK ", "ASK{")):
            raise ReadBudgetExceeded("non-read routing request")
        if usage["reads"] >= limit:
            raise ReadBudgetExceeded("routing read budget reached")
        usage["reads"] += 1
        try:
            return original(request, *args, **kwargs)
        except urllib.error.HTTPError as error:
            if error.code == 408:
                usage["timeouts"] += 1
            raise

    urllib.request.urlopen = bounded
    seeds_plate.urlopen = bounded
    try:
        yield usage
    finally:
        urllib.request.urlopen = original
        seeds_plate.urlopen = plate_original


def observe(cards, states, harness_for):
    """Public routing fields only; unknown is never an idle reviewer."""
    if len(cards) > 64:
        raise ReadBudgetExceeded("routing roster exceeds 64 cards")
    result = {card.name: {"name": card.name, "harness": harness_for(card),
                         "state": "unknown", "work": "unknown"}
              for card in cards}
    for card, state, work, posture in states:
        row = result[card.name]
        row.update(state=state, work=work)
        row["available"] = (row["harness"] == "codex" and state == "up"
                            and work == "idle" and posture == "BYPASS")
    return list(result.values())


def check_assignments(rows, read_rows, *, turn):
    """Check at most eight idle owners; rotate fairly between natural ticks.

    Pending work wins over an idle-looking pane. Unknown owner projections fail
    the entire observation; there is no SDK/full-board fallback.
    """
    candidates = sorted(row["name"] for row in rows if row.get("available"))
    selected = []
    if candidates:
        offset = (turn * 8) % len(candidates)
        selected = (candidates[offset:] + candidates[:offset])[:8]
    for row in rows:
        row["available"] = False
        row["assignment_checked"] = False
    if not selected:
        return
    items = read_rows(tuple(selected))
    occupied = set()
    for item in items:
        owner = item.get("assignee", "").split("/")[-1]
        if owner not in selected:
            raise ValueError("foreign owner in routing projection")
        if item.get("status") in ("hooked", "in_progress"):
            occupied.add(owner)
    for row in rows:
        if row["name"] in selected:
            row["assignment_checked"] = True
            row["available"] = row["name"] not in occupied


def command(a):
    from pathlib import Path
    from . import cli, cycle, deployment, harness, seeds_plate
    from .sd import SdTracker
    if not a.local or not a.json or any(getattr(a, name, False) for name in
                                       ("trees", "pane_state", "count", "governor")):
        print("review routing requires --local --json without census options")
        return 2
    usage = {"reads": 0, "timeouts": 0}
    try:
        with read_budget() as usage:
            cards = cli._registry(a).all().exact()
            host = deployment.local_host(a.root)
            cards = [card for card in cards if card.host in (None, host)]
            panes = cli._panes(a)
            runtime = cli._runtime(a, panes)
            states = cli._crew_states(
                cards, panes, runtime, cycling=cycle.Requests(a.root).pending(),
                untracked_root=Path(a.root), budget_root=Path(a.root))
            # A configured harness is not proof of the process currently in the
            # pane. Unknown command lines must never become Codex candidates.
            def running_harness(card):
                try:
                    return harness.running_name(panes.cmdline(card.pane))
                except Exception:
                    return None
            rows = observe(cards, states, running_harness)
            tracker = cli._tracker(a)
            if not isinstance(tracker, SdTracker):
                raise ValueError("routing requires the configured Seeds reader")
            proof = tracker.prove_store()
            if not proof.quipu_url or not proof.graph:
                raise ValueError("routing requires a proven remote graph")
            sdk_path = shutil.which(tracker._bin)
            if sdk_path is None:
                raise ValueError("configured Seeds executable unavailable")
            sdk_digest = hashlib.sha256(Path(sdk_path).read_bytes()).hexdigest()
            if any(row.get("available") for row in rows):
                check_assignments(
                    rows, lambda owners: seeds_plate.owner_rows(
                        proof, None, plate_owners=owners, timeout=15).exact(),
                    turn=int(datetime.now(timezone.utc).timestamp()) // 900)
        answer = dict(version=1, scope="review-routing", complete=True,
                      observed_at=datetime.now(timezone.utc).isoformat(), agents=rows,
                      capabilities=["inbox-retain-pointer-v1"],
                      delivery_sdk_sha256=sdk_digest,
                      quipu_reads=usage["reads"], quipu_408s=usage["timeouts"])
        print(json.dumps(answer))
        return 0
    except Exception as error:
        print(json.dumps(dict(version=1, scope="review-routing", complete=False,
                              quipu_reads=usage["reads"], quipu_408s=usage["timeouts"],
                              error=type(error).__name__)))
        return 2
