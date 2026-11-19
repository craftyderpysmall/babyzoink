"""#33: the M6 memory check must also run while a search is stalled (no "  x=" progress lines)."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for sub in ("tools/m6", "tools/m7", "tools/m5c", "tools/m5b", "tools/m5", "tools/m4", "tools/m3"):
    sys.path.insert(0, str(ROOT / sub))

solve_pool = pytest.importorskip("solve_pool")


class StalledSolver:
    """Evaluates forever at one point, like Dark Paradise's stall: never logs progress."""

    def __init__(self):
        self.evals = 0
        self.saved = 0

    def evaluate(self, cand):
        self.evals += 1
        return False, False, 0

    def save_progress(self):
        self.saved += 1


def test_stalled_search_still_hits_the_memory_check():
    now = [0.0]
    solver = StalledSolver()

    def check(s):
        s.save_progress()
        raise solve_pool.MemoryCap("over cap")

    solve_pool.guard_evaluations(solver, check, every_s=15.0, clock=lambda: now[0])
    with pytest.raises(solve_pool.MemoryCap):
        for _ in range(10_000):  # x never advances; each evaluation takes 0.5 s of game time
            now[0] += 0.5
            solver.evaluate([0] * 8)
    assert solver.saved == 1
    assert solver.evals == 29  # the first check fires once 15 s have passed, before evaluation 30


def test_guard_is_throttled():
    now = [0.0]
    calls = []
    solver = StalledSolver()
    solve_pool.guard_evaluations(solver, lambda s: calls.append(s.evals), every_s=15.0, clock=lambda: now[0])
    for _ in range(100):
        now[0] += 1.0
        solver.evaluate([0])
    assert len(calls) == 6  # once per 15 s over 100 s
