"""Run the resumable M5 behavior-cloning and practice curriculum on one bridge."""

import argparse
import hashlib
import json
import sys
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean
from tempfile import TemporaryDirectory
from time import perf_counter, process_time

TOOLS = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(TOOLS / "m3"), str(TOOLS / "m4")]

import numpy as np
import torch
from stable_baselines3 import PPO

from baseline import EVAL_SEED, MAX_ATTEMPTS, ROOT, DrillEnv, _fixture, fixtures, frozen_policy, model_for, save_report
from diagnose import quantize
from imitation import BC_BATCH, BC_EPOCHS, BC_LR, collect_demo
from practice import SEARCH_LIMIT, full_run
from scale import SEEDS, scaled_fixtures
from gdbot.curriculum import DeathHotspots, demo_batches, demo_counts, practice_section, save_demonstration
from gdbot.env import GDEnv
from gdbot.levels.drills import M5_NOTES
from gdbot.protocol import PIPE_PREFIX, BridgeClient, NamedPipeTransport
from gdbot.replay import Tape
from gdbot.sections import EnvTelemetry, TelemetryWriter, attempt_meta

DRILLS = ROOT / "levels/drills/m5"
K = 4
MAIN_LEVELS = ("Stereo Madness", "Back on Track", "Polargeist", "Dry Out", "Base After Base")


@dataclass(frozen=True)
class MainLevel:
    id: int
    variant: str
    revision: str = "main"

    @property
    def level(self):
        return {"kind": "main", "id": self.id}


class StudyEnv(DrillEnv):
    """Use the bridge's native progress for official levels with unknown length."""

    def __init__(self, client, layout):
        super().__init__(client, layout)
        self.telemetry = None
        self.pending_trial = None

    @contextmanager
    def recording(self, run):
        writer = TelemetryWriter(run)
        final_path = writer.path
        writer.path = final_path.with_suffix(".pending")
        writer.path.write_text("", encoding="utf-8")
        self.telemetry = EnvTelemetry(self, writer)
        try:
            yield
            self.stop_trial()
            writer.path.replace(final_path)
        finally:
            self.telemetry = None
            self.pending_trial = None

    def plan_trial(self, generation, seed, attempt, *, zero_shot=False, practice=False):
        if self.telemetry is None:
            return
        self.stop_trial()
        if isinstance(self.fixture, MainLevel):
            level = f"official:{self.fixture.id}"
        else:
            level = f"drill:{self.fixture.family}/{self.fixture.variant}"
        self.pending_trial = {"level": level, "generation": generation, "seed": seed,
                              "attempt": attempt, "zero_shot": zero_shot, "practice": practice}

    def stop_trial(self):
        if self.telemetry is not None:
            self.telemetry.stopped()

    def reset(self, *, seed=None, options=None):
        self.stop_trial()
        if isinstance(self.fixture, MainLevel):
            result = GDEnv.reset(self, seed=seed, options=options)
        else:
            result = super().reset(seed=seed, options=options)
        if self.pending_trial is not None:
            start = (options or {}).get("start", {}).get("kind", "zero")
            self.telemetry.started(attempt_meta(**self.pending_trial, start=start))
            self.pending_trial = None
        return result

    def step(self, action):
        if isinstance(self.fixture, MainLevel):
            result = GDEnv.step(self, action)
            if result[-1]["terminal"] == "complete":
                result[-1]["progress"] = 1.0
        else:
            result = super().step(action)
        if self.telemetry is not None:
            self.telemetry.stepped(result[-1], result[2], result[3])
        return result


def manifest(path):
    entry = None
    for line in path.read_text(encoding="utf-8").splitlines()[2:]:
        if line.startswith("  - "):
            if entry is not None:
                yield entry
            entry = {}
        key, value = line[4:].split(": ", 1)
        entry[key] = json.loads(value)
    if entry is not None:
        yield entry


