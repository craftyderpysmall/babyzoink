"""Run paired multi-seed PPO comparisons with resumable quarter checkpoints."""

import argparse
import hashlib
import json
import random
import statistics
from pathlib import Path
from time import perf_counter, process_time

import numpy as np
import torch
from stable_baselines3 import PPO

from baseline import (
    CPU_THREADS, MAX_ATTEMPTS, ROLLOUT, ROOT, DrillEnv, _fixture, fixtures, frozen_policy,
    model_for, save_report, score,
)
from diagnose import execute, quantize
from drills_live import attempt, targets_for
from gdbot.levels.drills import NOTES, build_drill
from gdbot.obs import PLAYER_FLAGS, ObservationEncoder
from gdbot.protocol import PIPE_PREFIX, BridgeClient, NamedPipeTransport

SEEDS = (1207, 2357, 3907)
QUARTERS = 4
DEFAULT_STEPS_PER_FIXTURE = 27_648


def scaled_fixtures():
    pools = fixtures()
    validation = []
    designs = []
    for index, family in enumerate(NOTES):
        seed = 4100 + index
        drill = build_drill(family, "heldout", seed)
        validation.append(_fixture(family, f"validation-{seed}", "validation", seed, drill.level.encode()))
        designs.append(drill)
    pools["validation"] = validation
    all_fixtures = [fixture for pool in pools.values() for fixture in pool]
    if len({fixture.digest for fixture in all_fixtures}) != len(all_fixtures):
        raise ValueError("scaled study fixture splits overlap")
    return pools, designs


def buffered_preflight(client, heldout):
    fixture = next(item for item in heldout if item.family == "yellow-orb")
    client.load_level(fixture.level)
    cutoff = 1055
    observations = []
    for edges in ([(997, 1)], [(997, 1), (998, 0), (1051, 1)]):
        arrays = []

        def capture(reply):
            if reply["tick"] == cutoff:
                arrays.append(reply["obs"])

        execute(client, edges, 1, cutoff, capture)
        if len(arrays) != 1:
            raise RuntimeError("buffered preflight did not reach the comparison tick")
        observations.append(arrays[0])
    client.request("quit_level")
    old_hold, recent_press = observations
    if "buffered" in old_hold["unsupported"] or "buffered" in recent_press["unsupported"]:
        raise RuntimeError("native bridge does not support buffered input")
    if [obs["players"][0]["buffered"] for obs in observations] != [False, True]:
        raise RuntimeError("native bridge does not distinguish the tested orb histories")
    buffered_index = 16 + PLAYER_FLAGS.index("buffered")
    for layout in ("topk", "set"):
        encoded = [ObservationEncoder(layout=layout).encode(obs, cutoff) for obs in observations]
        features = [item["player"] if layout == "set" else item for item in encoded]
        if np.flatnonzero(features[0] != features[1]).tolist() != [buffered_index]:
            raise RuntimeError(f"{layout} did not isolate pending orb input in its policy features")
    return {"fixture": fixture.level["name"], "tick": cutoff, "buffered": [False, True]}


def certify_validation(client, fixtures_and_designs):
    results = {}
    for fixture, drill in fixtures_and_designs:
        client.load_level(fixture.level)
        targets = targets_for(drill)
        witness = None
        for lead in (42, 35, 51, 28, 59):
            terminal, _, edges, _, _ = attempt(client, targets, {}, lead, 7 if drill.family == "yellow-orb" else 0)
            if terminal != "complete":
                continue
            for phase in range(4):
                outcome = execute(client, quantize(edges, 4, phase), 4, 6_000)
                if outcome["terminal"] == "complete":
                    witness = {"phase": phase, "terminal_tick": outcome["tick"]}
                    break
            if witness:
                break
        client.request("quit_level")
        results[fixture.family] = witness
        print(f"validation witness {fixture.family}: {witness}", flush=True)
    return results


