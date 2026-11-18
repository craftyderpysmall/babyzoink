"""Train and score the M3 CPU baselines without updating on held-out drills."""

import argparse
import hashlib
import json
import random
import sys
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter, process_time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import torch
from stable_baselines3 import PPO

from gdbot.baselines import TimingHeuristic
from gdbot.env import GDEnv
from gdbot.levels.drills import build_drill
from gdbot.levels.levelstring import LevelString
from gdbot.model import PooledSetExtractor, TopKExtractor
from gdbot.obs import ObservationEncoder
from gdbot.protocol import PIPE_PREFIX, BridgeClient, NamedPipeTransport
from gdbot.replay import Tape

FIXTURES = ROOT / "levels/drills"
TRAIN_SEED = 1207
EVAL_SEED = 8210
MAX_ATTEMPTS = 3
MAX_TICKS = 6_000
CPU_THREADS = 2
ROLLOUT = 256
TRAIN_ROUNDS = 2
STEPS_PER_BLOCK = 8_192
WALL_LIMIT_PER_ENCODER_SECONDS = 50 * 60


@dataclass(frozen=True)
class Fixture:
    family: str
    variant: str
    split: str
    seed: int
    data: str
    digest: str
    final_object_x: float
    revision: str | None = None
    build: str | None = None

    @property
    def level(self):
        return {"kind": "level_string", "name": f"{self.family}-{self.variant}", "data": self.data}


def _fixture(family, variant, split, seed, data, *, revision=None, build=None):
    objects = LevelString.decode(data).objects
    return Fixture(
        family, variant, split, seed, data, hashlib.sha256(data.encode("ascii")).hexdigest(),
        max(float(obj["2"]) for obj in objects), revision, build,
    )


def _manifest_rows():
    lines = (FIXTURES / "index.yaml").read_text(encoding="utf-8").splitlines()
    # The generator writes a YAML list with JSON-compatible scalar values.
    entry = None
    for line in lines[2:]:
        if line.startswith("  - "):
            if entry is not None:
                yield entry
            entry = {}
        key, value = line[4:].split(": ", 1)
        entry[key] = json.loads(value)
    if entry:
        yield entry


def fixtures():
    pools = {"train": [], "heldout": [], "validation": []}
    for entry in _manifest_rows():
        if not entry["training_ready"]:
            continue
        if not entry["progress_ok_dx"]:
            raise ValueError("forward progress was not verified for this fixture")
        tape = Tape.load(FIXTURES / entry["tape"])
        data = (FIXTURES / entry["path"]).read_bytes().decode("ascii")
        fixture = _fixture(
            entry["family"], entry["variant"], entry["split"], entry["seed"], data,
            revision=tape.level_revision, build=tape.build_hash,
        )
        if (
            fixture.digest != entry["sha256"] or tape.terminal != "complete"
            or tape.settings.get("drill_sha256") != fixture.digest or tape.level != fixture.level
        ):
            raise ValueError(f"stale fixture or tape for {fixture.variant}")
        pools[fixture.split].append(fixture)

    validation_specs = (("double-spike", 3101), ("yellow-orb", 3105), ("moving-geometry", 3108))
    for family, seed in validation_specs:
        drill = build_drill(family, "train", seed)
        pools["validation"].append(_fixture(family, f"validation-{seed}", "validation", seed, drill.level.encode()))
    digests = [fixture.digest for pool in pools.values() for fixture in pool]
    if len(set(digests)) != len(digests) or not all(pools.values()):
        raise ValueError("fixture splits must be non-empty and disjoint")
    return pools