def ready_fixtures(verification):
    pools = {split: {} for split in ("train", "validation", "heldout")}
    tapes = {}
    for entry in manifest(DRILLS / "index.yaml"):
        audit_key = f"{entry['family']}/{entry['variant']}"
        if not entry["training_ready"] or not verification.get(audit_key, {}).get("ready"):
            raise RuntimeError(f"verify {entry['family']}/{entry['variant']} live before starting the study")
        data = (DRILLS / entry["path"]).read_text(encoding="ascii")
        tape = Tape.load(DRILLS / entry["tape"])
        fixture = _fixture(
            entry["family"], entry["variant"], entry["split"], entry["seed"], data,
            revision=tape.level_revision, build=tape.build_hash,
        )
        if fixture.digest != entry["sha256"] or tape.level != fixture.level or tape.terminal != "complete":
            raise RuntimeError(f"unverified fixture or tape for {fixture.family}/{fixture.variant}")
        pools[fixture.split][fixture.family] = fixture
        if fixture.split == "train":
            tapes[fixture] = tape
    if any(set(split) != set(M5_NOTES) for split in pools.values()):
        raise RuntimeError("M5 splits must each contain all frozen families")
    return pools, tapes


def clone(model, archives, seed, *, epochs=BC_EPOCHS):
    counts = demo_counts(archives)
    if not counts.sum():
        raise ValueError("behavior cloning requires at least one demonstrated decision")
    weights = torch.as_tensor(counts.sum() / (2 * np.maximum(counts, 1)), dtype=torch.float32)
    loss_fn = torch.nn.CrossEntropyLoss(weight=weights)
    optimizer = torch.optim.Adam(model.policy.parameters(), lr=BC_LR)
    rng = np.random.default_rng(seed)
    for _ in range(epochs):
        for observations, actions in demo_batches(archives, rng, BC_BATCH):
            logits = model.policy.get_distribution(torch.from_numpy(observations)).distribution.logits
            loss = loss_fn(logits, torch.as_tensor(actions, dtype=torch.long))
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
    return int(counts.sum())


def tape_demo(env, fixture, tape):
    pressed = dict(quantize(tape.edges, K, 0))
    env.select(fixture)
    observation, _ = env.reset()
    observations, actions = [], []
    action = 0
    while True:
        action = pressed.get(env.tick + 1, action)
        observations.append(observation)
        actions.append(action)
        observation, _, terminated, truncated, info = env.step(action)
        if terminated or truncated:
            if info["terminal"] != "complete":
                raise RuntimeError(f"verified tape failed on the k={K} grid for {fixture.variant}")
            return observations, actions


def archive_trace(path, trace):
    save_demonstration(path, [item.observation for item in trace], [item.action for item in trace])


