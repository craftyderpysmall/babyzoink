import json
from types import SimpleNamespace

import pytest

from tools.m5c.solver import Solver
from tools.site.backfill_attempts import row, timed_solver_rows


CBF_FLAGS = {"cbf": True, "click_between_steps": False, "click_on_steps": False}


def solver_for(reply, progress=None):
    return Solver(SimpleNamespace(request=lambda *args, **kwargs: reply), {},
                  progress=progress, log=lambda _: None)


@pytest.mark.parametrize(("flags", "expected"), [(None, "tick"), (CBF_FLAGS, "cbf")])
def test_solver_saves_effective_bridge_timing(tmp_path, flags, expected):
    path = tmp_path / "progress.json"
    reply = {"episode": 7}
    if flags is not None:
        reply["input_timing"] = flags
    solver = solver_for(reply, path)
    solver.reset_zero()
    solver.committed, solver.seg_x, solver.bad = [], [], set()
    solver.save_progress()
    assert json.loads(path.read_text())["input_timing"] == expected


@pytest.mark.parametrize(("saved", "flags"), [(None, CBF_FLAGS), ("cbf", None)])
def test_resume_rejects_both_timing_migrations(tmp_path, saved, flags):
    path = tmp_path / "progress.json"
    progress = {"committed": [], "seg_x": [], "bad": [], "evals": 0, "ticks": 0}
    if saved is not None:
        progress["input_timing"] = saved
    path.write_text(json.dumps(progress))
    reply = {"episode": 7}
    if flags is not None:
        reply["input_timing"] = flags
    solver = solver_for(reply, path)
    solver.load_progress()
    with pytest.raises(ValueError, match="solver input timing changed"):
        solver.reset_zero()


def test_new_bridge_refuses_inconsistent_timing():
    reply = {"episode": 7, "input_timing": CBF_FLAGS | {"click_on_steps": True}}
    with pytest.raises(RuntimeError, match="native click-timing"):
        solver_for(reply).reset_zero()


@pytest.mark.parametrize("matches", [True, False])
def test_opt_in_migration_validates_legacy_boundary_before_writing(tmp_path, monkeypatch, matches):
    monkeypatch.setenv("GDBOT_MIGRATE_TICK_PREFIX", "1")
    path = tmp_path / "progress.json"
    original = json.dumps({"committed": [[1, 1]], "seg_x": [4.0], "bad": [], "evals": 5, "ticks": 8})
    path.write_text(original)

    def request(op, **kwargs):
        if op == "checkpoint_pop":
            return {"count": 0}
        if op == "reset":
            return {"episode": 1, "input_timing": CBF_FLAGS}
        if op == "step_seq":
            return {"terminal": None, "xs": [2.0, 4.0 if matches else 3.0], "ticks_advanced": 8}
        return {}

    client = SimpleNamespace(request=request, load_level=lambda _: None)
    solver = Solver(client, {}, progress=path, budget=5, log=lambda _: None)
    if not matches:
        with pytest.raises(ValueError, match="migration diverged"):
            solver.solve()
        assert path.read_text() == original
        return
    assert solver.solve() is None
    result = json.loads(path.read_text())
    assert result["input_timing"] == "cbf"
    assert result["migrated_from"] == "tick"
    assert result["migrated_at_depth"] == 1
    assert result["tick_evaluations"] == 5


def test_fractional_search_follows_tick_candidates_and_verifies_identical_tape(monkeypatch):
    monkeypatch.setenv("GDBOT_SOLVER_V2", "1")
    calls = []

    def request(op, **kwargs):
        if op == "checkpoint_pop":
            return {"count": 0}
        if op == "reset":
            return {"episode": 1, "input_timing": CBF_FLAGS}
        if op == "step_seq":
            payload = kwargs["actions"], kwargs.get("fracs")
            calls.append(payload)
            complete = payload[0][0] == 1 and payload[1] and payload[1][0] == 0.25
            return {"terminal": "complete" if complete else "death", "decisions": 0,
                    "xs": [], "ticks_advanced": 1}
        return {}

    client = SimpleNamespace(request=request, load_level=lambda _: None)
    result = Solver(client, {}, seg=1, look=1, budget=10, log=lambda _: None).solve()
    assert result["verified"] and result["input_timing"] == "cbf"
    assert result["actions"] == [1] and result["fracs"] == [0.25]
    assert [fraction for _, fraction in calls[:2]] == [None, None]
    assert calls[-1] == ([1], [0.25])


def test_dashboard_keeps_historical_attempts_in_legacy_timing():
    outcome = row("search", "official:1", normal_attempts=3, practice_attempts=12,
                  normal_clears=1, first_clear_attempt=3)
    legacy, current = timed_solver_rows(outcome, {"input_timing": "cbf", "migrated_from": "tick",
                                                "tick_verification_attempts": 2, "tick_evaluations": 5})
    assert (legacy["input_timing"], legacy["normal_clears"], legacy["practice_attempts"]) == ("tick", 0, 5)
    assert (current["input_timing"], current["first_clear_attempt"], current["practice_attempts"]) == ("cbf", 1, 7)
