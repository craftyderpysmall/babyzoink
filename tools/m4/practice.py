"""Compare frozen behavior clones with per-level checkpoint practice at k=4."""

import argparse
import hashlib
import json
import math
import sys
from dataclasses import asdict
from pathlib import Path
from statistics import mean
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "m3"))

import numpy as np
import torch
from stable_baselines3 import PPO

from baseline import EVAL_SEED, MAX_ATTEMPTS, ROOT, DrillEnv, _manifest_rows, frozen_policy, save_report
from imitation import behaviour_clone, collect_demo
from scale import SEEDS, scaled_fixtures
from gdbot.curriculum import DeathHotspots, Decision, practice_section, x_position
from gdbot.levels.levelstring import LevelString, with_startpos
from gdbot.protocol import PIPE_PREFIX, BridgeClient, NamedPipeTransport

SEARCH_LIMIT = 36
MODE = "topk"


def startpos_preflight(client):
    level = LevelString()
    level.add(1, 1800, 15)
    evidence = []
    for x, mode, code, speed, gravity, mini in (
        (0, "cube", 0, 0.9, False, False),
        (420, "cube", 0, 0.9, False, False),
        (750, "ship", 2, 1.1, True, True),
    ):
        variant = with_startpos(level, x, mode, code, gravity, mini) if x else level
        client.load_level({"kind": "level_string", "name": f"m4-start-probe-{x}", "data": variant.encode()})
        reset = client.request("reset", start={"kind": "zero"})
        advance = client.step(episode=reset["episode"], tick=reset["tick"], action=0, k=4)
        client.request("quit_level")
        expected = {"mode": mode, "gravity_flipped": gravity, "mini": mini}
        for reply in (reset, advance):
            player = reply["obs"]["players"][0]
            if not math.isclose(player["speed"], speed, abs_tol=1e-6) or any(
                player[key] != value for key, value in expected.items()
            ):
                raise RuntimeError(f"incorrect startpos mode, speed, gravity or size: {player}")
        before, after = (reply["obs"]["players"][0] for reply in (reset, advance))
        if not math.isclose(before["x"], x, abs_tol=0.01) or after["x"] <= x or advance["terminal"]:
            raise RuntimeError(f"incorrect startpos position or motion: {before} -> {after}")
        evidence.append({key: before[key] for key in ("x", "y", "mode", "speed", "gravity_flipped", "mini")})
    return evidence


def full_run(env, choose, ordinal, seed):
    started = perf_counter()
    torch.manual_seed(seed)
    observation, _ = env.reset(seed=seed, options={"start": {"kind": "zero"}})
    if abs(x_position(env)) >= 1:
        raise RuntimeError("the original drill did not reset to 0%")
    decisions = []
    peak = 0.0
    ticks = 0
    while True:
        action = choose(env, observation, ordinal == 0)
        decisions.append(Decision(x_position(env), observation, action))
        observation, _, terminated, truncated, info = env.step(action)
        peak = max(peak, info["progress"])
        ticks += info["ticks_advanced"]
        if terminated or truncated:
            return decisions, {
                "terminal": info["terminal"] or "tick_limit", "peak_progress": peak, "seed": seed,
                "ticks": ticks, "transitions": len(decisions), "wall_s": perf_counter() - started,
                "end_x": x_position(env),
            }


def run_arm(env, fixture, checkpoint, seed, index, demos, *, use_practice, archive):
    env.select(fixture)
    model = PPO.load(checkpoint, device="cpu")
    choose = frozen_policy(model)
    attempts = []
    practice = []
    demonstrations = []
    hotspots = DeathHotspots()
    for ordinal in range(MAX_ATTEMPTS):
        trace, outcome = full_run(env, choose, ordinal, EVAL_SEED + 10 * index + ordinal)
        attempts.append(outcome)
        if outcome["terminal"] == "complete":
            if use_practice:
                demonstrations.extend(trace)
            break
        if outcome["terminal"] != "death":
            continue
        bucket = hotspots.record(outcome["end_x"], trace)
        if not use_practice or ordinal + 1 == MAX_ATTEMPTS:
            continue
        bucket, source, window = hotspots.window(fixture.final_object_x + 30, bucket)
        demo, finish, cost = practice_section(env, source, window, choose, limit=SEARCH_LIMIT)
        record = {**asdict(cost), **asdict(window), "anchor_x": source[window.anchor].x,
                  "bucket": bucket, "demo_decisions": len(demo), "practice_completion": finish,
                  "clone_wall_s": 0.0}
        if demo:
            if finish:
                hotspots.end_witnesses[bucket] += 1
            demonstrations.extend(demo)
            started = perf_counter()
            behaviour_clone(
                model, demos[0] + [item.observation for item in demonstrations],
                demos[1] + [item.action for item in demonstrations], seed,
            )
            record["clone_wall_s"] = perf_counter() - started
        practice.append(record)
    solved = attempts[-1]["terminal"] == "complete"
    if demonstrations:
        np.savez_compressed(
            archive, observations=np.asarray([item.observation for item in demonstrations]),
            actions=np.asarray([item.action for item in demonstrations], dtype=np.uint8),
            positions=np.asarray([item.x for item in demonstrations]),
        )
    return {
        "solved": solved, "attempts_to_first_clear_capped": len(attempts),
        "attempts": attempts, "death_x_histogram_60_units": dict(hotspots.histogram),
        "practice": practice, "local_demo": archive.name if demonstrations else None,
    }


