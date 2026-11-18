"""Run cadence, input, and encoder diagnostics on three M3 drill families."""

import argparse
import json
from collections import deque
from pathlib import Path

from baseline import DrillEnv, EVAL_SEED, ROOT, eval_attempt, fixtures, frozen_policy

import torch
from stable_baselines3 import PPO

from gdbot.baselines import TimingHeuristic
from gdbot.levels.levelstring import LevelString
from gdbot.obs import CATEGORIES, OBJECT_WIDTH, PLAYER_VECTOR_WIDTH, ObservationEncoder
from gdbot.protocol import PIPE_PREFIX, BridgeClient, NamedPipeTransport
from gdbot.replay import Tape

FAMILIES = ("single-spike", "double-spike", "yellow-orb")
DRILLS = ROOT / "levels/drills"


def quantize(edges, k, phase):
    anchor = phase + 1
    result = []
    for tick, action in edges:
        grid = anchor + max(0, (tick - anchor + k // 2) // k) * k
        if result:
            grid = max(grid, result[-1][0] + k)
        result.append((grid, action))
    return result


def execute(client, edges, k, limit, inspect=None):
    reset = client.request("reset", start={"kind": "zero"})
    episode, tick, action = reset["episode"], 0, 0
    index = 0
    for _ in range(limit):
        if index < len(edges) and edges[index][0] == tick + 1:
            action = edges[index][1]
            index += 1
        next_edge = edges[index][0] - 1 if index < len(edges) else limit
        result = client.step(episode=episode, tick=tick, action=action, k=min(k, next_edge - tick))
        tick = result["tick"]
        if inspect is not None:
            inspect(result)
        if result["terminal"] or tick == limit:
            break
    player = result["obs"]["players"][0]
    return {"terminal": result["terminal"], "tick": tick, "x": player["x"], "y": player["y"]}


def cadence_check(client, tape):
    results = []
    for k in (4, 3, 2, 1):
        for phase in range(k):
            outcome = execute(client, quantize(tape.edges, k, phase), k, 6_000)
            results.append({"k": k, "phase": phase, **outcome})
        if any(row["terminal"] == "complete" for row in results):
            break
    return results


def orb_check(client, tape):
    takeoff, release, orb_press = [tick for tick, _ in tape.edges[:3]]
    raw = LevelString.decode(tape.level["data"])
    orb_x = min(float(obj["2"]) for obj in raw.objects if obj["1"] == "36")
    left, right = orb_press - 45, orb_press + 46

    def trial(edges):
        samples = []

        def inspect(reply):
            if not left <= reply["tick"] <= right:
                return
            obs = reply["obs"]
            p = obs["players"][0]
            orb = min((o for o in obs["objects"] if o["cat"] == "orb"),
                      key=lambda o: abs(o["x"] - orb_x), default=None)
            samples.append({"tick": reply["tick"], **p, "orb": orb})

        end = execute(client, edges, 1, right, inspect)
        boosts = [
            {"tick": b["tick"], "x": b["x"], "y": b["y"], "vy_before": a["vy"], "vy": b["vy"]}
            for a, b in zip(samples, samples[1:])
            if not a["on_ground"] and b["vy"] - a["vy"] > 4
        ]
        return {"edges": edges, "boosts": boosts, "end": end, "samples": samples}

    held = trial([(takeoff, 1)])
    first_overlap = next(
        row["tick"] for row in held["samples"]
        if row["orb"] and abs(row["x"] - row["orb"]["x"]) <= 15 + row["orb"]["w"] / 2
        and abs(row["y"] - row["orb"]["y"]) <= 15 + row["orb"]["h"] / 2
    )
    return {"first_geometric_overlap": first_overlap, "cases": {
        "held_through": held,
        "fresh_verified_press": trial([(takeoff, 1), (release, 0), (orb_press, 1), (orb_press + 1, 0)]),
        "fresh_overlap_entry": trial([(takeoff, 1), (release, 0), (first_overlap, 1), (first_overlap + 1, 0)]),
        "before_overlap_released": trial([(takeoff, 1), (release, 0), (first_overlap - 5, 1),
                                          (first_overlap - 4, 0)]),
        "before_overlap_held": trial([(takeoff, 1), (release, 0), (first_overlap - 5, 1)]),
    }}


def encoder_probe(client):
    encoder = ObservationEncoder()
    samples = deque(maxlen=8)

    def inspect(reply):
        if reply["terminal"]:
            return
        obs = reply["obs"]
        player = obs["players"][0]
        vector = encoder.encode(obs, reply["tick"])
        hazards = [obj for obj in obs["objects"] if obj["cat"] == "hazard" and obj["x"] > player["x"]]
        if not hazards:
            return
        hazard = min(hazards, key=lambda obj: obj["x"])
        row = vector[PLAYER_VECTOR_WIDTH:PLAYER_VECTOR_WIDTH + OBJECT_WIDTH]
        samples.append({
            "tick": reply["tick"], "gap": hazard["x"] - player["x"], "raw_player": player,
            "raw_hazard": hazard, "truncated": encoder.truncated, "unsupported": encoder.unsupported,
            "nearest_encoded": row.tolist(), "mask_count": int(vector[-encoder.max_objects:].sum()),
            "first_slot_hazard": bool(row[13 + CATEGORIES.index("hazard")]),
            "policy_input": vector.tolist(),
        })

    return {"outcome": execute(client, [], 4, 1500, inspect), "last": list(samples)}


def checkpoint_curve(client, pool, checkpoints):
    data = {}
    for layout in ("topk", "set"):
        env = DrillEnv(client, layout)
        for generation in ("initial", "round-1", "round-2"):
            model = PPO.load(checkpoints / layout / f"{generation}.zip", device="cpu")
            choose = frozen_policy(model)
            for index, fixture in enumerate(pool):
                env.select(fixture)
                trials = [eval_attempt(env, choose, EVAL_SEED + 10 * index + i, deterministic=i == 0)
                          for i in range(3)]
                data.setdefault(fixture.family, {}).setdefault(layout, {})[generation] = trials
        env.leave()
    return data


def timing_check(client, pool):
    results = {}
    env = DrillEnv(client, "topk")
    for fixture in pool:
        env.select(fixture)
        trials = {}
        for jump_lead in (0.08, 0.12, 0.14):
            heuristic = TimingHeuristic(jump_lead_s=jump_lead)
            trials[str(jump_lead)] = eval_attempt(
                env, lambda env, obs, deterministic: heuristic(env.raw_observation), EVAL_SEED, True,
            )
        results[f"{fixture.family}/{fixture.variant}"] = trials
    env.leave()
    return results


def confirm_heuristic(client, pool):
    env = DrillEnv(client, "topk")
    policy = TimingHeuristic()
    results = {}
    for fixture in pool:
        env.select(fixture)
        result = eval_attempt(env, lambda env, obs, deterministic: policy(env.raw_observation), EVAL_SEED, True)
        results[f"{fixture.family}/{fixture.variant}"] = result
    env.leave()
    return results


def run(args):
    discovery = json.loads((ROOT / "game/2.2091/gdbot/bridge.json").read_text(encoding="utf-8"))
    if discovery["pid"] != args.pid or discovery["pipe"] != PIPE_PREFIX + str(args.pid):
        raise RuntimeError("discovery must match the launcher-owned process")
    torch.set_num_threads(2)
    pools = {key: [fixture for fixture in value if fixture.family in FAMILIES]
             for key, value in fixtures().items()}
    report = {"cadence": {}, "orb": {}, "encoder": {}, "train_checkpoint_curve": {}}

    def persist():
        args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")

    with BridgeClient(NamedPipeTransport(discovery["pipe"])) as client:
        hello = client.require_isolated()
        report["build"] = hello["build"]
        client.request("set_mode", mode="dedicated")
        if args.confirm_heuristic:
            report = json.loads(args.output.read_text(encoding="utf-8"))
            report["heuristic_after"] = confirm_heuristic(client, pools["train"] + pools["heldout"])
            persist()
            print(json.dumps(report["heuristic_after"], indent=2), flush=True)
            client.request("set_mode", mode="normal")
            return
        for fixture in pools["heldout"]:
            tape = Tape.load(DRILLS / "tapes" / fixture.family / f"{fixture.variant}.json")
            loaded = client.load_level(fixture.level)
            if loaded["revision"] != tape.level_revision or hello["build"]["exe_sha256"] != tape.build_hash:
                raise RuntimeError("drill identity changed")
            report["cadence"][fixture.family] = cadence_check(client, tape)
            persist()
            print(f"cadence {fixture.family}: {report['cadence'][fixture.family]}", flush=True)
            client.request("quit_level")
        if not all(any(row["k"] == 4 and row["terminal"] == "complete" for row in trials)
                   for trials in report["cadence"].values()):
            return
        for split in ("train", "heldout"):
            fixture = next(f for f in pools[split] if f.family == "yellow-orb")
            tape = Tape.load(DRILLS / "tapes" / fixture.family / f"{fixture.variant}.json")
            client.load_level(fixture.level)
            report["orb"][split] = orb_check(client, tape)
            persist()
            print(f"orb {split}: " + str({key: case["boosts"] for key, case in report["orb"][split]["cases"].items()}),
                  flush=True)
            client.request("quit_level")
        for split in ("train", "heldout"):
            fixture = next(f for f in pools[split] if f.family == "single-spike")
            client.load_level(fixture.level)
            report["encoder"][split] = encoder_probe(client)
            persist()
            client.request("quit_level")
        report["train_checkpoint_curve"] = checkpoint_curve(client, pools["train"], args.checkpoints)
        report["timing_train"] = timing_check(client, pools["train"])
        persist()
        client.request("set_mode", mode="normal")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--checkpoints", type=Path, default=ROOT / "build/m3-baseline/first-study")
    parser.add_argument("--confirm-heuristic", action="store_true")
    run(parser.parse_args())
