"""Find in-game completion witnesses and audit M5 object metadata on the k=4 grid."""

import argparse
import hashlib
import json
from itertools import product
from pathlib import Path

from study import DRILLS, K, connect
from gdbot.levels.drills import (
    BLOCK, GRAVITY_NORMAL, M5_NOTES, MINI_PORTAL, MODE_PORTALS, ORBS, PADS, SPIKE,
    iter_m5_drills, write_drills,
)
from gdbot.replay import Tape

EXPECTED = {
    BLOCK: ("solid", {}), SPIKE: ("hazard", {}),
    MINI_PORTAL: ("portal_size", {"to": "mini"}),
    GRAVITY_NORMAL: ("portal_gravity", {"to": "normal"}),
    **{key: ("portal_mode", {"to": mode}) for mode, key in MODE_PORTALS.items()},
    **{key: ("pad", {"kind": "gravity" if kind == "blue" else kind}) for kind, key in PADS.items()},
    **{key: ("orb", {"kind": "dash_green" if kind == "dash" else kind}) for kind, key in ORBS.items()},
}
WORLD_Y_OFFSET = 90
ZERO = {"kind": "zero"}
TICK_LIMIT = 6_000


class WitnessPolicy:
    def __init__(self, drill, lead, hold, steering):
        self.family = drill.family
        self.lead = lead
        self.hold = hold
        self.steering = steering
        self.objects = [(int(item["1"]), float(item["2"]), float(item["3"]) + WORLD_Y_OFFSET,
                         item.get("6") == "180") for item in drill.level.objects]
        self.spikes = [(x, inverted) for kind, x, _, inverted in self.objects if kind == SPIKE]
        self.orbs = [(x, y, kind) for kind, x, y, _ in self.objects if kind in ORBS.values()]
        self.platforms = sorted({x for kind, x, y, _ in self.objects if kind == BLOCK and y <= 180})
        self.low_walls = sorted({x for kind, x, y, _ in self.objects if kind == BLOCK and y == 165})
        self.high_walls = sorted({x for kind, x, y, _ in self.objects if kind == BLOCK and y == 255})
        self.used = set()
        self.release_at = 0

    def flight(self, player, action):
        x, y, vy = (player[key] for key in ("x", "y", "vy"))
        # Look ahead to steer toward the opening and away from the current wall.
        low = min((position for position in self.low_walls if position + 20 >= x), default=float("inf"))
        high = min((position for position in self.high_walls if position + 20 >= x), default=float("inf"))
        target = 245 if low < high and low - x < 240 else 175 + self.steering
        if high < low and high - x < 220:
            target = 165
        if player["mode"] == "ship":
            return int(y + vy * 4 < target)
        if player["mode"] == "wave":
            return int(y + (10 if action else -10) < target)
        want_up = y + vy * 5 < target
        if player["gravity_flipped"] == want_up:
            return 0
        return 1 - action

    def choose(self, player, tick, action):
        x, mode = player["x"], player["mode"]
        if mode in ("ship", "wave", "swing"):
            return self.flight(player, action)
        if tick < self.release_at:
            return 1
        if action:
            return 0
        if mode in ("ball", "spider"):
            for position, inverted in self.spikes:
                if position not in self.used and 0 < position - x < self.lead and (
                    player["gravity_flipped"] == inverted and player["on_ground"]
                ):
                    self.used.add(position)
                    return 1
            return 0
        if mode == "ufo":
            target = 199 + self.steering if any(0 < p - x < 150 for p in self.platforms) else 155
            return int(player["y"] < target and player["vy"] <= 0)
        for position, y, kind in self.orbs:
            close = abs(x - position) <= max(12, self.lead - 28)
            if kind == ORBS["green"]:
                close = -(18 + self.steering / 2) <= x - position <= 23 and abs(player["y"] - y) < 25
            if position not in self.used and close and not player["on_ground"]:
                self.used.add(position)
                hold = {ORBS["dash"]: 93, ORBS["green"]: 20}.get(kind, 4)
                self.release_at = tick + hold
                return 1
            if player["on_ground"] and 0 < position - x <= self.lead:
                return 1
        targets = [(position, inverted) for position, inverted in self.spikes]
        if mode == "robot":
            targets += [(position, False) for position in self.platforms]
        for position, inverted in sorted(targets):
            upper_robot = mode == "robot" and position == max(self.platforms, default=-1)
            lead = self.lead + (self.steering if upper_robot else 0)
            if position not in self.used and 0 < position - x < lead and (
                player["gravity_flipped"] == inverted and player["on_ground"]
            ):
                self.used.add(position)
                self.release_at = tick + (self.hold if upper_robot else 4)
                return 1
        return 0