def compare(client, output, weights):
    pools, _ = scaled_fixtures()
    weights_hashes = {
        str(seed): hashlib.sha256((weights / f"topk-{seed}-bc.zip").read_bytes()).hexdigest()
        for seed in SEEDS
    }
    triggers = {row["variant"]: row["needs_trigger_support"] for row in _manifest_rows()}
    protocol = {
        "encoder": MODE, "k": 4, "attempt_cap": MAX_ATTEMPTS, "search_limit": SEARCH_LIMIT,
        "seeds": list(SEEDS), "eval_seed": EVAL_SEED, "weights_sha256": weights_hashes,
        "checkpoint_warmup_decisions": 1,
        "fixtures": {fixture.variant: fixture.digest for fixture in pools["heldout"]},
    }
    path = output / "report.json"
    report = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {
        "protocol": protocol, "complete": False, "pairs": {},
    }
    if report["protocol"] != protocol:
        raise RuntimeError("experiment inputs changed since the report was started")
    report["startpos_preflight"] = startpos_preflight(client)
    env = DrillEnv(client, MODE)
    demonstrations = ([], [])
    for fixture in pools["train"]:
        demo = collect_demo(env, fixture)
        if demo is None:
            raise RuntimeError(f"train demo did not clear {fixture.variant}")
        demonstrations[0].extend(demo[0])
        demonstrations[1].extend(demo[1])
    env.leave()
    report["train_demo_decisions"] = len(demonstrations[1])
    save_report(output, report)
    for seed in SEEDS:
        checkpoint = weights / f"topk-{seed}-bc.zip"
        for index, fixture in enumerate(pools["heldout"]):
            key = f"{seed}/{fixture.family}"
            if key in report["pairs"]:
                continue
            pair = {"trigger_dependent": triggers[fixture.variant], "variant": fixture.variant}
            # Alternate arm order so background load and temperature don't always favor one arm.
            for use_practice in (False, True)[:: -1 if (seed + index) % 2 else 1]:
                label = "practice" if use_practice else "control"
                pair[label] = run_arm(
                    env, fixture, checkpoint, seed, index, demonstrations, use_practice=use_practice,
                    archive=output / f"{seed}-{fixture.family}-{label}.npz",
                )
                env.leave()
            first = [arm["attempts"][0] for arm in (pair["control"], pair["practice"])]
            if any(first[0][field] != first[1][field] for field in ("terminal", "ticks", "end_x")):
                raise RuntimeError(f"unmatched first attempts for {key}: {first}")
            report["pairs"][key] = pair
            save_report(output, report)
            print(f"{key}: control={pair['control']['solved']}, practice={pair['practice']['solved']}", flush=True)
    report["summary"] = {}
    for label in ("control", "practice"):
        arms = [pair[label] for pair in report["pairs"].values()]
        costs = [cost for arm in arms for cost in arm["practice"]]
        report["summary"][label] = {
            "solved": sum(arm["solved"] for arm in arms),
            "mean_attempts_capped": mean(arm["attempts_to_first_clear_capped"] for arm in arms),
            "full_run_ticks": sum(attempt["ticks"] for arm in arms for attempt in arm["attempts"]),
            "full_run_wall_s": sum(attempt["wall_s"] for arm in arms for attempt in arm["attempts"]),
            "practice": {key: sum(cost[key] for cost in costs)
                         for key in ("resets", "ticks", "transitions", "wall_s", "clone_wall_s", "demo_decisions")},
            "checkpoint_parity_passed": sum(sum(cost["checkpoint_parity"]) for cost in costs),
            "checkpoint_parity_checks": sum(len(cost["checkpoint_parity"]) for cost in costs),
            "successful_sections": sum(cost["demo_decisions"] > 0 for cost in costs),
        }
    report["complete"] = True
    save_report(output, report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--weights", type=Path, default=ROOT / "build/m3-imitation")
    options = parser.parse_args()
    discovery = json.loads((ROOT / "game/2.2091/gdbot/bridge.json").read_text(encoding="utf-8"))
    if discovery["pid"] != options.pid or discovery["pipe"] != PIPE_PREFIX + str(options.pid):
        raise RuntimeError("bridge discovery must match the launcher-owned PID")
    options.output.mkdir(parents=True, exist_ok=True)
    with BridgeClient(NamedPipeTransport(discovery["pipe"])) as client:
        client.require_isolated()
        # The bridge preserves a user-selected background or dedicated override.
        client.request("set_mode", mode="dedicated")
        compare(client, options.output, options.weights)


if __name__ == "__main__":
    main()
