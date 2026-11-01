"""aegis-hnv7: a plan without a five_hour window is not a lost signal.

Anthropic removed the 5-hour window for Max plans. The producer now states that
absence explicitly (`claude_usage_window_offered{window="five_hour"} 0` from a
successful probe). A policy that lists the window in `optional_windows` treats
that statement as NOT APPLICABLE: no "USAGE SIGNAL PARTIALLY LOST" alarm, and
seven_day still governs. Everything else keeps its old meaning, and each case is
asserted against a control that differs in exactly one input:

- optional + server says not offered + fresh probe   -> not applicable, no alarm
- same, but the window is NOT optional in the policy  -> blind, alarm (as before)
- same, but the marker is absent (series just missing) -> blind, alarm
- same, but the probe failed / is stale / in the future -> blind, alarm
- one account still offers it                          -> governed / blind, never skipped
- seven_day (required) missing while five_hour n/a     -> full SIGNAL LOST
- every window optional and none offered               -> full SIGNAL LOST
- a real five_hour value when the server returns one   -> governed (tier engages)
- genuine seven_day exhaustion with five_hour n/a      -> the drain tier still engages
- config typos (string, unknown window, duplicates)    -> refused at parse
"""
import pytest

from shantytown import config, governor as gov
from shantytown import fleet_governor as fleet

NOW = 1_000_000.0

POLICY = """
[governor]
source = "textfile"
path = "{path}"
max_age_seconds = 900
{optional}

[[governor.tier]]
window = "five_hour"
at = 70
min_priority = 0

[[governor.tier]]
window = "seven_day"
at = 80
min_priority = 0

[[governor.tier]]
window = "seven_day"
at = 95
action = "drain"
"""

OPTIONAL = 'optional_windows = ["five_hour"]'


def prom(*, seven=54, five=None, offered="0", ok=1, at=NOW, status=200, accounts=("acct-a",),
         seven_offered="1"):
    lines = []
    for a in accounts:
        if seven is not None:
            lines.append(f'claude_usage_utilization_pct{{account="{a}",window="seven_day"}} {seven}')
        if five is not None:
            lines.append(f'claude_usage_utilization_pct{{account="{a}",window="five_hour"}} {five}')
        if offered is not None:
            value = offered if isinstance(offered, str) else offered[a]
            lines.append(f'claude_usage_window_offered{{account="{a}",window="five_hour"}} {value}')
        if seven_offered is not None:
            lines.append(f'claude_usage_window_offered{{account="{a}",window="seven_day"}} {seven_offered}')
        if ok is not None:
            lines.append(f'claude_usage_probe_success{{account="{a}"}} {ok}')
        lines.append(f'claude_usage_probe_http_status{{account="{a}"}} {status}')
        if at is not None:
            lines.append(f'claude_usage_probe_timestamp_seconds{{account="{a}"}} {at:.0f}')
        lines.append(f'claude_usage_cache_age_seconds{{account="{a}"}} 0')
    return "\n".join(lines) + "\n"


def verdict(tmp_path, body, *, optional=OPTIONAL, now=NOW):
    path = tmp_path / "claude_usage.prom"
    path.write_text(body)
    (tmp_path / "shantytown.toml").write_text(POLICY.format(path=path, optional=optional))
    policy = config.load(tmp_path).governor
    g = gov.Governor(policy, gov.reader_for(policy), None, now=lambda: now)
    return policy, g.evaluate(persist=False)


def test_optional_window_the_server_does_not_offer_is_not_a_lost_signal(tmp_path):
    _, v = verdict(tmp_path, prom())
    assert not v.signal_lost and v.alarm == ""
    assert v.tier is None                      # seven_day 54% engages nothing
    assert v.by_window == {"seven_day": 54.0}
    assert "not offered by this plan: five_hour" in v.why


def test_control_not_optional_keeps_the_partial_loss_alarm(tmp_path):
    _, v = verdict(tmp_path, prom(), optional="")
    assert "USAGE SIGNAL PARTIALLY LOST" in v.alarm and "five_hour" in v.alarm
    assert not v.signal_lost


def test_control_missing_marker_is_still_blind(tmp_path):
    """A series that is merely missing proves nothing about the plan."""
    _, v = verdict(tmp_path, prom(offered=None))
    assert "USAGE SIGNAL PARTIALLY LOST" in v.alarm and "five_hour" in v.alarm


