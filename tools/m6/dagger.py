"""Compare DAgger with whole-level expert iteration at a matched search budget."""

import argparse
import hashlib
import json
from contextlib import suppress
from pathlib import Path
from statistics import mean

from curve import ROOT, levels, save_json

from stable_baselines3 import PPO  # noqa: E402
from expert import solution_demo  # noqa: E402
from solver import K, Solver, candidates  # noqa: E402
from transfer import (  # noqa: E402
    SEED, OnlineLevel, TransferEnv, clone_checkpoint, first_runs, model_for, online_pool, study_pools,
)
from gdbot.curriculum import save_demonstration  # noqa: E402
from gdbot.instances import discovery  # noqa: E402
from gdbot.protocol import BridgeClient, NamedPipeTransport, ProtocolError, RemoteError  # noqa: E402


class StateTeacher(Solver):
    """Search a continuation from a policy state, using a released checkpoint when it reproduces the state."""

    def __init__(self, client, spec, *, budget, look):
        super().__init__(client, spec, budget=budget, look=look)
        self.replay = []

    def restore_prefix(self):
        if self.checkpoint:
            reply = self.c.request("reset", start={"kind": "checkpoint"})
        else:
            reply = self.c.request("reset", start={"kind": "zero"})
        self.ep = reply["episode"]
        actions = self.replay[self.checkpoint:] if self.checkpoint else self.replay
        if not actions:
            return reply["obs"]["players"][0]
        reply = self.run(actions)
        return None if reply["terminal"] else reply["player"]

    @staticmethod
    def matches(actual, expected):
        if actual is None or not {"x", "y", "mode"} <= actual.keys():
            return False
        continuous = ("x", "y", "vx", "vy", "rot", "speed")
        return all(abs(actual[key] - expected[key]) < 1e-3 if key in continuous else actual[key] == expected[key]
                   for key in expected if key in actual)

    def label(self, prefix, expected, budget):
        self.replay = prefix
        self.drop_checkpoints()
        self.checkpoint = 0
        # Do not put a press immediately after a checkpoint restore. Reapply at least one release.
        for index in range(len(prefix) - 1, 0, -1):
            if prefix[index] == 0:
                self.reset_zero()
                self.c.request("set_practice", enabled=True)
                if not self.run(prefix[:index])["terminal"]:
                    self.c.request("checkpoint_create")
                    self.checkpoint = index
                break
        try:
            if not self.matches(self.restore_prefix(), expected):
                self.checkpoint = 0
                if not self.matches(self.restore_prefix(), expected):
                    return None
            stop = min(self.budget, self.evals + budget)
            for candidate in candidates(self.seg, prefix[-1] if prefix else 0):
                for follow in self.followups():
                    if self.evals >= stop:
                        return None
                    if not self.matches(self.restore_prefix(), expected):
                        return None
                    self.evals += 1
                    reply = self.run(candidate + follow)
                    if reply["terminal"] == "complete" or reply["decisions"] == len(candidate) + len(follow):
                        return candidate[0]
                    if reply["decisions"] < len(candidate):
                        break
            return None
        finally:
            self.drop_checkpoints()


def collect(env, teacher, fixture, model, stride, query_budget):
    env.select(fixture)
    observation, _ = env.reset()
    trace = []
    while True:
        action = int(model.predict(observation, deterministic=True)[0].item())
        trace.append((observation, env.raw_observation["players"][0], action))
        observation, _, terminated, truncated, info = env.step(action)
        if terminated or truncated:
            break
    indexes = list(range(0, len(trace), stride))
    if info["terminal"] == "death":
        indexes = [len(trace) - 1, *(index for index in indexes if index != len(trace) - 1)]
    sampled = set(indexes)
    indexes.extend(index for index in range(len(trace)) if index not in sampled)
    rollout = [row[2] for row in trace]
    observations, actions = [], []
    for index in indexes:
        observation, player, _ = trace[index]
        action = teacher.label(rollout[:index], player, query_budget)
        if action is not None:
            observations.append(observation)
            actions.append(action)
        if teacher.evals >= teacher.budget:
            break
    env.leave()
    return observations, actions, info["terminal"]


