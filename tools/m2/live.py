"""Exercise one launcher-owned GD process and optionally compare with an earlier launch."""

import argparse
import cProfile
import json
import pstats
import sys
from dataclasses import asdict
from pathlib import Path
from time import sleep

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from gdbot.bench import benchmark
from gdbot.env import GDEnv
from gdbot.protocol import PIPE_PREFIX, BridgeClient, NamedPipeTransport
from gdbot.replay import Tape, diff_traces, record, replay

LEVEL = {"kind": "main", "id": 1}
SETTINGS = {"profile": "isolated launcher profile"}
COMMANDS = [(0, 100), (1, 18), (0, 140), (1, 10), (0, 520)]
OBJECT_FIELDS = ("uid", "cat", "x", "y", "w", "h")


class SamplingClient(BridgeClient):
    object_rows = None

    def step(self, **kwargs):
        reply = super().step(**kwargs)
        if self.object_rows is not None:
            objects = [
                {field: obj[field] for field in OBJECT_FIELDS}
                for obj in sorted(reply["obs"]["objects"], key=lambda obj: (obj["x"], obj["y"], obj["uid"]))
            ]
            self.object_rows.append({"tick": reply["tick"], "objects": objects})
        return reply


def env_smoke(client, level):
    env = GDEnv(client, level=level, k=4)
    before, reset = env.reset(options={"start": {"kind": "zero"}})
    _, _, terminated, truncated, first = env.step(0)
    for _ in range(14):
        _, _, terminated, truncated, info = env.step(0)
        if terminated or truncated:
            raise RuntimeError(f"episode ended unexpectedly at tick {info['tick']}")
    ground_y = env.raw_observation["players"][0]["y"]
    after, reward, terminated, truncated, info = env.step(1)
    jumped = env.raw_observation["players"][0].copy()
    _, _, _, _, released = env.step(0)
    checks = {
        "first_step_without_wait": first["tick"] == 4 and first["ticks_advanced"] == 4,
        "encoded_observations": env.observation_space.contains(before) and env.observation_space.contains(after),
        "step_ticks": info["tick"] == 64 and info["ticks_advanced"] == 4 and released["tick"] == 68,
        "jump_rises": not (terminated or truncated) and jumped["y"] > ground_y,
        "held_then_released": jumped["holding"] and not env.raw_observation["players"][0]["holding"],
    }
    return {
        "reset_tick": reset["tick"], "jump_tick": info["tick"], "release_tick": released["tick"],
        "reward": reward, "progress": info["progress"], "player": jumped,
        "unsupported": info["unsupported"], "objects": len(env.raw_observation["objects"]),
        "checks": checks,
    }


def freeze_probe(client, mode):
    client.request("set_mode", mode=mode)
    samples = []
    for wait in (0, 0.75):
        reset = client.request("reset", start={"kind": "zero"})
        episode = reset["episode"]
        first = client.step(episode=episode, tick=0, action=0, k=8)
        sleep(wait)
        next_step = client.step(episode=episode, tick=first["tick"], action=0, k=1)
        samples.append({"tick": next_step["tick"], **next_step["obs"]})
    return diff_traces(samples[:1], samples[1:])


def drill_prefix():
    verified = Tape.load(ROOT / "levels/drills/tapes/moving-geometry/train-1108.json")
    # The prefix passes the mover and excludes the wall-clock completion sequence.
    limit = 1320
    return Tape(
        verified.build_hash, verified.level, verified.level_revision, verified.settings, verified.seed,
        verified.start, limit, tuple(edge for edge in verified.edges if edge[0] <= limit),
    )


def capture(client, tape, mode, k):
    client.object_rows = []
    try:
        ticks = replay(client, tape, settings=tape.settings, seed=tape.seed, mode=mode, chunk_ticks=k)
        return {"ticks": ticks, "objects": client.object_rows}
    finally:
        client.object_rows = None


def compare(expected, actual, *, common_samples=False):
    left, right = expected["objects"], actual["objects"]
    if common_samples:
        shared = {row["tick"] for row in left} & {row["tick"] for row in right}
        if not shared:
            raise RuntimeError("no common object sampling ticks")
        left = [row for row in left if row["tick"] in shared]
        right = [row for row in right if row["tick"] in shared]
    player_difference = diff_traces(expected["ticks"], actual["ticks"])
    object_difference = diff_traces(left, right)
    return min(
        (diff for diff in (player_difference, object_difference) if diff is not None),
        key=lambda diff: diff.tick, default=None,
    )


def parity(client, tape, source):
    traces = {}
    cases = []
    for mode in ("normal", "dedicated", "background"):
        for k in (1, 4):
            label = f"{mode}:k{k}"
            traces[label] = capture(client, tape, mode, k)
            if mode == "normal":
                repeated = capture(client, tape, mode, k)
                cases.append((f"same process reset: {label}", compare(traces[label], repeated)))
            else:
                cases.append((f"mode parity: {label}", compare(traces[f"normal:k{k}"], traces[label])))
            if source:
                cases.append((f"fresh launch: {label}", compare(source["traces"][label], traces[label])))
        cases.append((f"physics freeze: {mode}", freeze_probe(client, mode)))
        samples = traces[f"{mode}:k1"]["objects"]
        if not any(row["objects"] for row in samples):
            raise RuntimeError(f"no collision objects captured in {mode}")
        cadence = compare(traces[f"{mode}:k1"], traces[f"{mode}:k4"], common_samples=True)
        cases.append((f"cross cadence: {mode}", cadence))
    return traces, cases