class DrillEnv(GDEnv):
    """Use forward displacement for reward on the tick-driven bridge."""

    def __init__(self, client, layout):
        super().__init__(client, k=4, encoder=ObservationEncoder(layout=layout), max_ticks=MAX_TICKS)
        self.fixture = None

    def select(self, fixture):
        if self.fixture == fixture:
            return
        if self.fixture is not None:
            self.client.request("quit_level")
        self.fixture = fixture
        self.level = fixture.level
        self._loaded = None
        self._ready = False

    def reset(self, *, seed=None, options=None):
        if self.fixture is None:
            raise RuntimeError("choose a drill before resetting")
        encoded, info = super().reset(seed=seed, options=options)
        if self.fixture.revision is not None and info["level_revision"] != self.fixture.revision:
            raise RuntimeError(f"native revision changed for {self.fixture.variant}")
        self._start_x = self.raw_observation["players"][0]["x"]
        self._length = self.fixture.final_object_x + 30 - self._start_x
        self._forward_progress = 0.0
        info["progress"] = 0.0
        return encoded, info

    def step(self, action):
        encoded, _, terminated, truncated, info = super().step(action)
        player = self.raw_observation["players"][0]
        progress = min(1.0, max(0.0, (player["x"] - self._start_x) / self._length))
        if info["terminal"] == "complete":
            progress = 1.0
        reward = progress - self._forward_progress
        if info["terminal"] == "death":
            reward -= self.death_penalty
        elif info["terminal"] == "complete":
            reward += self.completion_bonus
        self._forward_progress = progress
        info["progress"] = progress
        return encoded, reward, terminated, truncated, info

    def leave(self):
        if self.fixture is not None:
            self.client.request("quit_level")
            self.fixture = None


def save_report(output, report):
    path = output / "report.json"
    staging = output / "report.tmp"
    staging.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    staging.replace(path)


def model_for(env, layout):
    is_set = layout == "set"
    return PPO(
        "MultiInputPolicy" if is_set else "MlpPolicy", env, device="cpu", seed=TRAIN_SEED,
        learning_rate=3e-4, n_steps=ROLLOUT, batch_size=64, n_epochs=4, gamma=0.997,
        policy_kwargs={"features_extractor_class": PooledSetExtractor if is_set else TopKExtractor},
    )


def train(client, pool, order, layout, output, report):
    env = DrillEnv(client, layout)
    env.select(pool[order[0][0]])
    model = model_for(env, layout)
    work = output / layout
    work.mkdir(exist_ok=True)
    model.save(work / "initial.zip")
    results = {"blocks": [], "checkpoints": [str((work / "initial.zip").relative_to(output))]}
    report["training"][layout] = results
    wall_started, cpu_started = perf_counter(), process_time()
    for number, indices in enumerate(order, start=1):
        for index in indices:
            if perf_counter() - wall_started >= WALL_LIMIT_PER_ENCODER_SECONDS:
                raise TimeoutError(f"{layout} hit its matched {WALL_LIMIT_PER_ENCODER_SECONDS}-second wall limit")
            fixture = pool[index]
            env.select(fixture)
            model.set_env(env, force_reset=True)
            model.learn(total_timesteps=STEPS_PER_BLOCK, reset_num_timesteps=False)
            entry = {"round": number, "family": fixture.family, "variant": fixture.variant,
                     "steps": model.num_timesteps, "wall_s": perf_counter() - wall_started,
                     "python_cpu_s": process_time() - cpu_started}
            results["blocks"].append(entry)
            save_report(output, report)
            print(f"{layout} round {number} {fixture.family}: {model.num_timesteps} train steps", flush=True)
        checkpoint = work / f"round-{number}.zip"
        model.save(checkpoint)
        results["checkpoints"].append(str(checkpoint.relative_to(output)))
        save_report(output, report)
    env.leave()
    return model


def eval_attempt(env, choose, seed, deterministic):
    torch.manual_seed(seed)
    encoded, _ = env.reset(seed=seed)
    maximum_progress, transitions = 0.0, 0
    while True:
        action = choose(env, encoded, deterministic)
        encoded, _, terminated, truncated, info = env.step(action)
        maximum_progress = max(maximum_progress, info["progress"])
        transitions += 1
        if terminated or truncated:
            return {
                "terminal": info["terminal"] or "tick_limit", "peak_progress": maximum_progress,
                "ticks": env.tick, "transitions": transitions, "seed": seed,
            }


