"""Verify generated fixtures and capture repeatable clears on the isolated bridge."""

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from time import sleep

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from gdbot.levels.drills import (
    BLOCK, GRAVITY_NORMAL, GRAVITY_REVERSED, SPIKE, SPEED_FAST, YELLOW_ORB, iter_drills,
)
from gdbot.protocol import PIPE_PREFIX, BridgeClient, NamedPipeTransport, RemoteError
from gdbot.replay import Tape, diff_traces, replay

FIXTURES = ROOT / "levels/drills"
CATEGORIES = {BLOCK: "solid", SPIKE: "hazard", YELLOW_ORB: "orb", GRAVITY_NORMAL: "portal_gravity",
              GRAVITY_REVERSED: "portal_gravity", SPEED_FAST: "portal_speed"}
WORLD_Y_OFFSET = 90
POSITION_TOLERANCE = 4
ZERO = {"kind": "zero"}
FINISH_WAIT_SECONDS = 1.2


@dataclass(frozen=True)
class Target:
    x: float
    orb: bool = False


def targets_for(drill):
    level = drill.level.objects
    x_final = max(float(obj["2"]) for obj in level)
    targets = [Target(x_final)]
    spikes = [float(obj["2"]) for obj in level if int(obj["1"]) == SPIKE]
    previous = -1_000
    for x in sorted(spikes):
        if x > previous + 31:
            targets.append(Target(x))
        previous = x
    targets.extend(Target(float(obj["2"]), orb=True) for obj in level if int(obj["1"]) == YELLOW_ORB)
    if drill.family in ("block-steps", "pillar-gaps"):
        previous = -1_000
        for x in sorted({float(obj["2"]) for obj in level if int(obj["1"]) == BLOCK} - {x_final}):
            if x > previous + (110 if drill.family == "pillar-gaps" else 31):
                targets.append(Target(x))
            previous = x
    if drill.family == "moving-geometry":
        targets.extend(Target(float(obj["2"])) for obj in level if "57" in obj)
    return sorted(targets, key=lambda target: target.x)


def observe(seen, reply):
    for obj in reply["obs"]["objects"]:
        if obj["type_id"] in CATEGORIES and abs(obj["x"]) > POSITION_TOLERANCE:
            first = seen.setdefault(obj["uid"], {**obj, "min_y": obj["y"], "max_y": obj["y"]})
            first["min_y"] = min(first["min_y"], obj["y"])
            first["max_y"] = max(first["max_y"], obj["y"])


def object_differences(drill, seen):
    expected = [
        {"type_id": int(obj["1"]), "x": float(obj["2"]), "y": float(obj["3"]) + WORLD_Y_OFFSET}
        for obj in drill.level.objects if int(obj["1"]) in CATEGORIES
    ]
    missing, mismatched, motion = [], [], []
    unmatched = dict(seen)
    for obj in expected:
        candidates = [
            other for other in unmatched.values()
            if other["type_id"] == obj["type_id"] and abs(other["x"] - obj["x"]) <= POSITION_TOLERANCE
        ]
        closest = min(candidates, key=lambda other: abs(other["y"] - obj["y"]), default=None)
        if closest is None:
            missing.append(obj)
            continue
        del unmatched[closest["uid"]]
        if (abs(closest["y"] - obj["y"]) > POSITION_TOLERANCE
                or closest["cat"] != CATEGORIES[obj["type_id"]]):
            mismatched.append({"expected": {**obj, "cat": CATEGORIES[obj["type_id"]]}, "observed": closest})
        if closest["max_y"] - closest["min_y"] > POSITION_TOLERANCE:
            motion.append({"x": closest["x"], "min_y": closest["min_y"], "max_y": closest["max_y"]})
    return {"expected": len(expected), "seen": len(seen), "missing": missing,
            "mismatched": mismatched, "unexpected": list(unmatched.values()), "motion": motion}


def attempt(client, targets, seen, lead, orb_lead, *, pillar_hold=False):
    reset = client.request("reset", start=ZERO)
    observe(seen, reset)
    episode, tick = reset["episode"], reset["tick"]
    player = reset["obs"]["players"][0]
    target_index = 0
    action = 0
    edges = []
    finish_at = None
    for _ in range(15_000):
        x = player["x"]
        vx = max(1.2982, player["vx"])
        while target_index < len(targets) and x > targets[target_index].x + 12:
            target_index += 1
        target = targets[target_index] if target_index < len(targets) else None
        threshold = None
        if target:
            jump_lead = 42 if target.x == targets[-1].x else lead
            threshold = target.x - (orb_lead if target.orb else jump_lead * vx / 1.2982)
        if action:
            next_action = int(pillar_hold and target is not None and x >= threshold and not target.orb)
            count = 1
        elif target and x >= threshold and (target.orb or player["on_ground"] or pillar_hold):
            next_action, count = 1, 1
            target_index += 1
        else:
            next_action = 0
            count = 12 if threshold is None else max(1, min(12, int((threshold - x) / vx)))
        if finish_at is not None:
            sleep(FINISH_WAIT_SECONDS)
            count = 1
        result = client.step(episode=episode, tick=tick, action=next_action, k=count)
        if next_action != action:
            edges.append((tick + 1, next_action))
        tick, action = result["tick"], next_action
        player = result["obs"]["players"][0]
        observe(seen, result)
        if result["terminal"] or tick >= 9_000 or finish_at is not None:
            return result["terminal"], tick, tuple(edges), player, finish_at
        if player["x"] > targets[-1].x and abs(player["vx"]) < 0.25:
            finish_at = tick
    raise RuntimeError("attempt exceeded the step budget")


