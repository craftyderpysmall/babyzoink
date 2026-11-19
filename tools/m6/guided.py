"""Measure practice evaluations and normal attempts on a fixed, unseen level cohort."""

import argparse
import hashlib
import json
from contextlib import suppress
from pathlib import Path
from time import perf_counter

from curve import ROOT, save_json

import torch  # noqa: E402
from stable_baselines3 import PPO  # noqa: E402
from dagger import file_hash  # noqa: E402
from solver import K, Solver  # noqa: E402
from solve_pool import avail_mb, guard_evaluations  # noqa: E402
from transfer import online_pool, study_pools  # noqa: E402
from gdbot.instances import discovery  # noqa: E402
from gdbot.obs import ObservationEncoder  # noqa: E402
from gdbot.protocol import BridgeClient, NamedPipeTransport, ProtocolError, RemoteError  # noqa: E402


class GuidedSolver(Solver):
    def __init__(self, *args, policy, **kwargs):
        super().__init__(*args, **kwargs)
        self.policy = policy
        self.encoder = ObservationEncoder(near_x=90, route_geometry=True)

    def choices(self, previous):
        # This generator runs only when DFS reaches its boundary. Parent iterators retain their ordering.
        patterns = list(super().choices(previous))
        scores = self.forecast()
        # Score actions against a greedy forecast. After a candidate diverges, its suffix has no
        # observed probabilities. Prefer the smallest log-odds penalty, then the longest shared prefix.
        def rank(pattern):
            for index, ((release, hold), action) in enumerate(zip(scores, pattern)):
                if action != int(hold > release):
                    return 1, abs(hold - release), -index
            return 0, 0.0, 0

        yield from sorted(patterns, key=rank)

    def forecast(self):
        start = self.restore()
        prefix = self.prefix()
        self.encoder.reset()
        # Prime the encoder with consecutive observations at the boundary, including the last release.
        skip = self.run(prefix[:-2])
        if skip["terminal"]:
            return []
        tick = start["tick"] + skip["ticks_advanced"]
        reply = start
        if 0 < len(prefix) <= 2:
            self.encoder.encode(start["obs"], tick)
        tail = prefix[-2:]
        for index, action in enumerate(tail):
            reply = self.c.step(episode=self.ep, tick=tick, action=action, k=K)
            self.ticks += reply["ticks_advanced"]
            if reply["terminal"]:
                return []
            tick = reply["tick"]
            if index + 1 < len(tail):
                self.encoder.encode(reply["obs"], tick)
        if self.seg_x and abs(reply["obs"]["players"][0]["x"] - self.seg_x[-1]) > 1e-3:
            return []
        scores = []
        for index in range(self.seg):
            observation = self.encoder.encode(reply["obs"], tick)
            tensor, _ = self.policy.obs_to_tensor(observation)
            with torch.inference_mode():
                logits = self.policy.get_distribution(tensor).distribution.logits[0].tolist()
            scores.append(logits)
            if index + 1 == self.seg:
                break
            reply = self.c.step(episode=self.ep, tick=tick, action=int(logits[1] > logits[0]), k=K)
            self.ticks += reply["ticks_advanced"]
            if reply["terminal"]:
                break
            tick = reply["tick"]
        return scores


def run(client, args):
    online = {f"online:{f.id}": (f.variant.partition("/")[2], f.level) for f in online_pool()}
    drills = {f"drill:{f.family}/{f.variant}": (f"{f.family} {f.variant}", f.level)
              for f in study_pools(ROOT / "build/m5-curriculum")[0]["heldout"].values()}
    available = {**online, **drills}
    cohort = args.levels or list(available)
    if len(set(cohort)) != len(cohort) or not set(cohort) <= available.keys():
        raise ValueError("select distinct levels from the frozen online and held-out drill cohorts")
    if len(args.checkpoints) < 2:
        raise ValueError("provide the starting policy followed by at least one learned generation")
    args.output.mkdir(parents=True, exist_ok=True)
    protocol = {"cohort": cohort, "levels": {key: hashlib.sha256(available[key][1]["data"].encode("ascii")).hexdigest()
                                               for key in cohort},
                "checkpoints": [file_hash(checkpoint) for checkpoint in args.checkpoints],
                "budget": args.budget, "look": args.look}
    path = args.output / "report.json"
    report = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"protocol": protocol, "runs": []}
    if report["protocol"] != protocol:
        raise RuntimeError("guided search protocol changed. Use a new output directory.")
    save_json(path, report)

    def check_memory(solver=None):
        if not args.min_free_mb:
            return
        available = avail_mb()
        if available < args.min_free_mb:
            if solver is not None:
                solver.save_progress()
            raise RuntimeError(f"Saved guided search progress with {available} MB available. Retry when memory frees up.")

    for generation in range(-1, len(args.checkpoints)):
        index = generation + 1
        if index == len(report["runs"]):
            report["runs"].append({"generation": generation, "levels": {}})
        results = report["runs"][index]["levels"]
        check_memory()
        policy = PPO.load(args.checkpoints[generation], device="cpu").policy if generation >= 0 else None
        for slot, key in enumerate(cohort):
            if key in results:
                continue
            check_memory()
            name, spec = available[key]
            progress = args.output / f"{generation}-{slot}.progress.json"

            def log(message):
                print(message, flush=True)
                if message.startswith("  x="):
                    check_memory(solver)

            options = {"budget": args.budget, "look": args.look, "progress": progress, "log": log}
            solver = Solver(client, spec, **options) if policy is None else GuidedSolver(client, spec, policy=policy, **options)
            if args.min_free_mb:
                guard_evaluations(solver, check_memory)  # stalled searches never print "  x=" lines
            start = perf_counter()
            print(f"generation {generation}, {key}", flush=True)
            solution = solver.solve()
            results[key] = {"name": name, "practice_attempts": solver.evals,
                            "normal_attempts": solver.verification_attempts, "verified": bool(solution),
                            "saved_x": max(solver.seg_x, default=0), "ticks": solver.ticks,
                            "wall_s": perf_counter() - start, "result": solution}
            save_json(path, report)
            client.request("quit_level")
        del policy


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slot", type=int, required=True)
    parser.add_argument("--checkpoints", nargs="+", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "build/m6-scale/guided")
    parser.add_argument("--levels", nargs="+")
    parser.add_argument("--budget", type=int, default=400)
    parser.add_argument("--look", type=int, default=28)
    parser.add_argument("--min-free-mb", type=int, default=0)
    args = parser.parse_args()
    if min(args.budget, args.look) < 1 or args.min_free_mb < 0:
        parser.error("budget and lookahead must be positive and available memory threshold non-negative")
    with BridgeClient(NamedPipeTransport(discovery(args.slot)["pipe"])) as client:
        client.require_isolated()
        try:
            client.request("quit_level")
        except RemoteError:
            pass
        client.request("set_mode", mode="dedicated")
        try:
            run(client, args)
        finally:
            with suppress(ProtocolError, OSError, EOFError):
                client.request("quit_level")
            with suppress(ProtocolError, OSError, EOFError):
                client.request("set_mode", mode="normal")
