"""Measure the client, observation encoder, and PPO with one bridge."""

import argparse
import json
import math
import statistics
from dataclasses import asdict, dataclass, field
from time import perf_counter

from .mock_bridge import MOCK_LEVEL, MockBridge
from .protocol import BridgeClient, NamedPipeTransport


@dataclass
class _Samples:
    steps: list[float] = field(default_factory=list)
    resets: list[float] = field(default_factory=list)
    ticks: int = 0

    def step(self, started: float, ticks: int) -> None:
        self.steps.append(perf_counter() - started)
        self.ticks += ticks


@dataclass(frozen=True)
class Benchmark:
    stage: str
    mode: str
    transitions: int
    ticks: int
    elapsed_s: float
    ticks_per_s: float
    transitions_per_s: float
    step_p50_ms: float
    step_p95_ms: float
    reset_p50_ms: float
    resets: int


def _client_loop(client, level, steps, k, samples):
    client.load_level(level)
    episode, tick, terminal = None, 0, None
    started = perf_counter()
    for _ in range(steps):
        if episode is None or terminal:
            start = perf_counter()
            reset = client.request("reset", start={"kind": "zero"})
            samples.resets.append(perf_counter() - start)
            episode, tick = reset["episode"], reset["tick"]
        start = perf_counter()
        reply = client.step(episode=episode, tick=tick, action=0, k=k)
        samples.step(start, reply["ticks_advanced"])
        tick, terminal = reply["tick"], reply["terminal"]
    return perf_counter() - started


def _environment_loop(client, level, steps, k, samples, stage, layout):
    from .env import GDEnv
    from .obs import ObservationEncoder

    class TimedEnv(GDEnv):
        def reset(self, **kwargs):
            start = perf_counter()
            result = super().reset(**kwargs)
            samples.resets.append(perf_counter() - start)
            return result

        def step(self, action):
            start = perf_counter()
            result = super().step(action)
            samples.step(start, result[-1]["ticks_advanced"])
            return result

    env = TimedEnv(client, level=level, k=k, encoder=ObservationEncoder(layout=layout))
    if stage == "observation":
        started = perf_counter()
        env.reset()
        for index in range(steps):
            _, _, terminal, truncated, _ = env.step(0)
            if (terminal or truncated) and index + 1 < steps:
                env.reset()
        return perf_counter() - started

    from stable_baselines3 import PPO

    from .model import PooledSetExtractor, TopKExtractor

    rollout = min(128, max(2, steps))
    model = PPO(
        "MlpPolicy" if layout == "topk" else "MultiInputPolicy",
        env, n_steps=rollout, batch_size=rollout, n_epochs=1, device="cpu", seed=0,
        policy_kwargs={"features_extractor_class": TopKExtractor if layout == "topk" else PooledSetExtractor},
    )
    started = perf_counter()
    model.learn(total_timesteps=steps)
    return perf_counter() - started


def benchmark(
    client: BridgeClient, *, level: dict, steps: int = 1_000, k: int = 4,
    stage: str = "ipc", mode: str = "normal", layout: str = "topk",
) -> Benchmark:
    if steps < 1 or k < 1:
        raise ValueError("steps and k must be positive")
    if stage not in ("ipc", "observation", "ppo"):
        raise ValueError("unknown benchmark stage")
    client.require_isolated()
    client.request("set_mode", mode=mode)
    client.load_level(level)
    samples = _Samples()
    if stage == "ipc":
        elapsed = _client_loop(client, level, steps, k, samples)
    else:
        elapsed = _environment_loop(client, level, steps, k, samples, stage, layout)
    ordered = sorted(samples.steps)
    count = len(ordered)
    return Benchmark(
        stage, mode, count, samples.ticks, elapsed, samples.ticks / elapsed, count / elapsed,
        statistics.median(ordered) * 1_000, ordered[math.ceil(0.95 * count) - 1] * 1_000,
        statistics.median(samples.resets) * 1_000, len(samples.resets),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pipe", help="Local Windows bridge pipe. Omit to use the mock.")
    parser.add_argument("--level", type=json.loads, help="Protocol level selector as JSON.")
    parser.add_argument("--steps", type=int, default=1_000)
    parser.add_argument("--k", type=int, default=4)
    parser.add_argument("--stage", choices=("ipc", "observation", "ppo"), default="ipc")
    parser.add_argument("--mode", choices=("normal", "dedicated", "background"), default="normal")
    parser.add_argument("--layout", choices=("topk", "set"), default="topk")
    args = parser.parse_args()
    if args.pipe and not isinstance(args.level, dict):
        parser.error("--pipe requires a JSON --level selector")
    client = BridgeClient(NamedPipeTransport(args.pipe)) if args.pipe else MockBridge().client()
    with client:
        result = benchmark(
            client, level=args.level or MOCK_LEVEL, steps=args.steps, k=args.k,
            stage=args.stage, mode=args.mode, layout=args.layout,
        )
    print(json.dumps({"bridge": "pipe" if args.pipe else "mock", **asdict(result)}, indent=2))


if __name__ == "__main__":
    main()
