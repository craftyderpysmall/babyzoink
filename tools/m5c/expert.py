"""M5c expert iteration, step 1: search clears -> demonstrations -> behaviour cloning -> zero-shot eval.

Inputs: verified solver solutions (build/m5c/*.json, from tools/m5c/solver.py) for the TRAIN levels,
plus the 27 verified drill-tape demos Codex built for the M5b route arm. Held-out levels never
supply demonstrations. The cloned policy is scored zero-shot (first attempt) on the frozen M5b online
held-out set and on official levels 1-5, and compared with the M5b route baseline (same encoder,
same seed, drill demos only).

Usage: python tools/m5c/expert.py --slot 0 --train main:1 main:2 ... --output build/m5c/expert
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for extra in ("tools/m5b", "tools/m5", "tools/m4", "tools/m3"):
    sys.path.insert(0, str(ROOT / extra))
sys.path.insert(0, str(ROOT))

from transfer import SEED, OnlineLevel, TransferEnv, clone_checkpoint, first_runs, online_pool  # noqa: E402
from study import MAIN_LEVELS, MainLevel, model_for, save_report  # noqa: E402
from gdbot.curriculum import save_demonstration  # noqa: E402
from gdbot.instances import discovery  # noqa: E402
from gdbot.protocol import BridgeClient, NamedPipeTransport, RemoteError  # noqa: E402
from solver import level_spec  # noqa: E402

ROUTE_TRUSTED = ROOT / "build/m5b-official/transfer/route/trusted"


def fixture_for(name: str):
    kind, _, rest = name.partition(":")
    if kind == "main":
        n = int(rest)
        return MainLevel(n, MAIN_LEVELS[n - 1])
    return OnlineLevel(0, name, selector=level_spec(name))


def solution_demo(env, fixture, actions):
    """Replay a verified action list through the env, recording (observation, action) pairs."""
    env.select(fixture)
    observation, _ = env.reset()
    observations, taken = [], []
    for action in actions:
        observations.append(observation)
        taken.append(action)
        observation, _, terminated, truncated, info = env.step(action)
        if terminated or truncated:
            if info["terminal"] != "complete":
                raise RuntimeError(f"solution for {fixture.variant} ended in {info['terminal']} during demo replay")
            env.leave()
            return observations, taken
    raise RuntimeError(f"solution for {fixture.variant} did not finish")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--slot", type=int, default=0)
    ap.add_argument("--train", nargs="+", required=True, help="solver level names with verified solutions")
    ap.add_argument("--solutions", type=Path, default=ROOT / "build/m5c")
    ap.add_argument("--output", type=Path, default=ROOT / "build/m5c/expert")
    a = ap.parse_args()
    out = a.output
    (out / "demos").mkdir(parents=True, exist_ok=True)
    path = out / "report.json"
    report = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"train": a.train, "demos": {}}
    d = discovery(a.slot)
    with BridgeClient(NamedPipeTransport(d["pipe"])) as client:
        client.require_isolated()
        try:
            client.request("quit_level")
        except RemoteError:
            pass
        client.request("set_mode", mode="dedicated")
        env = TransferEnv(client, "route")
        env.max_ticks = 60_000
        archives = sorted(ROUTE_TRUSTED.glob("*.npz"))
        if len(archives) != 27:
            raise RuntimeError(f"expected the 27 M5b route drill demos, found {len(archives)}")
        for name in a.train:
            sol = json.loads((a.solutions / (name.replace(":", "_").replace("/", "_") + ".json")).read_text())["result"]
            if not sol or not sol["verified"]:
                print(f"skip {name}: no verified solution", flush=True)
                continue
            demo_path = out / "demos" / (name.replace(":", "_").replace("/", "_") + ".npz")
            if not demo_path.exists():
                obs, act = solution_demo(env, fixture_for(name), sol["actions"])
                save_demonstration(demo_path, obs, act)
                report["demos"][name] = {"decisions": len(act), "presses": int(sum(act))}
                print(f"demo {name}: {len(act)} decisions", flush=True)
            archives.append(demo_path)
        save_report(out, report)
        if "online" not in report:
            checkpoint = out / "clone.zip"
            model = model_for(env, "topk", seed=SEED)
            report["clone"] = clone_checkpoint(model, archives, checkpoint)
            del model
            official = [MainLevel(i, n) for i, n in enumerate(MAIN_LEVELS, 1)]
            report["official"] = first_runs(env, official, checkpoint, "m5c-expert-official", generation=1, official=True)
            report["online"] = first_runs(env, online_pool(), checkpoint, "m5c-expert-online", generation=1, official=False)
            save_report(out, report)
        client.request("set_mode", mode="normal")
    base = json.loads((ROOT / "build/m5b-official/transfer/report.json").read_text(encoding="utf-8"))
    for split in ("official", "online"):
        new = [r["peak_progress"] for r in report[split].values()]
        if split == "online":
            old = [v["first_progress"] for v in base["online"].values()]
        else:
            old = [v["peak_progress"] for v in base["official_zero_shot"].values()]
        print(f"{split}: zero-shot mean first progress {100 * sum(new) / len(new):.1f}% "
              f"(M5b route baseline {100 * sum(old) / len(old):.1f}%); clears {sum(r['terminal'] == 'complete' for r in report[split].values())}")


if __name__ == "__main__":
    main()