def file_hash(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def run(client, args):
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    all_levels = {key: (name, digest, spec) for split in ("drills", "online")
                  for key, name, digest, spec in levels(args.pool, split) if key in args.train}
    if set(all_levels) != set(args.train) or len(set(args.train)) != len(args.train):
        raise ValueError("each distinct --train key must appear in the M6 training manifests")
    eval_drills = tuple(study_pools(ROOT / "build/m5-curriculum")[0]["heldout"].values())
    eval_online = tuple(online_pool())
    frozen = {"drills": {fixture.variant: fixture.digest for fixture in eval_drills},
              "online": {str(fixture.id): hashlib.sha256(fixture.level["data"].encode("ascii")).hexdigest()
                         for fixture in eval_online}}
    heldout_hashes = set(frozen["drills"].values()) | set(frozen["online"].values())
    if any(digest in heldout_hashes or key.removeprefix("online:") in frozen["online"]
           for key, (_, digest, _) in all_levels.items()):
        raise ValueError("training and frozen evaluation levels overlap")
    protocol = {"training": {key: all_levels[key][1] for key in args.train}, "train_order": args.train,
                "heldout": frozen, "anchor": file_hash(args.anchor),
                "archives": {str(path): file_hash(path) for path in args.archives},
                "rounds": args.rounds, "stride": args.stride, "query_budget": args.query_budget,
                "budget": args.budget, "look": args.look}
    path = output / "report.json"
    report = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"protocol": protocol, "runs": {}}
    report["protocol"].setdefault("rounds", 2)
    if report["protocol"] != protocol:
        raise RuntimeError("DAgger protocol changed. Use a new output directory.")
    save_json(path, report)
    env = TransferEnv(client, "route")

    def evaluate(result, checkpoint, run_id, generation):
        for split, cohort in (("drills", eval_drills), ("online", eval_online)):
            if split not in result:
                result[split] = first_runs(env, cohort, checkpoint, f"m6-dagger-{run_id}-{split}",
                                           generation=generation, official=False)
                save_json(path, report)
            scores = result[split].values()
            print(f"{run_id} {split}: {mean(row['peak_progress'] for row in scores):.2%} mean first-run progress, "
                  f"{sum(row['terminal'] == 'complete' for row in scores)}/{len(scores)} clears", flush=True)

    evaluate(report["runs"].setdefault("anchor", {}), args.anchor, "anchor", 0)
    for arm in ("expert", "dagger"):
        checkpoint = args.anchor
        archives = list(args.archives)
        for generation in range(1, args.rounds + 1):
            run_id = f"{arm}-{generation}"
            result = report["runs"].setdefault(run_id, {"training": {}})
            model = PPO.load(checkpoint, device="cpu") if arm == "dagger" else None
            for index, key in enumerate(args.train):
                if index % args.rounds != generation - 1:
                    continue
                name, _, spec = all_levels[key]
                fixture = OnlineLevel(0, name, selector=spec)
                archive = output / run_id / f"{index}.npz"
                prior = result["training"].get(key)
                if prior is None or (prior["labels"] and not archive.exists()):
                    env.max_ticks = 60_000
                    if arm == "expert":
                        archive.parent.mkdir(parents=True, exist_ok=True)
                        teacher = Solver(client, spec, budget=args.budget, look=args.look,
                                         progress=archive.with_suffix(".progress.json"))
                        solution = teacher.solve()
                        if solution:
                            obs, actions = solution_demo(env, fixture, solution["actions"], fracs=solution.get("fracs"))
                        else:
                            client.request("quit_level")
                            obs, actions = [], []
                        terminal = "complete" if solution else None
                    else:
                        cost = report["runs"][f"expert-{generation}"]["training"][key]["evals"]
                        teacher = StateTeacher(client, spec, budget=cost, look=args.look)
                        obs, actions, terminal = collect(env, teacher, fixture, model, args.stride, args.query_budget)
                    if actions:
                        save_demonstration(archive, obs, actions)
                    prior = {"labels": len(actions), "evals": teacher.evals, "teacher_ticks": teacher.ticks,
                             "terminal": terminal}
                    result["training"][key] = prior
                    save_json(path, report)
                    print(run_id, key, prior, flush=True)
                if prior["labels"]:
                    archives.append(archive)
            del model
            result["teacher_evals"] = sum(row["evals"] for row in result["training"].values())
            save_json(path, report)
            checkpoint = output / f"{run_id}.zip"
            if "clone" not in result or not checkpoint.exists():
                result["clone"] = clone_checkpoint(model_for(env, "topk", seed=SEED), archives, checkpoint)
                save_json(path, report)
            evaluate(result, checkpoint, run_id, generation)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slot", type=int, required=True)
    parser.add_argument("--pool", type=Path, default=ROOT / "build/m6-scale")
    parser.add_argument("--output", type=Path, default=ROOT / "build/m6-scale/dagger")
    parser.add_argument("--anchor", type=Path, required=True)
    parser.add_argument("--archives", type=Path, nargs="+", required=True)
    parser.add_argument("--train", nargs="+", required=True)
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument("--stride", type=int, default=12)
    parser.add_argument("--budget", type=int, default=400)
    parser.add_argument("--query-budget", type=int, default=60)
    parser.add_argument("--look", type=int, default=28)
    args = parser.parse_args()
    if min(args.rounds, args.stride, args.budget, args.query_budget, args.look) < 1:
        parser.error("rounds, stride, budgets and lookahead must be positive")
    if args.rounds > len(args.train):
        parser.error("supply at least one distinct training level per round")
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