def profile_benchmark(client, *, level, stage, k, output):
    profiler = cProfile.Profile()
    sample = profiler.runcall(benchmark, client, level=level, stage=stage, k=k, mode="dedicated", steps=2000)
    profiler.dump_stats(str(output))
    stats = pstats.Stats(profiler)

    def cumulative(file, name):
        return sum(
            record[3] for (source, _, function), record in stats.stats.items()
            if Path(source).name == file and function == name
        )

    return {
        "stage": stage, "k": k, "wall_s": sample.elapsed_s,
        "pipe_read_s": cumulative("protocol.py", "_read_exact"),
        "python_json_decode_s": cumulative("__init__.py", "loads"),
        "request_pack_s": cumulative("protocol.py", "pack_frame"),
        "encoder_s": cumulative("obs.py", "encode"),
        "ppo_update_s": cumulative("ppo.py", "train"),
    }


def stage_benchmarks(client, level, label, output):
    measurements, profiles = [], []
    modes = ("normal", "dedicated", "background") if label == "main" else ("dedicated",)
    for mode in modes:
        steps = 6000 if mode == "dedicated" else 180
        for stage in ("ipc", "observation", "ppo"):
            for k in (1, 4):
                sample = benchmark(client, level=level, steps=steps, stage=stage, mode=mode, k=k)
                measurements.append({"k": k, **asdict(sample)})
                print(
                    f"{label} {mode} {stage} k={k}: {sample.ticks_per_s:.1f} ticks/s, "
                    f"{sample.transitions_per_s:.1f} transitions/s", flush=True,
                )
    for stage in ("ipc", "observation", "ppo"):
        for k in (1, 4):
            profile_path = output.with_suffix(f".{label}.{stage}.k{k}.pstats")
            profiles.append(profile_benchmark(client, level=level, stage=stage, k=k, output=profile_path))
    return measurements, profiles


def run(args):
    discovery = json.loads(args.discovery.read_text(encoding="utf-8"))
    if discovery["pid"] != args.pid or discovery["pipe"] != PIPE_PREFIX + str(args.pid):
        raise RuntimeError("discovery does not match the launcher-reported PID")
    source = json.loads(args.baseline.read_text(encoding="utf-8")) if args.baseline else None
    if source and source["pid"] == args.pid:
        raise RuntimeError("fresh-launch comparison requires a different PID")
    report = {"pid": args.pid, "baseline_pid": source["pid"] if source else None, "levels": {}}
    passed = True
    with SamplingClient(NamedPipeTransport(discovery["pipe"])) as client:
        hello = client.require_isolated()
        if hello["capabilities"].get("objects") is not True:
            raise RuntimeError("the native object extractor must be enabled")
        report["hello"] = hello
        print(f"Connected to {args.pid} with isolated saves and HTTP blocking.", flush=True)
        drill = drill_prefix() if args.with_drill else None
        levels = [("main", LEVEL)]
        if drill is not None:
            levels.append(("moving-drill", drill.level))
        for label, level in levels:
            smoke = env_smoke(client, level)
            print(f"{label} Gymnasium smoke: {smoke['checks']}", flush=True)
            client.request("set_mode", mode="dedicated")
            tape_path = args.output.with_suffix(f".{label}.tape.json")
            if source:
                baseline_path = args.baseline.with_suffix(f".{label}.tape.json")
                tape = Tape.load(baseline_path)
            elif label == "main":
                tape = record(client, level, COMMANDS, settings=SETTINGS)
            else:
                tape = drill
            tape.save(tape_path)
            traces, cases = parity(client, tape, source["levels"][label] if source else None)
            for name, difference in cases:
                print(f"{label} {name}: {difference or 'PASS'}", flush=True)
            measurements, profiles = stage_benchmarks(client, level, label, args.output) if args.bench else ([], [])
            report["levels"][label] = {
                "env": smoke, "tape": asdict(tape), "traces": traces,
                "parity": [{"case": name, "difference": asdict(diff) if diff else None} for name, diff in cases],
                "benchmarks": measurements, "profiles": profiles,
            }
            args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
            passed &= all(smoke["checks"].values()) and all(diff is None for _, diff in cases)
            client.request("quit_level")
        client.request("set_mode", mode="normal")
    return int(not passed)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, required=True, help="Game PID printed by gdbot-launch.exe")
    parser.add_argument("--discovery", type=Path, default=ROOT / "game/2.2091/gdbot/bridge.json")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--bench", action="store_true")
    parser.add_argument("--with-drill", action="store_true", help="Also test the verified moving-geometry prefix.")
    raise SystemExit(run(parser.parse_args()))


if __name__ == "__main__":
    main()
