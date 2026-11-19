"""Compare fixed drill demonstrations plus nested online cohorts on frozen evaluation levels."""

import argparse
import hashlib
import json
import random
import sys
from collections import defaultdict, deque
from pathlib import Path
from statistics import mean

from pool import ROOT, save_json
from solve_pool import levels

sys.path[:0] = [str(ROOT / "tools/m5b"), str(ROOT / "tools/m5c")]
from expert import solution_demo  # noqa: E402
from transfer import (  # noqa: E402
    SEED, MAIN_LEVELS, MainLevel, OnlineLevel, TransferEnv, clone_checkpoint, first_runs,
    model_for, online_pool,
)
from gdbot.curriculum import save_demonstration  # noqa: E402
from gdbot.instances import discovery  # noqa: E402
from gdbot.protocol import BridgeClient, NamedPipeTransport, RemoteError  # noqa: E402


def digest(data):
    return hashlib.sha256(data.encode("ascii")).hexdigest()


def verified_solutions(pool):
    solutions = {}
    for path in sorted((pool / "solutions").glob("*.json")):
        if path.name.endswith(".progress.json"):
            continue
        report = json.loads(path.read_text(encoding="utf-8"))
        if report["verified"]:
            if report["result"]["k"] != 4:
                raise RuntimeError(f"{report['level']} does not use the four-tick policy grid")
            solutions[report["level"]] = report
    return solutions


def ordered_online(rows, solutions):
    groups = defaultdict(list)
    for row in rows:
        key = f"online:{row['id']}"
        if key in solutions:
            groups[row["difficulty"], row["length"]].append(key)
    rng = random.Random(SEED)
    strata = []
    for _, keys in sorted(groups.items()):
        rng.shuffle(keys)
        strata.append(deque(keys))
    rng.shuffle(strata)
    ordered = []
    while strata:
        ordered.extend(group.popleft() for group in strata)
        strata = [group for group in strata if group]
    return ordered


def signature(solution):
    return {"level_sha256": solution["sha256"],
            "action_sha256": digest(json.dumps(solution["result"]["actions"], separators=(",", ":")))}


def run(pool, output, slot, seeds):
    solutions = verified_solutions(pool)
    evaluation = online_pool()
    heldout = {str(f.id): digest(f.level["data"]) for f in evaluation}
    path = output / "report.json"
    if path.exists():
        report = json.loads(path.read_text(encoding="utf-8"))
    else:
        online = ordered_online(json.loads((pool / "online-train.json").read_text(encoding="utf-8")), solutions)
        drills = sorted(key for key in solutions if key.startswith("drill:"))
        if len(online) < 10 or not drills:
            raise RuntimeError(f"need at least 10 verified online solutions and one drill; found {len(online)} and {len(drills)}")
        report = {"online": online, "drills": drills, "heldout": heldout,
                  "signatures": {key: signature(solutions[key]) for key in drills + online}, "demos": {}, "runs": {}}
        save_json(path, report)
    keys = set(report["drills"] + report["online"])
    if heldout != report["heldout"] or any(key not in solutions or signature(solutions[key]) != report["signatures"][key]
                                           for key in keys):
        raise RuntimeError("the frozen training or evaluation data changed")
    if keys & {f"online:{level}" for level in heldout} or any(solutions[k]["sha256"] in heldout.values() for k in keys):
        raise RuntimeError("training and held-out data overlap")
    counts = sorted({n for n in (10, 20, 40, len(report["online"])) if n <= len(report["online"])})
    demos = output / "demos"
    demos.mkdir(parents=True, exist_ok=True)
    archives = {}
    with BridgeClient(NamedPipeTransport(discovery(slot)["pipe"])) as client:
        client.require_isolated()
        try:
            client.request("quit_level")
        except RemoteError:
            pass
        client.request("set_mode", mode="dedicated")
        try:
            env = TransferEnv(client, "route")
            for split in ("drills", "online"):
                for key, name, level_hash, spec in levels(pool, split):
                    if key not in keys:
                        continue
                    if level_hash != solutions[key]["sha256"]:
                        raise RuntimeError(f"cached level {key} changed since search")
                    archive = demos / f"{key.replace(':', '_').replace('/', '_')}.npz"
                    if key not in report["demos"] or not archive.exists():
                        actions = solutions[key]["result"]["actions"]
                        env.max_ticks = max(60_000, 4 * len(actions) + 4)
                        obs, decisions = solution_demo(env, OnlineLevel(0, name, selector=spec), actions)
                        save_demonstration(archive, obs, decisions)
                        report["demos"][key] = {"name": name, "decisions": len(decisions)}
                        save_json(path, report)
                        print(f"demo {key}: {len(decisions)} decisions", flush=True)
                    archives[key] = archive
            for generation, count in enumerate(counts, 1):
                data = [archives[key] for key in report["drills"] + report["online"][:count]]
                for seed in seeds:
                    run_id = f"m6-curve-{count}-s{seed}"
                    result = report["runs"].setdefault(run_id, {"online_demos": count, "seed": seed})
                    checkpoint = output / f"{run_id}.zip"
                    if "clone" not in result or not checkpoint.exists():
                        model = model_for(env, "topk", seed=seed)
                        result["clone"] = clone_checkpoint(model, data, checkpoint, seed=seed)
                        del model
                        save_json(path, report)
                    if "official" not in result:
                        official = [MainLevel(i, name) for i, name in enumerate(MAIN_LEVELS, 1)]
                        result["official"] = first_runs(env, official, checkpoint, f"{run_id}-official",
                                                        generation=generation, seed=seed, official=True)
                        save_json(path, report)
                    if "online" not in result:
                        result["online"] = first_runs(env, evaluation, checkpoint, f"{run_id}-online",
                                                       generation=generation, seed=seed, official=False)
                        save_json(path, report)
                    for split in ("official", "online"):
                        rows = list(result[split].values())
                        print(f"{run_id} {split}: {100 * mean(row['peak_progress'] for row in rows):.1f}% mean first run, "
                              f"{sum(row['terminal'] == 'complete' for row in rows)}/{len(rows)} clears", flush=True)
        finally:
            client.request("set_mode", mode="normal")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pool", type=Path, default=ROOT / "build/m6-scale")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--slot", type=int, required=True)
    parser.add_argument("--seeds", type=int, nargs="+", default=[SEED])
    args = parser.parse_args()
    run(args.pool, args.output or args.pool / "curve", args.slot, args.seeds)