def score(client, pool, name, layout, choose, cap, output, report):
    env = DrillEnv(client, layout)
    results = report["evaluation"].setdefault(name, [])
    for index, fixture in enumerate(pool):
        env.select(fixture)
        attempts = []
        for ordinal in range(cap):
            started = perf_counter()
            attempt = eval_attempt(env, choose, EVAL_SEED + 10 * index + ordinal, deterministic=ordinal == 0)
            attempt["wall_s"] = perf_counter() - started
            attempts.append(attempt)
            if attempt["terminal"] == "complete":
                break
        solved = attempts[-1]["terminal"] == "complete"
        extra = attempts[1:]
        row = {
            "family": fixture.family, "variant": fixture.variant, "split": fixture.split,
            "first_progress": attempts[0]["peak_progress"], "solved": solved,
            "attempts_to_first_clear_capped": len(attempts) if solved else cap,
            "practice": {"resets": 0, "ticks": 0, "transitions": 0, "wall_s": 0.0},
            "additional_full_runs": {
                "resets": len(extra), "ticks": sum(a["ticks"] for a in extra),
                "transitions": sum(a["transitions"] for a in extra), "wall_s": sum(a["wall_s"] for a in extra),
            },
            "attempts": attempts,
        }
        results.append(row)
        save_report(output, report)
        print(f"{name} {fixture.split} {fixture.family}: first={row['first_progress']:.1%}, solved={solved}", flush=True)
    env.leave()


def frozen_policy(model):
    def choose(env, encoded, deterministic):
        action, _ = model.predict(encoded, deterministic=deterministic)
        return int(action.item())
    return choose


def run(launcher_pid, output):
    output.mkdir(parents=True, exist_ok=False)
    discovery = json.loads((ROOT / "game/2.2091/gdbot/bridge.json").read_text(encoding="utf-8"))
    if discovery["pid"] != launcher_pid or discovery["pipe"] != PIPE_PREFIX + str(launcher_pid):
        raise RuntimeError("bridge discovery must match the launcher-owned PID")
    torch.set_num_threads(CPU_THREADS)
    torch.set_num_interop_threads(1)
    pools = fixtures()
    rng = random.Random(TRAIN_SEED)
    order = [rng.sample(range(len(pools["train"])), k=len(pools["train"])) for _ in range(TRAIN_ROUNDS)]
    report = {
        "pid": launcher_pid, "protocol": {
            "training_seed": TRAIN_SEED, "evaluation_seed": EVAL_SEED, "k": 4,
            "cpu_threads": CPU_THREADS, "per_encoder_wall_cap_s": WALL_LIMIT_PER_ENCODER_SECONDS,
            "steps_per_block": STEPS_PER_BLOCK, "rollout": ROLLOUT, "ppo_epochs": 4,
            "evaluation_attempt_cap": MAX_ATTEMPTS, "max_episode_ticks": MAX_TICKS,
            "heldout_training_steps": 0, "online_practice_budget": 0, "finish_wait_s": 0,
            "train_order": [[pools["train"][index].variant for index in draw] for draw in order],
        },
        "fixtures": {
            split: [{"name": fixture.level["name"], "seed": fixture.seed, "sha256": fixture.digest} for fixture in pool]
            for split, pool in pools.items()
        },
        "training": {}, "evaluation": {},
    }
    with BridgeClient(NamedPipeTransport(discovery["pipe"])) as client:
        hello = client.require_isolated()
        if not all(hello["capabilities"].get(flag) is True for flag in ("objects", "level_string", "quit_level")):
            raise RuntimeError("the baseline requires object-enabled local drill loading")
        if any(fixture.build != hello["build"]["exe_sha256"] for fixture in pools["train"] + pools["heldout"]):
            raise RuntimeError("fixture tapes were verified on a different game build")
        report["build"] = hello["build"]
        save_report(output, report)
        client.request("set_mode", mode="dedicated")
        fitted = {layout: train(client, pools["train"], order, layout, output, report) for layout in ("topk", "set")}

        heuristic = TimingHeuristic()
        for split in ("validation", "heldout"):
            pool = pools[split]
            score(client, pool, "heuristic", "topk", lambda env, obs, deterministic: heuristic(env.raw_observation),
                  MAX_ATTEMPTS, output, report)
            for layout, model in fitted.items():
                initial = PPO.load(output / layout / "initial.zip", device="cpu")
                score(client, pool, f"{layout}-initial", layout, frozen_policy(initial), 1, output, report)
                score(client, pool, layout, layout, frozen_policy(model), MAX_ATTEMPTS, output, report)
        client.request("set_mode", mode="normal")
    report["complete"] = True
    save_report(output, report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    options = parser.parse_args()
    run(options.pid, options.output)
