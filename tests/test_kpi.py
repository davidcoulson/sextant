"""The panel's stability KPI (custom_components/sextant/kpi.py).

The metric code is duplicated from tools/flap_kpi.py on purpose (see the
module docstring); tests/test_flap_kpi.py covers that copy, this covers the
integration's. The restart case is the one that matters: a day with three
restarts used to read as a fleet-wide flap.
"""
from datetime import datetime, timedelta, timezone

from sextant import kpi

T0 = datetime(2026, 9, 24, 10, 0, tzinfo=timezone.utc)


def _rows(*items):
    return [{"state": s, "last_changed": (T0 + timedelta(seconds=sec)).isoformat()} for sec, s in items]


def test_a_restart_is_not_a_change():
    """Kitchen, unavailable, unknown, Kitchen: the sensor went away and came
    back where it was. Zero changes, and the dead rows counted separately."""
    m = kpi.compute_metrics(_rows((0, "Kitchen"), (100, "unavailable"), (101, "unknown"), (102, "Kitchen")), window_hours=1)
    assert m["changes"] == 0
    assert m["flips"] == 0
    assert m["dead"] == 2
    assert m["states"] == 1
    assert m["top_pairs"] == []


def test_a_move_across_a_restart_is_one_change():
    m = kpi.compute_metrics(_rows((0, "Kitchen"), (100, "unavailable"), (102, "Office")), window_hours=1)
    assert m["changes"] == 1
    assert m["dead"] == 1
    assert m["top_pairs"] == [{"pair": ["Kitchen", "Office"], "count": 1}]


def test_three_restarts_on_a_stationary_thing_score_zero():
    """What today looked like: three restarts, the wallet never moved. It used
    to read as 6 changes with a median dwell of a few seconds."""
    rows = [(0, "Kitchen")]
    for t in (3600, 7200, 10800):
        rows += [(t, "unavailable"), (t + 20, "unknown"), (t + 21, "Kitchen")]
    m = kpi.compute_metrics(_rows(*rows), window_hours=4)
    assert m["changes"] == 0
    assert m["changes_per_hour"] == 0
    assert m["dead"] == 6
    assert m["median_dwell_s"] is None


def test_a_flip_around_a_restart_still_counts():
    """Kitchen, Office, restart, Kitchen: the flip is real, the restart is not."""
    m = kpi.compute_metrics(_rows((0, "Kitchen"), (30, "Office"), (60, "unavailable"), (70, "Kitchen")), window_hours=1)
    assert m["changes"] == 2
    assert m["flips"] == 1
    assert m["dead"] == 1
    # The dwell in Office runs to when Kitchen came back, not to the restart.
    assert m["median_dwell_s"] == 35.0


def test_a_window_that_opens_dead_starts_at_the_first_live_state():
    m = kpi.compute_metrics(_rows((0, "unavailable"), (5, "Kitchen"), (65, "Office")), window_hours=1)
    assert m["changes"] == 1
    assert m["dead"] == 1


def test_summary_rolls_up_the_live_changes_only():
    per = {
        "sensor.a_sextant_room": kpi.compute_metrics(_rows((0, "Kitchen"), (100, "unavailable"), (102, "Kitchen")), window_hours=1),
        "sensor.b_sextant_room": kpi.compute_metrics(_rows((0, "Kitchen"), (100, "Office")), window_hours=1),
    }
    s = kpi.summarise(per)["sextant_room"]
    assert s["changes"] == 1
    assert s["changes_per_thing_hour"] == 0.5
