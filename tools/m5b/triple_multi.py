"""Compare the existing triple-spike control with three verified training tapes."""

import argparse
import hashlib
import json
from contextlib import suppress
from pathlib import Path
from time import sleep

from triple_seeds import (
    ROOT, TAPE, BridgeClient, NamedPipeTransport, RemoteError, TransferEnv,
    archives, clone_checkpoint, discovery, frozen_policy, full_run, model_for, save_report as write_report,
)
from baseline import EVAL_SEED, MAX_ATTEMPTS, MAX_TICKS
from expert import solution_demo
from gdbot.curriculum import save_demonstration
from gdbot.levels.drills import build_drill
from gdbot.protocol import ProtocolError
from solver import K, Solver
from stable_baselines3 import PPO
from transfer import OnlineLevel, study_pools

CLONE_SEEDS = (2357, 1207, 3907)
TRAIN_SEEDS = (1112, 1122, 1132, 1142, 1152)
ARMS = ("control", "multi-tape")


def save_report(output, report):
    # A brief Windows sharing lock (for example from a concurrent status read) can block rename.
    for retry in range(6):
        try:
            write_report(output, report)
            return
        except PermissionError:
            if retry == 5:
                raise
            sleep(0.05 * 2 ** retry)


def sha256(data: str) -> str:
    return hashlib.sha256(data.encode("ascii")).hexdigest()


def archive_hash(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def collect_tapes(client, env, output, report, fixtures, budget):
    tapes = [TAPE]
    env.max_ticks = 60_000
    for fixture in fixtures:
        path = output / f"{fixture.variant}.npz"
        recorded = report["tapes"].get(fixture.variant)
        if recorded is None:
            solver = Solver(client, fixture.level, budget=budget,
                            log=lambda message: print(message, flush=True), progress=path.with_suffix(".progress.json"))
            print(f"Search {fixture.variant}", flush=True)
            solution = solver.solve()
            if solution is not None and solution["verified"] and solution["k"] == K:
                observations, actions = solution_demo(env, fixture, solution["actions"], fracs=solution.get("fracs"))
                save_demonstration(path, observations, actions)
                recorded = {"verified": True, "decisions": len(actions), "evaluations": solver.evals,
                            "archive_sha256": archive_hash(path)}
            else:
                client.request("quit_level")
                recorded = {"verified": False, "evaluations": solver.evals}
            report["tapes"][fixture.variant] = recorded
            save_report(output, report)
        print(f"{fixture.variant}: {recorded}", flush=True)
        if recorded["verified"]:
            if archive_hash(path) != recorded["archive_sha256"]:
                raise RuntimeError(f"training tape changed: {path}")
            tapes.append(path)
            if len(tapes) == 3:
                return tapes
    raise RuntimeError("fewer than three verified triple-spike training tapes within the frozen search budget")


def run(client, output, budget):
    output.mkdir(parents=True, exist_ok=True)
    holdouts = study_pools(ROOT / "build/m5-curriculum")[0]["heldout"]
    triple = holdouts["triple-spike"]
    training = []
    for seed in TRAIN_SEEDS:
        drill = build_drill("triple-spike", "train", seed)
        spec = {"kind": "level_string", "name": f"triple-spike-{drill.variant}", "data": drill.level.encode()}
        training.append(OnlineLevel(0, drill.variant, selector=spec))
    training_hashes = {f.variant: sha256(f.level["data"]) for f in training}
    holdout_hashes = {f.variant: f.digest for f in holdouts.values()}
    if len(set(training_hashes.values())) != len(training) or set(training_hashes.values()) & set(holdout_hashes.values()):
        raise RuntimeError("training variants overlap each other or the held-out levels")
    control = archives(False)
    protocol = {"training": training_hashes, "heldout": holdout_hashes, "clone_seeds": list(CLONE_SEEDS),
                "archives": {str(path.relative_to(ROOT)): archive_hash(path) for path in [*control, TAPE]},
                "evaluation_budget": budget, "attempt_cap": MAX_ATTEMPTS, "k": K}
    path = output / "report.json"
    report = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {
        "protocol": protocol, "tapes": {}, "runs": {},
    }
    if protocol != report["protocol"]:
        raise RuntimeError("study inputs changed; use a new output directory")
    save_report(output, report)
    env = TransferEnv(client, "route")
    tapes = collect_tapes(client, env, output, report, training, budget)
    report["selected_tapes"] = [str(path.relative_to(ROOT)) for path in tapes]
    policies = {}
    for seed in CLONE_SEEDS:
        for arm in ARMS:
            key = f"{seed}-{arm}"
            entry = report["runs"].setdefault(key, {"seed": seed, "arm": arm, "triple": [], "other": {}})
            checkpoint = output / f"{key}.zip"
            if "clone" not in entry or not checkpoint.exists():
                if entry["triple"] or entry["other"]:
                    raise RuntimeError(f"checkpoint missing for recorded outcomes: {checkpoint}")
                demos = control if arm == "control" else [*control, *tapes]
                entry["clone"] = clone_checkpoint(model_for(env, "topk", seed=seed), demos, checkpoint, seed=seed)
                save_report(output, report)
            policies[key] = frozen_policy(PPO.load(checkpoint, device="cpu"))

    env.max_ticks = MAX_TICKS
    env.select(triple)
    for key, choose in policies.items():
        attempts = report["runs"][key]["triple"]
        while len(attempts) < MAX_ATTEMPTS:
            ordinal = len(attempts)
            _, result = full_run(env, choose, ordinal, EVAL_SEED + ordinal)
            attempts.append(result)
            save_report(output, report)
        print(key, [(a["terminal"], round(a["peak_progress"], 4)) for a in attempts], flush=True)
    env.leave()

    for index, fixture in enumerate(f for f in holdouts.values() if f != triple):
        for key, choose in policies.items():
            scores = report["runs"][key]["other"]
            if fixture.variant not in scores:
                env.select(fixture)
                _, result = full_run(env, choose, 0, EVAL_SEED + 20 * index)
                scores[fixture.variant] = result
                save_report(output, report)
        env.leave()
        print(f"Other drills {index + 1}/{len(holdouts) - 1}: {fixture.variant}", flush=True)
    report["complete"] = True
    save_report(output, report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slot", required=True, type=int)
    parser.add_argument("--output", default=ROOT / "build/m5c-expert/triple-multi", type=Path)
    parser.add_argument("--budget", default=4500, type=int)
    args = parser.parse_args()
    if args.budget < 1:
        parser.error("budget must be positive")
    args.output = args.output.resolve()
    with BridgeClient(NamedPipeTransport(discovery(args.slot)["pipe"])) as client:
        client.require_isolated()
        with suppress(RemoteError):
            client.request("quit_level")
        client.request("set_mode", mode="dedicated")
        try:
            run(client, args.output, args.budget)
        finally:
            with suppress(ProtocolError, OSError, EOFError):
                client.request("quit_level")
            with suppress(ProtocolError, OSError, EOFError):
                client.request("set_mode", mode="normal")
