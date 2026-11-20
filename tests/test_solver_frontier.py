import json
from types import SimpleNamespace

from tools.m5c.solver import Solver


class DeterministicSolver(Solver):
    def __init__(self, progress, budget, calls, *, reverse=False):
        super().__init__(SimpleNamespace(load_level=lambda level: None), {},
                         seg=2, look=2, progress=progress, budget=budget, log=lambda _: None)
        self.calls = calls
        self.reverse = reverse

    def choices(self, previous):
        patterns = [[0, 0], [1, 1], [0, 1]]
        return iter(reversed(patterns) if self.reverse else patterns)

    def rebuild(self, target, **kwargs):
        return target

    def restore(self):
        pass

    def run(self, actions, xs=False):
        self.calls.append(actions)
        self.ticks += 4
        return {"terminal": "death", "decisions": 0 if actions[:2] == [0, 0] else 2}


def test_resume_does_not_repeat_rejections_or_partial_followups(tmp_path, monkeypatch):
    monkeypatch.setenv("GDBOT_SOLVER_V2", "1")
    uninterrupted_calls = []
    DeterministicSolver(None, 40, uninterrupted_calls).solve()

    path = tmp_path / "progress.json"
    resumed_calls = []
    DeterministicSolver(path, 3, resumed_calls).solve()
    saved = json.loads(path.read_text())
    assert saved["rejected"] == [[[0, 0]]]
    assert saved["partial"] == {"candidate": [1, 1], "next": 2, "best": 2}

    restarted = DeterministicSolver(path, 40, resumed_calls, reverse=True)
    restarted.solve()
    assert resumed_calls == uninterrupted_calls
    assert restarted.evals == len(uninterrupted_calls)


def test_legacy_progress_migrates_on_opt_in(tmp_path, monkeypatch):
    path = tmp_path / "progress.json"
    monkeypatch.delenv("GDBOT_SOLVER_V2", raising=False)
    DeterministicSolver(path, 3, []).solve()
    assert "frontier_version" not in json.loads(path.read_text())
    monkeypatch.setenv("GDBOT_SOLVER_V2", "1")
    solver = DeterministicSolver(path, 4, [])
    solver.solve()
    assert solver.evals == 4
    assert json.loads(path.read_text())["frontier_version"] == 1