def fixture_manifest(pools):
    return {
        split: [{"name": f.level["name"], "seed": f.seed, "sha256": f.digest} for f in pool]
        for split, pool in pools.items()
    }


def _checkpoint(output, key, quarter):
    return output / key / f"quarter-{quarter}.zip"


def _torch_parameter_count(model):
    return sum(weight.numel() for weight in model.policy.parameters())


def train_quarter(client, pool, order, model_seed, layout, quarter, block_steps, output, report):
    key = f"{layout}-{model_seed}"
    state = report["training"].setdefault(key, {"layout": layout, "seed": model_seed, "quarters": {}})
    quarter_key = str(quarter)
    if quarter_key in state["quarters"]:
        return
    work = output / key
    work.mkdir(exist_ok=True)
    env = DrillEnv(client, layout)
    env.select(pool[order[0]])
    previous = _checkpoint(output, key, quarter - 1)
    model = PPO.load(previous, env=env, device="cpu") if quarter > 1 else model_for(env, layout, seed=model_seed)
    model.set_random_seed(model_seed + quarter * 10_000)
    if quarter == 1:
        model.save(work / "initial.zip")
    state["parameters"] = _torch_parameter_count(model)
    before_steps = model.num_timesteps
    wall, cpu = perf_counter(), process_time()
    blocks = []
    for number, index in enumerate(order, start=1):
        fixture = pool[index]
        env.select(fixture)
        model.set_env(env, force_reset=True)
        model.learn(total_timesteps=block_steps, reset_num_timesteps=False)
        blocks.append({"family": fixture.family, "transitions": model.num_timesteps,
                       "wall_s": perf_counter() - wall, "cpu_s": process_time() - cpu})
        report["live"] = {"run": key, "quarter": quarter, "blocks_done": number, **blocks[-1]}
        save_report(output, report)
        print(f"{key} quarter {quarter} {number}/{len(order)}: {model.num_timesteps} transitions", flush=True)
    env.leave()
    if model.num_timesteps != before_steps + len(order) * block_steps:
        raise RuntimeError("PPO did not use the requested transition budget")
    checkpoint = _checkpoint(output, key, quarter)
    staged = checkpoint.with_suffix(".tmp.zip")
    model.save(staged)
    staged.replace(checkpoint)
    state["quarters"][quarter_key] = {
        "checkpoint": checkpoint.relative_to(output).as_posix(), "steps": model.num_timesteps,
        "wall_s": perf_counter() - wall, "cpu_s": process_time() - cpu, "blocks": blocks,
    }
    save_report(output, report)


def measure_checkpoint(client, pool, layout, seed, quarter, split, output, report):
    key = f"{layout}-{seed}"
    label = f"{key}/quarter-{quarter}/{split}"
    rows = report["evaluation"].get(label, [])
    if len(rows) == len(pool) and [item["variant"] for item in rows] == [item.variant for item in pool]:
        return
    report["evaluation"].pop(label, None)
    model = PPO.load(_checkpoint(output, key, quarter), device="cpu")
    score(client, pool, label, layout, frozen_policy(model), MAX_ATTEMPTS, output, report)


def metrics(rows):
    return {
        "mean_first_progress": statistics.mean(row["first_progress"] for row in rows),
        "first_run_clears": sum(row["attempts"][0]["terminal"] == "complete" for row in rows),
        "capped_clears": sum(row["solved"] for row in rows),
        "mean_capped_attempts": statistics.mean(row["attempts_to_first_clear_capped"] for row in rows),
    }


def summarize(report):
    summary = {}
    for layout in ("topk", "set"):
        summary[layout] = {}
        for quarter in range(1, 5):
            for split in ("validation", "heldout"):
                if split == "heldout" and quarter != QUARTERS:
                    continue
                results = [metrics(report["evaluation"][f"{layout}-{seed}/quarter-{quarter}/{split}"])
                           for seed in SEEDS]
                summary[layout][f"{split}-{quarter * 25}"] = {
                    name: {"mean": statistics.mean(item[name] for item in results),
                           "sd": statistics.stdev(item[name] for item in results),
                           "by_seed": [item[name] for item in results]}
                    for name in results[0]
                }
    return summary


