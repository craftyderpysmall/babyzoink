"""#11 follow-up: does one verified search tape fix the held-out triple spike across clone seeds, and how fast does
the trainer run in dedicated vs background mode?

Part A (dedicated): for each extra clone seed, clone the control (27 route drill demos + official search demos) and
the same set plus the training triple-spike search tape, then play heldout-2102 up to 3 attempts per arm.
Part B: clone the with-search set once per mode (dedicated, background) at the reference seed and time it, then time
three evaluation runs per mode on the held-out drill.

Usage: python tools/m5b/triple_seeds.py --slot 1 [--seeds 1207 3907] [--output build/m5c-expert/triple-seeds]
Inputs: build/m5c-expert/official (report.json, demos/), build/m5c-expert/triple/train-1102-search.npz.
"""

import argparse
import json
import sys
from pathlib import Path
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "m5c"))

from expert import (  # noqa: E402
    ROOT, ROUTE_TRUSTED, SEED, BridgeClient, NamedPipeTransport, RemoteError,
    TransferEnv, clone_checkpoint, discovery, model_for, save_report,
)
from stable_baselines3 import PPO  # noqa: E402
from baseline import EVAL_SEED, MAX_ATTEMPTS, fixtures, frozen_policy  # noqa: E402
from study import full_run  # noqa: E402
from gdbot import runmode  # noqa: E402

OFFICIAL = ROOT / "build/m5c-expert/official"
TAPE = ROOT / "build/m5c-expert/triple/train-1102-search.npz"


def archives(with_tape):
    route = sorted(ROUTE_TRUSTED.glob("*.npz"))
    if len(route) != 27:
        raise RuntimeError("expected the 27 M5b route drill demonstrations")
    expert = json.loads((OFFICIAL / "report.json").read_text(encoding="utf-8"))
    official = [OFFICIAL / "demos" / f"{name.replace(':', '_')}.npz" for name in expert["demos"]]
    return route + official + ([TAPE] if with_tape else [])


def evaluate(env, heldout, checkpoint, attempts, *, stop_on_clear=True, runs=MAX_ATTEMPTS):
    choose = frozen_policy(PPO.load(checkpoint, device="cpu"))
    env.select(heldout)
    while len(attempts) < runs and not (stop_on_clear and any(a["terminal"] == "complete" for a in attempts)):
        ordinal = len(attempts)
        _, attempt = full_run(env, choose, ordinal, EVAL_SEED + ordinal)
        attempts.append(attempt)
    env.leave()
    return attempts


def summary(attempts):
    return (f"first={attempts[0]['peak_progress']:.1%}, best={max(a['peak_progress'] for a in attempts):.1%}, "
            f"clears={sum(a['terminal'] == 'complete' for a in attempts)}/{len(attempts)}")


def set_mode(client, mode):
    reply = client.request("set_mode", mode=mode)
    runmode.follow(mode)
    return bool(reply.get("overridden_by_user")) if isinstance(reply, dict) else False


def run(slot, seeds, output):
    output.mkdir(parents=True, exist_ok=True)
    if not TAPE.exists():
        raise RuntimeError(f"missing {TAPE}")
    pools = fixtures()
    heldout = next(f for f in pools["heldout"] if f.family == "triple-spike")
    path = output / "report.json"
    report = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {
        "heldout_level": f"drill:{heldout.family}/{heldout.variant}", "attempt_cap": MAX_ATTEMPTS,
        "reference_seed": SEED, "seeds": {}, "throughput": {}}
    with BridgeClient(NamedPipeTransport(discovery(slot)["pipe"])) as client:
        client.require_isolated()
        try:
            client.request("quit_level")
        except RemoteError:
            pass
        try:
            report["overridden_by_user"] = set_mode(client, "dedicated")
            env = TransferEnv(client, "route")
            # Part A: seed robustness.
            for seed in seeds:
                entry = report["seeds"].setdefault(str(seed), {})
                for arm, with_tape in (("control", False), ("with-search", True)):
                    checkpoint = output / f"{arm}-{seed}.zip"
                    if not checkpoint.exists():
                        entry.setdefault("clone", {})[arm] = clone_checkpoint(
                            model_for(env, "topk", seed=seed), archives(with_tape), checkpoint, seed=seed)
                        save_report(output, report)
                    attempts = entry.setdefault(arm, [])
                    evaluate(env, heldout, checkpoint, attempts)
                    save_report(output, report)
                    print(f"seed {seed} {arm}: {summary(attempts)}", flush=True)
            # Part B: trainer and environment throughput per mode.
            for mode in ("dedicated", "background"):
                if mode in report["throughput"]:
                    continue
                overridden = set_mode(client, mode)
                checkpoint = output / f"throughput-{mode}.zip"
                cloned = clone_checkpoint(model_for(env, "topk", seed=SEED), archives(True), checkpoint, seed=SEED)
                start = perf_counter()
                runs = evaluate(env, heldout, checkpoint, [], stop_on_clear=False)
                wall = perf_counter() - start
                ticks = sum(a["ticks"] for a in runs)
                report["throughput"][mode] = {
                    "overridden_by_user": overridden,
                    "clone": cloned, "clone_samples_per_s": cloned["samples"] / cloned["wall_s"],
                    "eval_runs": len(runs), "eval_ticks": ticks, "eval_wall_s": wall,
                    "eval_ticks_per_s": ticks / wall,
                }
                save_report(output, report)
                t = report["throughput"][mode]
                print(f"{mode}: clone {t['clone_samples_per_s']:.0f} samples/s ({cloned['wall_s']:.1f}s wall), "
                      f"eval {t['eval_ticks_per_s']:.0f} ticks/s", flush=True)
        finally:
            client.request("set_mode", mode="normal")
            runmode.follow("normal")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slot", type=int, required=True)
    parser.add_argument("--seeds", type=int, nargs="+", default=[1207, 3907])
    parser.add_argument("--output", type=Path, default=ROOT / "build/m5c-expert/triple-seeds")
    args = parser.parse_args()
    run(args.slot, args.seeds, args.output)
