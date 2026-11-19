"""Compare collision features on frozen validation, then learn from official-level practice."""

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter, process_time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "m5"))

from stable_baselines3 import PPO

from study import (
    EVAL_SEED, MAIN_LEVELS, ROOT, MainLevel, StudyEnv, attempts, clone, fixtures, frozen_policy,
    full_run, metrics, model_for, save_report, score, study_pools, trusted_archive,
)
from gdbot.instances import discovery
from gdbot.levels.online import FROZEN_M5B_ONLINE_IDS as ONLINE_IDS, level_spec
from gdbot.obs import ObservationEncoder
from gdbot.protocol import PIPE_PREFIX, BridgeClient, NamedPipeTransport

SEED = 2357
BASE = ROOT / "build/m5-curriculum"


@dataclass(frozen=True)
class OnlineLevel(MainLevel):
    selector: dict | None = None

    @property
    def level(self):
        return self.selector


class TransferEnv(StudyEnv):
    def __init__(self, client, arm):
        super().__init__(client, "topk")
        if arm == "route":
            self.encoder = ObservationEncoder(near_x=90, route_geometry=True)
            self.observation_space = self.encoder.space

    def plan_trial(self, *args, **kwargs):
        super().plan_trial(*args, **kwargs)
        if self.pending_trial is not None and isinstance(self.fixture, OnlineLevel):
            self.pending_trial["level"] = f"online:{self.fixture.id}"


def online_pool():
    pool = []
    for identifier in ONLINE_IDS:
        path = ROOT / "levels/online" / f"{identifier}.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        meta = record
        if (
            meta["id"] != identifier or meta["demon"] or meta["platformer"]
            or meta["difficulty"] not in ("easy", "normal", "hard") or meta["stars"] not in range(2, 6)
        ):
            raise RuntimeError(f"held-out level metadata changed for {identifier}")
        pool.append(OnlineLevel(identifier, f"{identifier}/{meta['name']}", selector=level_spec(record)))
    return pool


def clone_checkpoint(model, archives, checkpoint, *, seed=SEED):
    start, cpu = perf_counter(), process_time()
    samples = clone(model, archives, seed)
    model.save(checkpoint)
    return {"samples": samples, "wall_s": perf_counter() - start, "cpu_s": process_time() - cpu}


def first_runs(env, pool, checkpoint, run, *, generation, official, seed=SEED):
    model = PPO.load(checkpoint, device="cpu")
    choose = frozen_policy(model)
    env.max_ticks = 40_000 if official else 6_000
    scores = {}
    with env.recording(run):
        for index, fixture in enumerate(pool):
            env.select(fixture)
            env.plan_trial(generation, seed, 1, zero_shot=True)
            _, first = full_run(env, choose, 0, EVAL_SEED + 20 * index)
            scores[fixture.variant] = first
            env.leave()
    return scores