def audit_objects(drill, observed):
    unmatched = list(observed.values())
    problems = []
    for record in drill.level.objects:
        kind, x, y = int(record["1"]), float(record["2"]), float(record["3"]) + WORLD_Y_OFFSET
        candidates = [item for item in unmatched if item["type_id"] == kind and abs(item["x"] - x) <= 4]
        match = min(candidates, key=lambda item: abs(item["y"] - y), default=None)
        if match is None:
            problems.append({"id": kind, "x": x, "y": y, "problem": "missing"})
            continue
        unmatched.remove(match)
        category, params = EXPECTED[kind]
        if abs(match["y"] - y) > 4 or match["cat"] != category or any(
            match["params"].get(key) != value for key, value in params.items()
        ):
            problems.append({"id": kind, "x": x, "y": y, "expected": [category, params], "actual": match})
    return problems


def play(client, drill, policy, *, witness=None):
    reset = client.request("reset", start=ZERO)
    tick, held, terminal = reset["tick"], 0, None
    edges, observed = [], {}
    modes, flags = set(), set()
    recorded = dict(witness.edges) if witness else {}
    reply = reset
    while True:
        player = reply["obs"]["players"][0]
        for obj in reply["obs"]["objects"]:
            observed.setdefault(obj["uid"], obj)
        modes.add(player["mode"])
        flags.update(key for key in ("mini", "gravity_flipped", "dashing") if player[key])
        if terminal or tick >= TICK_LIMIT:
            break
        action = recorded.get(tick + 1, held) if witness else policy.choose(player, tick, held)
        if action != held:
            edges.append((tick + 1, action))
        reply = client.step(episode=reset["episode"], tick=tick, action=action, k=K)
        tick, held, terminal = reply["tick"], action, reply["terminal"]
    return terminal, tick, tuple(edges), observed, modes, flags, player


def attempt_fixture(client, drill, tape_path, exe_hash):
    level = {"kind": "level_string", "name": f"{drill.family}-{drill.variant}", "data": drill.level.encode()}
    loaded = client.load_level(level)
    settings = {"decision_ticks": K, "drill_sha256": hashlib.sha256(level["data"].encode("ascii")).hexdigest()}
    required_modes = {mode for mode, kind in MODE_PORTALS.items()
                      if any(int(item["1"]) == kind for item in drill.level.objects)}
    required_flags = {
        "mini-cube": {"mini"}, "dash-orb": {"dashing"},
        "blue-pad": {"gravity_flipped"}, "blue-orb": {"gravity_flipped"}, "green-orb": {"gravity_flipped"},
    }.get(drill.family, set())
    coverage, best = {}, None
    try:
        witness = Tape.load(tape_path) if tape_path.exists() else None
        if witness is None:
            for lead, hold, steering in product((47, 59, 71, 35, 83, 95), (28, 56), (0, 20, -15)):
                trial = play(client, drill, WitnessPolicy(drill, lead, hold, steering))
                terminal, tick, edges, observed, modes, flags, player = trial
                coverage.update(observed)
                if best is None or player["x"] > best["player"]["x"]:
                    best = {"lead": lead, "hold": hold, "steering": steering, "terminal": terminal,
                            "ticks": tick, "player": player, "flags": sorted(flags), "edges_until_failure": edges}
                if terminal == "complete" and required_modes <= modes and required_flags <= flags:
                    witness = Tape(exe_hash, level, loaded["revision"], settings, drill.seed, ZERO, tick, edges, terminal)
                    break
        if witness is None:
            return {"ready": False, "reason": "no verified completion witness", "best": best,
                    "missing_expected_ids": sorted({int(obj["1"]) for obj in drill.level.objects}
                                                   - {obj["type_id"] for obj in coverage.values()})}
        if witness.level != level or witness.level_revision != loaded["revision"] or witness.build_hash != exe_hash:
            raise RuntimeError(f"stale witness for {drill.family}/{drill.variant}")
        terminal, tick, edges, observed, modes, flags, _ = play(client, drill, None, witness=witness)
        problems = audit_objects(drill, observed)
        ready = terminal == "complete" and tick == witness.total_ticks and edges == witness.edges and not problems
        ready = ready and required_modes <= modes and required_flags <= flags
        if ready:
            tape_path.parent.mkdir(parents=True, exist_ok=True)
            staging = tape_path.with_suffix(".tmp")
            witness.save(staging)
            staging.replace(tape_path)
        return {"ready": ready, "terminal": terminal, "ticks": tick, "edge_count": len(edges),
                "modes": sorted(modes), "flags": sorted(flags), "metadata": problems}
    finally:
        client.request("quit_level")


def verify(client, output, families):
    build = client.require_isolated()["build"]["exe_sha256"]
    output.mkdir(parents=True, exist_ok=True)
    path = output / "verification.json"
    results = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    for drill in iter_m5_drills():
        if families and drill.family not in families:
            continue
        fixture = f"{drill.family}/{drill.variant}"
        tape_path = DRILLS / "tapes" / f"{fixture}.json"
        results[fixture] = attempt_fixture(client, drill, tape_path, build)
        stage = path.with_suffix(".tmp")
        stage.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
        stage.replace(path)
        print(fixture, results[fixture]["ready"], flush=True)
    write_drills(DRILLS, m5=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--family", choices=M5_NOTES, action="append")
    options = parser.parse_args()
    with connect(options.pid) as client:
        client.require_isolated()
        client.request("set_mode", mode="dedicated")
        verify(client, options.output, options.family)
