"""Test a verified training-only triple-spike tape against the expert clone."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "m5c"))

from expert import (  # noqa: E402
    ROOT, ROUTE_TRUSTED, SEED, BridgeClient, NamedPipeTransport, RemoteError,
    TransferEnv, clone_checkpoint, discovery, model_for, save_demonstration,
    save_report, solution_demo,
)
from stable_baselines3 import PPO  # noqa: E402
from baseline import EVAL_SEED, MAX_ATTEMPTS, fixtures, frozen_policy  # noqa: E402
from study import full_run  # noqa: E402


def run(slot, official, output):
    output.mkdir(parents=True, exist_ok=True)
    pools = fixtures()
    train = next(f for f in pools["train"] if f.family == "triple-spike")
    heldout = next(f for f in pools["heldout"] if f.family == "triple-spike")
    train_key = f"drill:{train.family}/{train.variant}"
    test_key = f"drill:{heldout.family}/{heldout.variant}"
    solution = ROOT / "build/m5c" / f"drill_{train.family}_{train.variant}.json"
    source = json.loads(solution.read_text(encoding="utf-8"))
    if source["level"] != train_key or not source["result"]["verified"]:
        raise RuntimeError("expected a verified solution for the training fixture")
    expert = json.loads((official / "report.json").read_text(encoding="utf-8"))
    if "online" not in expert:
        raise RuntimeError("complete the official expert comparison first")
    if set(expert["demos"]) - {f"main:{i}" for i in range(1, 6)}:
        raise RuntimeError("the expert comparison must use only official search demonstrations")
    path = output / "report.json"
    protocol = {
        "training_level": train_key, "heldout_level": test_key, "attempt_cap": MAX_ATTEMPTS,
        "clone_seed": SEED, "expert_training_levels": expert["train"],
    }
    report = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {**protocol, "evaluation": {}}
    if any(report.get(key) != value for key, value in protocol.items()):
        raise RuntimeError("comparison inputs changed; use an output directory for the new run")
    demo = output / f"{train.variant}-search.npz"
    new_clone = output / "with-search.zip"
    with BridgeClient(NamedPipeTransport(discovery(slot)["pipe"])) as client:
        client.require_isolated()
        try:
            client.request("quit_level")
        except RemoteError:
            pass
        client.request("set_mode", mode="dedicated")
        try:
            env = TransferEnv(client, "route")
            if "demo" not in report or not demo.exists():
                observations, actions = solution_demo(env, train, source["result"]["actions"])
                save_demonstration(demo, observations, actions)
                report["demo"] = {"decisions": len(actions), "terminal": "complete", "peak_progress": 1.0}
                save_report(output, report)
            if "clone" not in report or not new_clone.exists():
                original_archives = sorted(ROUTE_TRUSTED.glob("*.npz"))
                if len(original_archives) != 27:
                    raise RuntimeError("expected the 27 M5b route drill demonstrations")
                official_archives = [official / "demos" / f"{name.replace(':', '_')}.npz"
                                     for name in expert["demos"]]
                model = model_for(env, "topk", seed=SEED)
                report["clone"] = clone_checkpoint(model, original_archives + official_archives + [demo], new_clone)
                del model
                save_report(output, report)
            for arm, checkpoint in (("expert", official / "clone.zip"), ("with-search", new_clone)):
                attempts = report["evaluation"].setdefault(arm, [])
                model = PPO.load(checkpoint, device="cpu")
                choose = frozen_policy(model)
                env.select(heldout)
                while len(attempts) < MAX_ATTEMPTS and not any(a["terminal"] == "complete" for a in attempts):
                    ordinal = len(attempts)
                    _, attempt = full_run(env, choose, ordinal, EVAL_SEED + ordinal)
                    attempts.append(attempt)
                    save_report(output, report)
                env.leave()
                print(f"{arm}: first={attempts[0]['peak_progress']:.1%}, "
                      f"best={max(a['peak_progress'] for a in attempts):.1%}, "
                      f"clears={sum(a['terminal'] == 'complete' for a in attempts)}/{len(attempts)}", flush=True)
        finally:
            client.request("set_mode", mode="normal")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slot", type=int, required=True)
    parser.add_argument("--official", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.slot, args.official, args.output)