def run(client, output):
    output.mkdir(parents=True, exist_ok=True)
    pools, tapes = study_pools(BASE)
    online = online_pool()
    official = [MainLevel(i, name) for i, name in enumerate(MAIN_LEVELS, 1)]
    legacy_training = fixtures()["train"]
    protocol = {
        "seed": SEED, "k": 4, "official_train_cap": 10, "online_cap": 3,
        "online_sha256": {str(f.id): hashlib.sha256(f.level["data"].encode("ascii")).hexdigest() for f in online},
        "drills_sha256": {split: {name: f.digest for name, f in rows.items()} for split, rows in pools.items()},
        "original_train_sha256": {f.family: f.digest for f in legacy_training},
        "bridge_sha256": hashlib.sha256((ROOT / "mod/build/Release/gdbot_bridge.dll").read_bytes()).hexdigest(),
    }
    path = output / "report.json"
    report = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {
        "protocol": protocol, "arms": {}, "training": {}, "online": {}, "complete": False,
    }
    if report["protocol"] != protocol:
        raise RuntimeError("the frozen comparison inputs changed")
    for arm in ("base", "route"):
        if arm in report["arms"]:
            continue
        env = TransferEnv(client, arm)
        arm_root = output / arm
        arm_root.mkdir(exist_ok=True)
        archives = [trusted_archive(env, arm_root, f) for f in legacy_training]
        archives.extend(trusted_archive(env, arm_root, f, tapes[f]) for f in pools["train"].values())
        checkpoint = arm_root / "clone.zip"
        model = model_for(env, "topk", seed=SEED)
        cost = clone_checkpoint(model, archives, checkpoint)
        del model
        with env.recording(f"m5b-validation-{arm}"):
            validation = score(
                env, pools["validation"].values(), checkpoint, archives, output, SEED,
                cap=3, practice=False, generation=4,
            )
        report["arms"][arm] = {
            "checkpoint": checkpoint.relative_to(output).as_posix(),
            "archives": [p.relative_to(output).as_posix() for p in archives],
            "clone_cost": cost, "validation": validation, "summary": metrics(validation),
        }
        save_report(output, report)
        print(arm, report["arms"][arm]["summary"], flush=True)

    def rank(arm):
        row = report["arms"][arm]["summary"]
        return row["clears"], row["mean_first_progress"], arm == "base"

    selected = max(report["arms"], key=rank)
    report["selected_arm"] = selected
    env = TransferEnv(client, selected)
    starting = output / report["arms"][selected]["checkpoint"]
    archives = [output / p for p in report["arms"][selected]["archives"]]
    if "official_zero_shot" not in report:
        report["official_zero_shot"] = first_runs(
            env, official, starting, "m5b-official-opening", generation=4, official=True,
        )
        save_report(output, report)
        print("Official zero-shot", {name: result["peak_progress"]
              for name, result in report["official_zero_shot"].items()}, flush=True)

    trained = starting
    env.max_ticks = 40_000
    for index, fixture in enumerate(official):
        if fixture.variant not in report["training"]:
            with env.recording(f"m5b-official-practice-{fixture.id}"):
                row, added = attempts(
                    env, fixture, trained, archives, output / "self-imitation" / str(fixture.id),
                    SEED, index, 10, practice=True, generation=4,
                )
            next_checkpoint, cost = trained, None
            if added:
                model = PPO.load(trained, device="cpu")
                next_checkpoint = output / f"official-after-{fixture.id}.zip"
                cost = clone_checkpoint(model, [*archives, *added], next_checkpoint)
                del model
            report["training"][fixture.variant] = {
                **row, "archive": [p.relative_to(output).as_posix() for p in added],
                "checkpoint": next_checkpoint.relative_to(output).as_posix(), "clone_cost": cost,
            }
            save_report(output, report)
            print(fixture.variant, row["solved"], f"best {max(x['peak_progress'] for x in row['attempts']):.2%}",
                  flush=True)
        previous = report["training"][fixture.variant]
        trained = output / previous["checkpoint"]
        archives.extend(output / p for p in previous["archive"])
    if "drill_regression" not in report:
        report["drill_regression"] = first_runs(
            env, pools["heldout"].values(), trained, "m5b-drill-regression", generation=5, official=False,
        )
        save_report(output, report)
    env.max_ticks = 40_000
    for index, fixture in enumerate(online):
        if fixture.variant in report["online"]:
            continue
        with TemporaryDirectory(dir=output) as directory, env.recording(f"m5b-heldout-{fixture.id}"):
            row, _ = attempts(
                env, fixture, trained, archives, Path(directory), SEED, index, 3,
                practice=True, generation=5, unseen=True,
            )
        report["online"][fixture.variant] = row
        save_report(output, report)
        print(fixture.variant, row["solved"], f"first {row['first_progress']:.2%}", flush=True)
    report["online_summary"] = metrics(report["online"])
    report["complete"] = True
    save_report(output, report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slot", type=int, required=True)
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    options = parser.parse_args()
    bridge = discovery(options.slot)
    if bridge["instance"] != options.slot or bridge["pid"] != options.pid or bridge["pipe"] != PIPE_PREFIX + str(options.pid):
        raise RuntimeError("slot discovery did not match the launcher-owned game")
    with BridgeClient(NamedPipeTransport(bridge["pipe"])) as client:
        client.require_isolated()
        client.request("set_mode", mode="dedicated")
        run(client, options.output)
