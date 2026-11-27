"""replay.py: the room election replayed over the election log with other tuning."""
import json

import sextant
from sextant import replay

SCALE = 100.0
LAYOUT = {"floor": [{"name": "F", "scale": SCALE, "receivers": [{"entity_id": "p1", "cords": {"x": 50, "y": 50}}], "zones": [
    {"entity_id": "A", "cords": [{"x": 0, "y": 0}, {"x": 300, "y": 0}, {"x": 300, "y": 300}, {"x": 0, "y": 300}]},
    {"entity_id": "B", "cords": [{"x": 300, "y": 0}, {"x": 600, "y": 0}, {"x": 600, "y": 300}, {"x": 300, "y": 300}]},
]}], "tuning": {"zone_switch_secs": 0, "zone_switch_margin": 0.05, "zone_prob_smoothing": 1.0,
                    "far_move_secs": 0, "far_move_margin": 0, "zone_lock_warmup_secs": 3600}}   # neither the far-move dwell nor the stationary lock


def _rows(t0=1000.0):
    """A thing well inside A, then hopping to B and back every 60 s."""
    rows = []
    for i in range(120):
        in_b = (i // 12) % 2 == 1
        rows.append({"t": t0 + 5 * i, "ent": "cat", "floor": "F", "cords": [450 if in_b else 150, 150],
                     "zone_raw": "B" if in_b else "A", "zone": "B" if in_b else "A", "anchor": None, "rms_m": 0.2, "speed": 0.0})
    return rows


def test_a_longer_dwell_replays_as_fewer_bounces_and_leaves_the_live_state_alone():
    sextant._zone_state.clear()
    out = replay.compare(sextant, LAYOUT, _rows(), {"zone_switch_secs": 120})
    assert out["rows"] == 120 and out["things"] == 1
    assert out["logged"]["bounces"] > 3
    # At the tuning as it is the replay follows the log (a few cycles behind: the log here is the instant room); a 120 s dwell rides the hops out.
    assert out["base"]["agree"] > 0.7 and out["base"]["bounces"] > 3
    assert out["trial"]["switches"] == 0 and out["trial"]["bounces"] == 0
    assert out["things_changed"]["cat"]["trial"] == {"switches": 0, "bounces": 0}
    assert sextant._zone_state == {}                       # ran on its own state
    assert replay.compare(sextant, LAYOUT, [], {}) == {"rows": 0}


def test_load_rows_keeps_the_window_and_skips_what_cannot_be_replayed(tmp_path):
    now = 1795000000.0
    name = sextant.election_log.file_for(now - 600)
    good = {"t": now - 600, "ent": "cat", "floor": "F", "cords": [1, 2], "zone_raw": "A", "zone": "A", "radii_n": 4}
    lines = [json.dumps(good), json.dumps({**good, "t": now - 7 * 3600}), json.dumps({**good, "cords": None}), '{"t": 17']
    (tmp_path / name).write_text("\n".join(lines) + "\n")
    (tmp_path / "notes.txt").write_text("not a log")
    rows = replay.load_rows(str(tmp_path), 6, now=now)
    assert [r["t"] for r in rows] == [now - 600] and "radii_n" not in rows[0]
    assert replay.load_rows(str(tmp_path / "missing"), 6, now=now) == []


def test_cross_floor_replay_measures_both_fixes():
    """tools/replay_cross_floor.py: the three measures, own beside cross."""
    import importlib.util
    import pathlib
    spec = importlib.util.spec_from_file_location("rcf", pathlib.Path(__file__).parent.parent / "tools" / "replay_cross_floor.py")
    rcf = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rcf)
    layout = {"floor": [{"name": "G", "scale": 100.0,
                         "zones": [{"entity_id": "Den", "poly": True, "cords": [{"x": 0, "y": 0}, {"x": 200, "y": 0}, {"x": 200, "y": 200}, {"x": 0, "y": 200}]}],
                         "receivers": [{"entity_id": "rx", "cords": {"x": 100, "y": 100}}]}]}

    def row(t, own, cross):
        return {"t": t, "ent": "cat", "floor": "G", "speed": 0.0, "zone": "Den", "anchor": "rx",
                "floor_cands": {"G": {"fix": [0, 0], "cross": {"fix": cross, "own": own}}}}
    rows = [row(0, [300, 100], [100, 100]), row(10, [100, 100], [100, 100]), {"t": 20, "ent": "cat", "floor": "G", "floor_cands": {"G": {"fix": [1, 1]}}},
            row(30, [900, 900], [900, 900])]             # after a dropped cycle: not a still step
    rows.append({**row(5, [0, 0], [0, 0]), "ent": "dog"})
    by_thing = rcf.pairs(rows, rcf.floors_of(layout))
    assert rcf.measure(by_thing["dog"] + by_thing["cat"][:1])["still"][2] == 0   # never a step from one thing to another
    s = rcf.measure(by_thing["cat"][:2])
    assert len(by_thing["cat"]) == 3 and s["like"] == 2  # the row without a cross fix is left out
    assert s["still"] == (2.0, 0.0, 1)                   # own jumped 2 m between still cycles, cross none
    assert s["room"] == (0.5, 1.0, 2)                    # own was outside the Den once
    assert s["anchor"] == (1.0, 0.0, 2)                  # median distance to the proxy it sat on


def test_receiver_report_ranks_the_receiver_that_reads_long(tmp_path):
    """tools/receiver_report.py: bias and spread per receiver, from a gzipped hour as well as a plain one."""
    import gzip
    import importlib.util
    import json
    import pathlib
    spec = importlib.util.spec_from_file_location("rr", pathlib.Path(__file__).parent.parent / "tools" / "receiver_report.py")
    rr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rr)
    layout = {"floor": [{"name": "G", "scale": 100.0, "receivers": [
        {"entity_id": "good", "height": 1.0, "cords": {"x": 300, "y": 0}},
        {"entity_id": "long", "height": 1.0, "cords": {"x": 0, "y": 400}},
        {"entity_id": "unheard", "cords": {"x": 9, "y": 9}}]}]}

    def row(t):
        return {"t": t, "ent": "cat", "floor": "G", "floor_cands": {"G": {"fix": [0, 0], "heard": [["good", 3.0], ["long", 5.5], ["elsewhere", 1.0]]}}}
    (tmp_path / "2026-11-20T01Z.jsonl.gz").write_bytes(gzip.compress((json.dumps(row(1)) + "\n").encode()))
    (tmp_path / "2026-11-20T02Z.jsonl").write_text(json.dumps(row(2)) + "\n")
    (tmp_path / "2026-11-20T03Z.jsonl.gz.tmp").write_bytes(b"half a gzip")
    rows = rr.load_rows(str(tmp_path))
    assert [r["t"] for r in rows] == [1, 2]
    assert rr.report(rows, layout) == [("G", "long", 2, 1.5, 1.5), ("G", "good", 2, 0.0, 0.0)]
    # Heights as the live solve: a robot runs at 0.1 m, so a receiver 4 m above it reads 5 m at 3 m along.
    robot = {**layout, "thing_classes": {"cat": "robot"}}
    robot["floor"] = [{**layout["floor"][0], "receivers": [{"entity_id": "good", "height": 4.1, "cords": {"x": 300, "y": 0}}]}]
    assert rr.report([{**row(1), "floor_cands": {"G": {"fix": [0, 0], "heard": [["good", 5.0]]}}}], robot) == [("G", "good", 1, 0.0, 0.0)]
    assert rr.thing_height({"thing_heights": {"cat": 0}, "thing_height": 2}, "cat") == 0.0 and rr.thing_height({"thing_height": 2}, "cat") == 2.0