def attempts(env, fixture, checkpoint, archives, directory, seed, index, cap, *, practice, generation=0,
             unseen=False):
    """Adapt one in-memory model. Callers decide whether train demonstrations persist."""
    model = PPO.load(checkpoint, device="cpu")
    choose = frozen_policy(model)
    env.select(fixture)
    hotspots = DeathHotspots()
    outcomes, practice_log, added = [], [], []
    trial = 0

    def start_practice_trial():
        nonlocal trial
        trial += 1
        env.plan_trial(generation, seed, trial, practice=True)

    for ordinal in range(cap):
        cpu = process_time()
        env.plan_trial(generation, seed, ordinal + 1, zero_shot=unseen and ordinal == 0)
        trace, result = full_run(env, choose, ordinal, EVAL_SEED + 20 * index + ordinal)
        result["cpu_s"] = process_time() - cpu
        outcomes.append(result)
        if result["terminal"] == "complete":
            if practice:
                file = directory / f"clean-{ordinal}.npz"
                archive_trace(file, trace)
                added.append(file)
            break
        if result["terminal"] != "death" or not practice or ordinal + 1 == cap:
            continue
        bucket = hotspots.record(result["end_x"], trace)
        if isinstance(fixture, MainLevel):
            finish = result["end_x"] / result["peak_progress"] if result["peak_progress"] else float("inf")
        else:
            finish = fixture.final_object_x + 30
        bucket, source, window = hotspots.window(finish, bucket)
        cpu = process_time()
        try:
            demo, complete, cost = practice_section(
                env, source, window, choose, limit=SEARCH_LIMIT, start_trial=start_practice_trial,
            )
        finally:
            env.stop_trial()
        row = {**asdict(cost), "demo_decisions": len(demo), "section_completed_level": complete,
               "search_cpu_s": process_time() - cpu, "clone_wall_s": 0.0, "clone_cpu_s": 0.0}
        if demo:
            if complete:
                hotspots.end_witnesses[bucket] += 1
            file = directory / f"section-{ordinal}.npz"
            archive_trace(file, demo)
            added.append(file)
            wall, cpu = perf_counter(), process_time()
            clone(model, [*archives, *added], seed)
            row.update(clone_wall_s=perf_counter() - wall, clone_cpu_s=process_time() - cpu)
        practice_log.append(row)
    env.leave()
    return {
        "solved": outcomes[-1]["terminal"] == "complete", "first_progress": outcomes[0]["peak_progress"],
        "attempts_capped": len(outcomes), "attempts": outcomes, "practice": practice_log,
    }, added


def score(env, pool, checkpoint, archives, output, seed, *, cap, practice, generation, unseen=False):
    rows = {}
    for index, fixture in enumerate(pool):
        # Each test starts with the frozen checkpoint. No episode from this directory
        # is an input to future fixtures, model selection, or the next generation.
        env.max_ticks = 40_000 if isinstance(fixture, MainLevel) else 6_000
        with TemporaryDirectory(dir=output) as temporary:
            rows[fixture.variant], _ = attempts(
                env, fixture, checkpoint, archives, Path(temporary), seed, index, cap, practice=practice,
                generation=generation, unseen=unseen,
            )
    return rows


def metrics(rows):
    attempts = [attempt for row in rows.values() for attempt in row["attempts"]]
    practice = [entry for row in rows.values() for entry in row["practice"]]
    return {
        "clears": sum(row["solved"] for row in rows.values()),
        "mean_attempts_capped": mean(row["attempts_capped"] for row in rows.values()),
        "mean_first_progress": mean(row["first_progress"] for row in rows.values()),
        "full_run_ticks": sum(attempt["ticks"] for attempt in attempts),
        "full_run_wall_s": sum(attempt["wall_s"] for attempt in attempts),
        "full_run_cpu_s": sum(attempt["cpu_s"] for attempt in attempts),
        "practice": {key: sum(entry[key] for entry in practice) for key in (
            "ticks", "resets", "wall_s", "search_cpu_s", "clone_wall_s", "clone_cpu_s", "demo_decisions",
        )},
    }


def trusted_archive(env, output, fixture, tape=None):
    path = output / "trusted" / f"{fixture.family}-{fixture.variant}-{fixture.digest}.npz"
    if not path.exists():
        demo = collect_demo(env, fixture) if tape is None else tape_demo(env, fixture, tape)
        if demo is None:
            raise RuntimeError(f"trusted demonstration failed for {fixture.variant}")
        save_demonstration(path, *demo)
    env.leave()
    return path


