"""tools/replay_floors.py replays the floor habit prior: the logged factor out, the table's in."""
import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location("replay_floors", Path(__file__).resolve().parents[1] / "tools" / "replay_floors.py")
rf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rf)


def test_with_habit_divides_out_the_logged_factor_and_applies_the_table(tmp_path):
    t = 1795766400.0
    (tmp_path / "h.json").write_text('{"version": 1, "data": {}}')
    mod, _ = rf.load_habits(str(tmp_path / "h.json"))
    table = {"meg": {mod.slot_of(t): {"at": t, "z": {"Second|Bed": 3600.0}}}}
    cands = {"Second": {"score": 0.5, "habit": 0.5}, "Ground": {"score": 0.4}}
    plain = rf.with_habit({"Second": 0.5, "Ground": 0.4}, cands, "meg", t, None)
    assert plain == {"Second": 1.0, "Ground": 0.4}
    prior = rf.with_habit({"Second": 0.5, "Ground": 0.4}, cands, "meg", t, (mod, table, 1.0, None))
    assert prior["Second"] == 1.0 and abs(prior["Ground"] - 0.4 * mod.FLOOR_FLOOR_SHARE) < 1e-9
