"""Triple-spike follow-up: does BC fail narrow timing windows because of coarse distance features or underfitting?

Arms (same demos from the 9 train tapes, same frozen M3 protocol and eval seeds):
  base     : current top-K encoder, 60 BC epochs (the M3 imitation recipe)
  base300  : current encoder, 300 epochs (underfitting?)
  near     : encoder with near_x=90 fine-scale timing features, 60 epochs (feature resolution?)
  near300  : both
Usage: python tools/m3/near_field.py --pid <launcher GD pid> --output build/m3-triple/near --seeds 1207 [--arms ...]
"""
import argparse
import json
import random
from pathlib import Path

import torch

import baseline
import imitation
from baseline import CPU_THREADS, MAX_ATTEMPTS, ROOT, frozen_policy, model_for, save_report, score
from gdbot.env import GDEnv
from gdbot.obs import ObservationEncoder
from gdbot.protocol import PIPE_PREFIX, BridgeClient, NamedPipeTransport, RemoteError
from scale import metrics, scaled_fixtures

ARMS = {"base": (None, 60), "base300": (None, 300), "near": (90.0, 60), "near300": (90.0, 300)}
_OriginalDrillEnv = baseline.DrillEnv
_near = {"x": None}


class NearDrillEnv(_OriginalDrillEnv):
    def __init__(self, client, layout):
        GDEnv.__init__(self, client, k=4, encoder=ObservationEncoder(layout=layout, near_x=_near["x"]),
                       max_ticks=baseline.MAX_TICKS)
        self.fixture = None


baseline.DrillEnv = NearDrillEnv  # score() builds its env through this name


def run(pid, output, seeds, arms):
    discovery = json.loads((ROOT / "game/2.2091/gdbot/bridge.json").read_text(encoding="utf-8"))
    if discovery["pid"] != pid or discovery["pipe"] != PIPE_PREFIX + str(pid):
        raise RuntimeError("bridge discovery must match the launcher-owned process")
    output.mkdir(parents=True, exist_ok=True)
    torch.set_num_threads(CPU_THREADS)
    pools, _ = scaled_fixtures()
    path = output / "report.json"
    report = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"evaluation": {}, "bc": {}}
    with BridgeClient(NamedPipeTransport(discovery["pipe"])) as client:
        client.require_isolated()
        try:
            client.request("quit_level")  # leave any level a previous client left loaded
        except RemoteError:
            pass
        client.request("set_mode", mode="dedicated")
        demos = {}
        for arm in arms:
            near_x, epochs = ARMS[arm]
            _near["x"] = near_x
            if near_x not in demos:
                env = NearDrillEnv(client, "topk")
                obs, act = [], []
                for fixture in pools["train"]:
                    demo = imitation.collect_demo(env, fixture)
                    if demo is None:
                        raise RuntimeError(f"demo failed: {fixture.family}")
                    obs += demo[0]
                    act += demo[1]
                env.leave()
                demos[near_x] = (obs, act)
            obs, act = demos[near_x]
            imitation.BC_EPOCHS = epochs
            for seed in seeds:
                key = f"{arm}-{seed}"
                if f"{key}/heldout" in report["evaluation"]:
                    continue
                random.seed(seed)
                model = model_for(NearDrillEnv(client, "topk"), "topk", seed=seed)
                report["bc"][key] = imitation.behaviour_clone(model, obs, act, seed)
                model.save(output / f"{key}.zip")
                for split in ("validation", "heldout"):
                    score(client, pools[split], f"{key}/{split}", "topk", frozen_policy(model), MAX_ATTEMPTS,
                          output, report)
                save_report(output, report)
        client.request("set_mode", mode="normal")
    report["summary"] = {k: metrics(v) for k, v in report["evaluation"].items()}
    save_report(output, report)
    for k, v in report["evaluation"].items():
        failed = [r["family"] for r in v if not r["solved"]]
        print(k, json.dumps(report["summary"][k]), "unsolved:", failed)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--pid", type=int, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--seeds", type=int, nargs="+", default=[1207])
    ap.add_argument("--arms", nargs="+", default=list(ARMS))
    a = ap.parse_args()
    run(a.pid, a.output, a.seeds, a.arms)