def generation(env, output, report, number, seed, families, pools, tapes, base):
    key = f"{number}/{seed}"
    old = [report["runs"][f"{index}/{seed}"] for index in range(1, number)]
    unlocked = old[-1]["next_family"] if old else 0
    root = output / f"g{number:02d}-s{seed}"
    root.mkdir(exist_ok=True)
    checkpoint = root / "policy.zip"
    archives = [*base, *(output / relative for row in old for relative in row["earned_archives"])]
    for family in families[:unlocked + 1]:
        fixture = pools["train"][family]
        archives.append(trusted_archive(env, output, fixture, tapes[fixture]))
    model = model_for(env, "topk", seed=seed)
    wall, cpu = perf_counter(), process_time()
    samples = clone(model, archives, seed)
    clone_cost = {"wall_s": perf_counter() - wall, "cpu_s": process_time() - cpu}
    model.save(checkpoint)
    del model
    with env.recording(f"m5-{output.name}-g{number}-s{seed}"):
        validation, heldout = (
            score(env, pools[split].values(), checkpoint, archives, output, seed, cap=MAX_ATTEMPTS,
                  practice=split == "heldout", generation=number, unseen=split == "heldout")
            for split in ("validation", "heldout")
        )
        training, added = None, []
        if unlocked < len(families):
            training, added = attempts(
                env, pools["train"][families[unlocked]], checkpoint, archives, root / "train",
                seed, unlocked, MAX_ATTEMPTS, practice=True, generation=number,
            )
    report["runs"][key] = {
        "checkpoint": checkpoint.relative_to(output).as_posix(),
        "cloned_samples": samples, "clone_cost": clone_cost,
        "cloning_archives": [path.relative_to(output).as_posix() for path in archives],
        "earned_archives": [path.relative_to(output).as_posix() for path in added],
        "validation": validation, "heldout": heldout, "training": training,
        "validation_summary": metrics(validation), "heldout_summary": metrics(heldout),
        "next_family": unlocked + int(training is not None and training["solved"]),
    }
    save_report(output, report)
    print(key, report["runs"][key]["heldout_summary"], flush=True)


def study_pools(output):
    verification = json.loads((output / "verification.json").read_text(encoding="utf-8"))
    candidates, tapes = ready_fixtures(verification)
    legacy, _ = scaled_fixtures()
    # Preserve M3's frozen held-out split, including triple spike, before the new split.
    pools = {
        split: {**{f.family: f for f in legacy[split]}, **candidates[split]}
        for split in ("validation", "heldout")
    }
    pools["train"] = candidates["train"]
    return pools, tapes


def run(client, output, count):
    pools, tapes = study_pools(output)
    output.mkdir(parents=True, exist_ok=True)
    report_path = output / "report.json"
    protocol = {
        "k": K, "seeds": list(SEEDS), "full_attempt_cap": MAX_ATTEMPTS, "main_cap": 10,
        "bc_epochs": BC_EPOCHS, "bc_batch": BC_BATCH, "bc_lr": BC_LR, "search_limit": SEARCH_LIMIT,
        "bridge_sha256": hashlib.sha256((ROOT / "mod/build/Release/gdbot_bridge.dll").read_bytes()).hexdigest(),
        "family_order": list(M5_NOTES),
        "fixtures": {split: {key: item.digest for key, item in pool.items()} for split, pool in pools.items()},
        "train_tapes": {f.variant: hashlib.sha256(json.dumps(asdict(t), sort_keys=True).encode()).hexdigest()
                        for f, t in tapes.items()},
    }
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {
        "protocol": protocol, "runs": {}, "official": {}, "complete": False,
    }
    if report["protocol"] != protocol:
        raise RuntimeError("M5 study inputs differ from the frozen report")
    if str(count) not in report["official"]:
        report["complete"] = False
        save_report(output, report)
    env = StudyEnv(client, "topk")
    base = [trusted_archive(env, output, fixture) for fixture in fixtures()["train"]]
    for number in range(1, count + 1):
        for seed in SEEDS:
            if f"{number}/{seed}" not in report["runs"]:
                generation(env, output, report, number, seed, list(M5_NOTES), pools, tapes, base)
    if str(count) not in report["official"]:
        def validation_rank(seed):
            summary = report["runs"][f"{count}/{seed}"]["validation_summary"]
            return summary["clears"], summary["mean_first_progress"], -seed
        seed = max(SEEDS, key=validation_rank)
        row = report["runs"][f"{count}/{seed}"]
        archives = [output / path for path in row["cloning_archives"]]
        main = [MainLevel(index, name) for index, name in enumerate(MAIN_LEVELS, 1)]
        with env.recording(f"m5-{output.name}-official-g{count}-s{seed}"):
            results = score(
                env, main, output / row["checkpoint"], archives, output, seed,
                cap=10, practice=True, generation=count, unseen=True,
            )
        report["official"][str(count)] = {"validation_selected_seed": seed, "levels": results}
    report["complete"] = True
    save_report(output, report)


