"""A gate stated only in prose, stored as a date, is reported once it is met (aegis-152).

The specimen is aegis-tnr: its notes said "Resume as soon as qbl closes; the date is
a backstop", its field said `date:2026-10-16`, and it sat parked 9h after qbl
closed. The r09 backstop (PR #239) follows only a structured `closed:` marker, so it
could not see this. Measured on the live board 2026-10-14: aegis-d82, aegis-hz1 and
aegis-wke6r4g8v were in the same state for 1-3 days.

Report-only: prose never becomes a releasable condition.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from shantytown import deferrals


NOW = datetime(2026, 10, 14, 19, 0, tzinfo=timezone.utc)
FUTURE = (NOW + timedelta(days=2)).isoformat().replace("+00:00", "Z")
TNR = ("Preempted by lead tim for P1 aegis-qbl. Resume as soon as qbl closes; the "
       "date is a backstop.\nresume_when: date:" + FUTURE)


def _row(bead="aegis-tnr", notes=TNR, status="deferred", defer_until=FUTURE):
    return {"id": bead, "title": "public installs", "status": status,
            "assignee": "ellie", "priority": 1, "notes": notes, "defer_until": defer_until}


def _closed(*ids):
    return lambda bead: True if bead in ids else (None if bead == "aegis-gone" else False)


def test_the_tnr_specimen_is_reported_with_the_item_it_waited_on():
    [finding] = deferrals.evaluate([_row()], NOW, is_closed=_closed("aegis-qbl"))
    assert finding.prose_gate == "aegis-qbl"
    assert not finding.met and not finding.lapsed_at
    assert "PROSE GATE MET [aegis-qbl is closed]" in finding.render()


def test_live_phrasings_resolve_to_their_targets():
    assert deferrals.prose_gate_targets("Resume when aegis-amt closed; no GO inferred") == ["aegis-amt"]
    assert deferrals.prose_gate_targets("resume earlier when aegis-q5a closes") == ["aegis-q5a"]
    assert deferrals.prose_gate_targets(
        "Resume when dse has landed and closed with merged blob verification") == ["aegis-dse"]
    assert deferrals.prose_gate_targets("unrelated: aegis-xyz closed yesterday") == []


def test_an_open_target_is_silent():
    assert deferrals.evaluate([_row()], NOW, is_closed=_closed()) == []


def test_an_unknown_target_is_silent_not_untestable():
    # "qbl" might not be an item at all; an unknown answer must not cry wolf.
    notes = "Resume when gone closes.\nresume_when: date:" + FUTURE
    assert deferrals.evaluate([_row(notes=notes)], NOW, is_closed=_closed()) == []


def test_a_raising_lookup_is_silent_and_never_crashes_the_sweep():
    def boom(_):
        raise RuntimeError("store down")
    assert deferrals.evaluate([_row()], NOW, is_closed=boom) == []


def test_no_lookup_at_all_reports_nothing():
    assert deferrals.evaluate([_row()], NOW) == []


def test_a_structured_closed_marker_keeps_its_own_path():
    notes = "Resume when aegis-qbl closes.\nresume_when: closed:aegis-other"
    [finding] = deferrals.evaluate([_row(notes=notes)], NOW,
                                   is_closed=_closed("aegis-qbl", "aegis-other"))
    assert finding.met and not finding.prose_gate


def test_a_prose_finding_can_never_release_the_item():
    row = _row()
    [finding] = deferrals.evaluate([row], NOW, is_closed=_closed("aegis-qbl"))
    assert deferrals.can_release(row, finding, NOW) is False
    lapsed = _row(defer_until=None, notes="Resume when qbl closes.")
    found = deferrals.evaluate([lapsed], NOW, is_closed=_closed("aegis-qbl"))
    assert all(deferrals.can_release(lapsed, f, NOW) is False for f in found)


def test_the_state_key_changes_when_the_prose_gate_is_met(tmp_path):
    seen = deferrals.Reported(tmp_path)
    [met] = deferrals.evaluate([_row()], NOW, is_closed=_closed("aegis-qbl"))
    assert seen.unreported([met]) == [met]
    seen.record([met])
    assert seen.unreported([met]) == []


def test_existing_findings_keep_their_keys_so_install_does_not_re_alert():
    # Pinned to origin/main's Finding.key() before this change (aegis-152 review C1):
    # appending the new field to every key would re-alert the whole backlog once.
    lapsed = deferrals.Finding(bead="aegis-x", title="t", assignee="a", priority=1,
                               lapsed_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
                               lapsed_days=3)
    waiting = deferrals.Finding(bead="aegis-y", priority=2,
                                condition=deferrals.Condition("date", "2026-10-20T13:00:00Z"))
    assert lapsed.key() == "485e6508d2a8e07f"
    assert waiting.key() == "69fa1a1bafe99e20"
    # ...while a prose finding is a different state, so it does get its own key.
    prose = deferrals.Finding(bead="aegis-y", priority=2,
                              condition=deferrals.Condition("date", "2026-10-20T13:00:00Z"),
                              prose_gate="aegis-qbl")
    assert prose.key() != waiting.key()
