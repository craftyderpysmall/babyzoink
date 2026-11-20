"""Bounded exploration of distinct gameplay states from a stalled DFS path."""
from dataclasses import asdict, dataclass
import hashlib
import json
import random


def cell_key(cell):
    def player(values):
        if values is None:
            return None
        x, y, vy, *state = values
        return (int(x // 15), int(y // 15), int(vy // 2), *state)

    return (player(cell["p1"]), player(cell["p2"]), cell["held"], cell["world"], cell["items"])


def run_path(solver, actions, *, cells=False, xs=False):
    """Respect the bridge's per-request action cap for long prefixes."""
    result = {"terminal": None, "cells": [], "xs": [], "decisions": 0}
    for start in range(0, len(actions), 20000):
        reply = solver.run(actions[start:start + 20000], cells=cells, xs=xs)
        result["cells"].extend(reply.get("cells", []))
        result["xs"].extend(reply.get("xs", []))
        result["decisions"] += reply["decisions"]
        result["terminal"] = reply["terminal"]
        if reply["terminal"]:
            break
    return result


@dataclass
class Node:
    parent: int | None
    seed_length: int
    actions: list
    cell: dict
    attempts: int = 0
    disabled: bool = False


class Archive:
    MAX_NODES = 2048
    MAX_TRIALS = 96
    MAX_REPLAY_TICKS = 2_500_000
    REPRESENTATIVES = 2
    SEED_SEGMENTS = 96

    def __init__(self, solver, seed):
        self.solver = solver
        self.seed = seed
        level = json.dumps(solver.level, sort_keys=True).encode("utf-8")
        self.digest = hashlib.sha256(level + b"\0" + bytes(seed)).hexdigest()
        self.path = (solver.progress.parent / "archives" / solver.progress.with_suffix(".archive.json").name
                     if solver.progress else None)
        self.nodes = []
        self.groups = {}
        self.trials = 0
        self.replay_ticks = 0
        self.horizon = None
        self.furthest = len(seed)
        self.load()

    def load(self):
        if not self.path or not self.path.exists():
            return
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if (data["version"], data["prefix"], data["segment_size"]) != (1, self.digest, self.solver.seg):
            return
        self.nodes = [Node(**record) for record in data["nodes"]]
        self.horizon = data["horizon"]
        self.trials = data["trials"]
        self.replay_ticks = data["replay_ticks"]
        self.furthest = data.get("furthest", len(self.seed))
        self.solver.evals = max(self.solver.evals, data["evaluations"])
        self.solver.ticks = max(self.solver.ticks, data["ticks"])
        for index, node in enumerate(self.nodes):
            self.groups.setdefault(cell_key(node.cell), []).append(index)

    def save(self):
        if not self.path:
            return
        self.path.parent.mkdir(exist_ok=True)
        state = {"version": 1, "prefix": self.digest, "segment_size": self.solver.seg,
                 "horizon": self.horizon, "nodes": [asdict(node) for node in self.nodes],
                 "trials": self.trials, "replay_ticks": self.replay_ticks,
                 "furthest": self.furthest,
                 "evaluations": self.solver.evals, "ticks": self.solver.ticks}
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, separators=(",", ":")), encoding="utf-8")
        temporary.replace(self.path)

    def add(self, cell, parent, actions, *, seed_length=0):
        key = cell_key(cell)
        group = self.groups.get(key, [])
        if len(self.nodes) >= self.MAX_NODES or len(group) >= self.REPRESENTATIVES:
            return None
        physical = {k: v for k, v in cell.items() if k != "t"}
        if any(all(self.nodes[i].cell[k] == v for k, v in physical.items()) for i in group):
            return None
        index = len(self.nodes)
        self.groups.setdefault(key, []).append(index)
        self.nodes.append(Node(parent, seed_length, actions, cell))
        return index

    def tape(self, index):
        parts = []
        node = self.nodes[index]
        while node.parent is not None:
            parts.append(node.actions)
            node = self.nodes[node.parent]
        return self.seed[:node.seed_length] + [action for part in reversed(parts) for action in part]

    def run(self, actions, *, cells=False, xs=False):
        return run_path(self.solver, actions, cells=cells, xs=xs)

    def reset(self):
        reset = self.solver.reset_zero()
        if "world_hash" not in reset.get("state", {}):
            raise RuntimeError("archive search requires the M9 world-state bridge")

    def check_resources(self):
        if self.solver.archive_guard:
            try:
                self.solver.archive_guard()
            except Exception:
                self.save()
                raise

    def prepare(self):
        seg = self.solver.seg
        start = max(0, len(self.seed) - self.SEED_SEGMENTS * seg)
        self.reset()
        if self.run(self.seed[:start])["terminal"]:
            return None
        trace = self.run(self.seed[start:], cells=True)
        if trace["terminal"] or len(trace["cells"]) != len(self.seed) - start:
            return None
        for length, cell in enumerate(trace["cells"], start + 1):
            if length % seg == 0:
                self.add(cell, None, [], seed_length=length)
        if not self.nodes:
            return None
        # Compare against both constant continuations from the saved boundary.
        horizon = len(self.seed)
        for action in (0, 1):
            if self.solver.evals >= self.solver.budget:
                return None
            self.check_resources()
            self.reset()
            if self.run(self.seed)["terminal"]:
                return None
            self.solver.evals += 1
            result = self.run([action] * (self.solver.look + 8 * seg))
            horizon = max(horizon, len(self.seed) + result["decisions"])
        self.horizon = horizon
        return horizon

    def choose(self, rng):
        available = [i for i, node in enumerate(self.nodes) if not node.disabled]
        if not available:
            return None
        if rng.random() < .125:
            return rng.choice(available)
        latest = max(self.nodes[i].cell["t"] for i in available)
        recency_scale = 32 * self.solver.seg
        weights = []
        for i in available:
            node = self.nodes[i]
            recency = 1 + 2 / (1 + (latest - node.cell["t"]) / recency_scale)
            weights.append(recency * (1 + (node.parent is not None)) / (1 + node.attempts))
        return rng.choices(available, weights=weights, k=1)[0]

    def explore(self):
        """Return a tape and expected end cell, using None for a terminal clear."""
        if self.horizon is None and self.prepare() is None:
            return None
        solver = self.solver
        trial_limit = min(solver.budget, solver.evals + self.MAX_TRIALS)
        replay_limit = self.replay_ticks + self.MAX_REPLAY_TICKS
        while solver.evals < trial_limit and self.replay_ticks < replay_limit:
            self.check_resources()
            rng = random.Random(int(self.digest[:16], 16) + self.trials)
            index = self.choose(rng)
            if index is None or len(self.nodes) >= self.MAX_NODES:
                break
            node = self.nodes[index]
            tape = self.tape(index)
            previous_ticks = solver.ticks
            self.reset()
            replay = self.run(tape[:-1])
            boundary = self.run(tape[-1:], cells=True) if not replay["terminal"] else replay
            self.replay_ticks += solver.ticks - previous_ticks
            solver.evals += 1
            self.trials += 1
            node.attempts += 1
            if boundary["terminal"] or boundary["cells"] != [node.cell]:
                node.disabled = True
                continue
            size = 8 * solver.seg
            action = (node.attempts - 1) % 2
            duration = 1 << min((node.attempts - 1) // 2, 5)
            tail = ([action] * min(duration, solver.seg) +
                    solver._random_tail(rng, size))[:size]
            reply = self.run(tail, cells=True)
            self.furthest = max(self.furthest, len(tape) + reply["decisions"])
            if reply["terminal"] == "complete":
                self.save()
                return tape + tail[:reply["decisions"] + 1], None
            novel = set()
            for length, cell in enumerate(reply["cells"], 1):
                if length % solver.seg:
                    continue
                key = cell_key(cell)
                if len(tape) + length > self.horizon and key not in self.groups:
                    novel.add(key)
                self.add(cell, index, tail[:length])
            if not reply["terminal"] and len(novel) >= 2:
                length = len(tape) + size
                self.save()
                return (tape + tail)[:length], reply["cells"][-1]
            if self.trials % 8 == 0:
                self.save()
        self.save()
        return None