@pytest.mark.parametrize("probe", [
    dict(ok=0, status=500),          # the probe said it failed
    dict(ok=None),                   # no success flag at all
    dict(at=NOW - 5000),             # stale beyond max_age_seconds
    dict(at=NOW + 5000),             # timestamp in the future
    dict(at=None),                   # unaged
])
def test_control_an_unusable_probe_never_vouches_for_absence(tmp_path, probe):
    _, v = verdict(tmp_path, prom(seven=None, seven_offered=None, **probe))
    # Nothing readable at all: the old full signal-lost path, never "not applicable".
    assert v.signal_lost
    assert "not offered" not in v.why


def test_control_a_stale_probe_does_not_skip_five_hour_even_with_seven_day_readable(tmp_path):
    """Same staleness, but seven_day carries a value: five_hour must be blind
    (and seven_day is lost too, because the shared probe is stale)."""
    _, v = verdict(tmp_path, prom(at=NOW - 5000))
    assert v.signal_lost and "not offered" not in v.why


def test_control_one_account_still_offering_it_is_never_skipped(tmp_path):
    _, v = verdict(tmp_path, prom(offered={"acct-a": "0", "acct-b": "1"},
                                  accounts=("acct-a", "acct-b")))
    assert "USAGE SIGNAL PARTIALLY LOST" in v.alarm and "five_hour" in v.alarm
    assert "not offered" not in v.why


def test_control_required_seven_day_missing_is_a_full_signal_loss(tmp_path):
    _, v = verdict(tmp_path, prom(seven=None, seven_offered="0"))
    assert v.signal_lost, v
    assert "not offered by this plan" not in v.why


def test_control_every_window_optional_and_none_offered_is_a_full_signal_loss(tmp_path):
    _, v = verdict(tmp_path, prom(seven=None, seven_offered="0"),
                   optional='optional_windows = ["five_hour", "seven_day"]')
    assert v.signal_lost


def test_a_real_five_hour_value_is_still_governed(tmp_path):
    """If the server ever returns the window again, it governs as before."""
    _, v = verdict(tmp_path, prom(five=75, offered="1"))
    assert v.tier is not None and v.tier.window == "five_hour" and v.tier.at == 70
    assert v.alarm == "" and "not offered" not in v.why


def test_a_value_wins_over_a_contradictory_marker(tmp_path):
    _, v = verdict(tmp_path, prom(five=75, offered="0"))
    assert v.tier is not None and v.tier.window == "five_hour"


def test_genuine_seven_day_exhaustion_still_drains(tmp_path):
    _, v = verdict(tmp_path, prom(seven=97))
    assert v.tier is not None and v.tier.window == "seven_day" and v.tier.drains
    assert v.alarm == ""


@pytest.mark.parametrize("optional, message", [
    ('optional_windows = "five_hour"', "ARRAY"),
    ('optional_windows = ["five_huor"]', r"names 'five_huor', which has no"),
    ('optional_windows = ["five_hour", "five_hour"]', "twice"),
    ('optional_windows = [""]', "ARRAY"),
])
def test_config_typos_are_refused(tmp_path, optional, message):
    (tmp_path / "shantytown.toml").write_text(POLICY.format(path=tmp_path / "x", optional=optional))
    with pytest.raises(Exception, match=message):
        config.load(tmp_path)


def test_wire_is_unchanged_unless_used(tmp_path):
    """An older peer's strict checks must keep accepting today's wire."""
    plain, _ = verdict(tmp_path, prom(), optional="")
    assert "optional_windows" not in fleet.policy_wire(plain)
    used, _ = verdict(tmp_path, prom())
    assert fleet.policy_wire(used)["optional_windows"] == ["five_hour"]
    ordinary = gov.Reading(pct=10.0, at=NOW, source="textfile")
    absent = gov.Reading(pct=None, at=NOW, source="textfile", offered=False)

    class R:
        def read_all_detailed(self):
            return {"seven_day": ordinary, "five_hour": absent}, "", ""

    class G:
        reader = R()
        policy = used

    wire = fleet.observations(G())
    assert "offered" not in wire["seven_day"]
    assert wire["five_hour"]["offered"] is False