def run(pid, output, steps_per_fixture):
    if steps_per_fixture < ROLLOUT or steps_per_fixture % ROLLOUT:
        raise ValueError(f"steps per fixture must be a positive multiple of {ROLLOUT}")
    discovery = json.loads((ROOT / "game/2.2091/gdbot/bridge.json").read_text(encoding="utf-8"))
    if discovery["pid"] != pid or discovery["pipe"] != PIPE_PREFIX + str(pid):
        raise RuntimeError("bridge discovery must match the launcher-owned process")
    output.mkdir(parents=True, exist_ok=True)
    torch.set_num_threads(CPU_THREADS)
    torch.set_num_interop_threads(1)
    pools, designs = scaled_fixtures()
    protocol = {"seeds": list(SEEDS), "quarters": QUARTERS, "k": 4, "torch_threads": CPU_THREADS,
                "per_fixture_steps": steps_per_fixture, "steps_per_model": 4 * len(pools["train"]) * steps_per_fixture,
                "validation_attempt_cap": MAX_ATTEMPTS, "heldout_optimization_steps": 0}
    manifest = fixture_manifest(pools)
    dll = ROOT / "mod/build/Release/gdbot_bridge.dll"
    bridge_hash = hashlib.sha256(dll.read_bytes()).hexdigest()
    report_path = output / "report.json"
    if report_path.exists():
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if report["protocol"] != protocol or report["fixtures"] != manifest or report["bridge_sha256"] != bridge_hash:
            raise ValueError("existing scaled run has a different configuration, fixture set, or bridge")
        if report.get("complete"):
            return
    else:
        report = {"protocol": protocol, "fixtures": manifest, "bridge_sha256": bridge_hash,
                  "training": {}, "evaluation": {}, "complete": False}
    with BridgeClient(NamedPipeTransport(discovery["pipe"])) as client:
        hello = client.require_isolated()
        if not all(hello["capabilities"].get(flag) is True for flag in ("objects", "level_string", "quit_level")):
            raise RuntimeError("scaled study requires object-enabled local drill loading")
        if any(f.build != hello["build"]["exe_sha256"] for f in pools["train"] + pools["heldout"]):
            raise RuntimeError("training and held-out tapes belong to a different executable")
        report["build"] = hello["build"]
        client.request("set_mode", mode="dedicated")
        if "buffered_preflight" not in report:
            report["buffered_preflight"] = buffered_preflight(client, pools["heldout"])
            save_report(output, report)
        if "validation_witnesses" not in report:
            report["validation_witnesses"] = certify_validation(client, zip(pools["validation"], designs, strict=True))
            save_report(output, report)
        for seed_index, seed in enumerate(SEEDS):
            rng = random.Random(seed)
            orders = [rng.sample(range(len(pools["train"])), k=len(pools["train"])) for _ in range(QUARTERS)]
            layouts = ("topk", "set") if seed_index % 2 == 0 else ("set", "topk")
            for layout in layouts:
                for quarter, order in enumerate(orders, start=1):
                    train_quarter(client, pools["train"], order, seed, layout, quarter, steps_per_fixture, output, report)
                    measure_checkpoint(client, pools["validation"], layout, seed, quarter, "validation", output, report)
        for seed in SEEDS:
            for layout in ("topk", "set"):
                measure_checkpoint(client, pools["heldout"], layout, seed, QUARTERS, "heldout", output, report)
        client.request("set_mode", mode="normal")
    report.pop("live", None)
    report["summary"] = summarize(report)
    report["complete"] = True
    save_report(output, report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--steps-per-fixture", type=int, default=DEFAULT_STEPS_PER_FIXTURE)
    options = parser.parse_args()
    run(options.pid, options.output, options.steps_per_fixture)