def backfill_telemetry(client, output):
    """Re-run frozen first attempts from the stored models without modifying the study report."""
    path = output / "telemetry-backfill.json"
    progress = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    report = json.loads((output / "report.json").read_text(encoding="utf-8"))
    if not report["complete"]:
        raise RuntimeError("complete the study before backfilling telemetry")
    pools, _ = study_pools(output)
    env = StudyEnv(client, "topk")

    def check(first, expected, label):
        if any(first[key] != expected[key] for key in ("terminal", "ticks", "end_x")):
            raise RuntimeError(f"frozen first attempt diverged for {label}: {first} vs {expected}")

    def registered(key):
        staging = path.with_suffix(".tmp")
        staging.write_text(json.dumps(progress, indent=2) + "\n", encoding="utf-8")
        staging.replace(path)
        print(f"Telemetry recorded for {key}", flush=True)

    newest = max(map(int, report["official"]))
    official = report["official"][str(newest)]
    if "official" not in progress:
        seed = official["validation_selected_seed"]
        row = report["runs"][f"{newest}/{seed}"]
        archives = [output / name for name in row["cloning_archives"]]
        main = [MainLevel(index, name) for index, name in enumerate(MAIN_LEVELS, 1)]
        with env.recording(f"m5-backfill-official-g{newest}-s{seed}"):
            results = score(
                env, main, output / row["checkpoint"], archives, output, seed,
                cap=10, practice=True, generation=newest, unseen=True,
            )
            for level in main:
                check(results[level.variant]["attempts"][0], official["levels"][level.variant]["attempts"][0],
                      level.variant)
        progress["official"] = {"levels": len(main), "metrics": metrics(results)}
        registered("official")

    env.max_ticks = 6_000
    for key, row in report["runs"].items():
        if key in progress:
            continue
        generation, seed = map(int, key.split("/"))
        model = PPO.load(output / row["checkpoint"], device="cpu")
        choose = frozen_policy(model)
        with env.recording(f"m5-backfill-g{generation}-s{seed}"):
            for index, fixture in enumerate(pools["heldout"].values()):
                env.select(fixture)
                env.plan_trial(generation, seed, 1, zero_shot=True)
                _, result = full_run(env, choose, 0, EVAL_SEED + 20 * index)
                check(result, row["heldout"][fixture.variant]["attempts"][0], fixture.variant)
                env.leave()
        del choose, model
        progress[key] = {"first_attempts": len(row["heldout"])}
        registered(key)


def connect(pid):
    discovery = json.loads((ROOT / "game/2.2091/gdbot/bridge.json").read_text(encoding="utf-8"))
    if discovery["pid"] != pid or discovery["pipe"] != PIPE_PREFIX + str(pid):
        raise RuntimeError("bridge discovery must match the launcher-owned PID")
    return BridgeClient(NamedPipeTransport(discovery["pipe"]))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--generations", type=int, default=3, choices=range(3, 21))
    parser.add_argument("--backfill-telemetry", action="store_true")
    options = parser.parse_args()
    with connect(options.pid) as client:
        client.require_isolated()
        client.request("set_mode", mode="dedicated")
        if options.backfill_telemetry:
            backfill_telemetry(client, options.output)
        else:
            run(client, options.output, options.generations)
