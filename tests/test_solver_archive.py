from tools.m5c.archive import Archive, cell_key


def state(tick, held=False, upper_y=30, world="same"):
    return {"t": tick, "held": held,
            "p1": [tick, 0, 0, 1, "cube", 0, 0],
            "p2": [tick, upper_y, 0, 1, "cube", 1, 0],
            "world": world, "items": "empty"}


class DualFixture:
    seg = 2
    look = 4
    level = {"kind": "synthetic-dual"}
    budget = 30
    archive_guard = None

    def __init__(self, progress):
        self.progress = progress
        self.evals = self.ticks = 0

    def reset_zero(self):
        self.actions = []
        return {"state": {"world_hash": "same"}}

    def run(self, actions, *, xs=False, cells=False):
        trace = []
        terminal = None
        for action in actions:
            self.actions.append(action)
            self.ticks += 4
            n = len(self.actions)
            if n == 14 and self.actions[8:11] in ([0, 0, 0], [1, 1, 1]):
                terminal = "death"
                break
            if n == 22:
                terminal = "complete"
                break
            trace.append(state(n * 4, bool(action), upper_y=30 + sum(self.actions)))
        return {"cells": trace if cells else [], "decisions": len(trace), "terminal": terminal}

    def _random_tail(self, rng, size):
        return [index % 2 for index in range(size)]


def test_archive_replays_and_finds_a_divergent_dual_branch(tmp_path):
    fixture = DualFixture(tmp_path / "progress.json")
    archive = Archive(fixture, [0] * 10)
    tape, boundary = archive.explore()
    assert fixture.evals <= fixture.budget
    assert archive.replay_ticks > 0
    fixture.reset_zero()
    verified = archive.run(tape, cells=True)
    if boundary is None:
        assert verified["terminal"] == "complete"
    else:
        assert verified["terminal"] is None
        assert verified["cells"][-1] == boundary
    assert tape[8:11] not in ([0, 0, 0], [1, 1, 1])
    resumed = Archive(DualFixture(fixture.progress), [0] * 10)
    assert resumed.trials == archive.trials
    assert resumed.replay_ticks == archive.replay_ticks
    assert resumed.solver.evals == fixture.evals


def test_cell_key_distinguishes_upper_player_and_world_but_ignores_elapsed_time():
    cell = state(4)
    assert cell_key(cell) == cell_key(cell | {"t": 100})
    assert cell_key(cell) != cell_key(state(4, upper_y=65))
    assert cell_key(cell) != cell_key(state(4, world="changed"))