def search(client, drill, selector, build_hash, revision, digest):
    seen = {}
    best = None
    attempts = 0
    targets = targets_for(drill)
    leads = (42, 35, 51, 28, 59, 21, 66)
    orb_leads = (7, 1, 13) if drill.family == "yellow-orb" else (0,)
    use_hold = (False, True) if drill.family == "pillar-gaps" else (False,)
    settings = {"profile": "isolated launcher profile", "drill_sha256": digest,
                "recorded_mode": "dedicated"}
    for hold in use_hold:
        for lead in leads:
            for orb_lead in orb_leads:
                attempts += 1
                terminal, tick, edges, player, finish_at = attempt(
                    client, targets, seen, lead, orb_lead, pillar_hold=hold,
                )
                if best is None or player["x"] > best["x"]:
                    best = {"tick": tick, "terminal": terminal, "x": player["x"], "y": player["y"],
                            "lead": lead, "orb_lead": orb_lead, "edges": edges}
                if terminal == "complete":
                    finish_wait = None if finish_at is None else (finish_at, FINISH_WAIT_SECONDS)
                    tape = Tape(
                        build_hash, selector, revision, settings, drill.seed, ZERO, tick, edges, terminal,
                        finish_wait=finish_wait,
                    )
                    traces = [
                        replay(client, tape, settings=settings, seed=drill.seed, mode="dedicated", chunk_ticks=12)
                        for _ in range(2)
                    ]
                    for trace in traces:
                        if not trace or trace[-1]["tick"] != tick or trace[-1].get("terminal") != "complete":
                            return attempts, best, object_differences(drill, seen), None, "replay did not reproduce the clear"
                    difference = diff_traces(*traces)
                    if difference is not None:
                        return attempts, best, object_differences(drill, seen), None, f"replay diverged: {difference}"
                    return attempts, best, object_differences(drill, seen), tape, None
    return attempts, best, object_differences(drill, seen), None, "bounded jump search did not clear the drill"


def run(args):
    discovery = json.loads((ROOT / "game/2.2091/gdbot/bridge.json").read_text(encoding="utf-8"))
    if discovery["pid"] != args.pid or discovery["pipe"] != PIPE_PREFIX + str(args.pid):
        raise RuntimeError("discovery does not match the launcher-owned PID")
    report = []
    with BridgeClient(NamedPipeTransport(discovery["pipe"])) as client:
        hello = client.require_isolated()
        if not all(hello["capabilities"].get(key) is True for key in ("objects", "level_string", "quit_level", "trace")):
            raise RuntimeError("bridge lacks the capabilities needed for drill verification")
        client.request("set_mode", mode="dedicated")
        for drill in iter_drills():
            if args.family and drill.family not in args.family:
                continue
            if args.variant and drill.variant not in args.variant:
                continue
            relative = Path(drill.family) / f"{drill.variant}.txt"
            data = (FIXTURES / relative).read_bytes()
            if data.decode("ascii") != drill.level.encode():
                raise RuntimeError(f"fixture differs from the builder: {relative}")
            digest = hashlib.sha256(data).hexdigest()
            selector = {"kind": "level_string", "name": f"{drill.family}-{drill.variant}", "data": data.decode("ascii")}
            row = {"family": drill.family, "variant": drill.variant, "sha256": digest, "tape": None}
            try:
                loaded = client.load_level(selector)
                row["revision"] = loaded["revision"]
                attempts, best, objects, tape, reason = search(
                    client, drill, selector, hello["build"]["exe_sha256"], loaded["revision"], digest,
                )
                row.update(attempts=attempts, best=best, objects=objects, reason=reason)
                if tape:
                    path = FIXTURES / "tapes" / relative.with_suffix(".json")
                    path.parent.mkdir(parents=True, exist_ok=True)
                    tape.save(path)
                    row["tape"] = path.relative_to(FIXTURES).as_posix()
            except RemoteError as exc:
                row["reason"] = str(exc)
            finally:
                report.append(row)
                args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
                print(json.dumps(row, separators=(",", ":")), flush=True)
                client.request("quit_level")
    return int(any(not item["tape"] for item in report))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--family", action="append")
    parser.add_argument("--variant", action="append")
    raise SystemExit(run(parser.parse_args()))
