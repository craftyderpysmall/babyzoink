"""M3 recipe fix: behaviour cloning from the verified train tapes, then PPO fine-tuning (top-K encoder).

Compares, under the scaled study's frozen protocol (validation 4100-4108, frozen held-out set,
3-attempt cap, same eval seeds):
  bc      : policy trained only on demonstrations from the 9 train-drill tapes
  bc_ppo  : bc weights fine-tuned with PPO (lower lr / clip) for one quarter of the scaled budget
The scaled study's top-K results (build/m3-scale/paired-study) are the baseline.
Never uses validation or held-out tapes.

Usage: python tools/m3/imitation.py --pid <launcher GD pid> --output build/m3-imitation
"""
import argparse
import json
import random
from pathlib import Path
from time import perf_counter

import numpy as np
import torch
from torch import nn

from baseline import CPU_THREADS, MAX_ATTEMPTS, ROLLOUT, ROOT, DrillEnv, frozen_policy, model_for, save_report, score
from diagnose import quantize
from gdbot.protocol import PIPE_PREFIX, BridgeClient, NamedPipeTransport
from gdbot.replay import Tape
from scale import metrics, scaled_fixtures

SEEDS = (1207, 2357, 3907)
K = 4
BC_EPOCHS = 60
BC_BATCH = 256
BC_LR = 1e-3
PPO_STEPS_PER_FIXTURE = 27_648  # one quarter of the scaled study per model
PPO_LR = 1e-4
PPO_CLIP = 0.1


def tape_for(fixture):
    for line in (ROOT / "levels/drills/index.yaml").read_text(encoding="utf-8").splitlines():
        if line.strip().startswith('tape: "') and f"/{fixture.variant}.json" in line and fixture.family in line:
            return Tape.load(ROOT / "levels/drills" / line.split('"')[1])
    raise FileNotFoundError(f"no tape for {fixture.family}/{fixture.variant}")


def collect_demo(env, fixture):
    """Replay the tape on the policy's own decision grid; return (obs, actions) if it completes."""
    edges = quantize([tuple(e) for e in tape_for(fixture).edges], K, 0)
    act_at = {}
    action = 0
    for tick, value in edges:
        act_at[tick] = value
    env.select(fixture)
    obs, _ = env.reset(seed=0)
    observations, actions = [], []
    while True:
        # A decision at tick T sets the button for ticks T+1..T+K; quantized edges sit exactly on T+1.
        action = act_at.get(env.tick + 1, action)
        observations.append(obs)
        actions.append(action)
        obs, _, terminated, truncated, info = env.step(action)
        if terminated or truncated:
            return (observations, actions) if info["terminal"] == "complete" else None


def behaviour_clone(model, observations, actions, seed):
    torch.manual_seed(seed)
    x = torch.as_tensor(np.asarray(observations), dtype=torch.float32)
    y = torch.as_tensor(np.asarray(actions), dtype=torch.long)
    counts = torch.bincount(y, minlength=2).float().clamp(min=1)
    loss_fn = nn.CrossEntropyLoss(weight=counts.sum() / (2 * counts))  # balance rare presses
    policy = model.policy
    opt = torch.optim.Adam(policy.parameters(), lr=BC_LR)
    gen = torch.Generator().manual_seed(seed)
    history = []
    for epoch in range(BC_EPOCHS):
        order = torch.randperm(len(y), generator=gen)
        total = 0.0
        for start in range(0, len(y), BC_BATCH):
            idx = order[start:start + BC_BATCH]
            logits = policy.get_distribution(x[idx]).distribution.logits
            loss = loss_fn(logits, y[idx])
            opt.zero_grad()
            loss.backward()
            opt.step()
            total += loss.item() * len(idx)
        if epoch % 10 == 9 or epoch == BC_EPOCHS - 1:
            with torch.no_grad():
                pred = policy.get_distribution(x).distribution.logits.argmax(-1)
            acc = float((pred == y).float().mean())
            press_recall = float(((pred == 1) & (y == 1)).sum() / max(1, int((y == 1).sum())))
            history.append({"epoch": epoch + 1, "loss": total / len(y), "accuracy": acc, "press_recall": press_recall})
            print(f"  bc epoch {epoch + 1}: loss {total / len(y):.4f} acc {acc:.3f} press-recall {press_recall:.3f}", flush=True)
    return history


def run(pid, output):
    discovery = json.loads((ROOT / "game/2.2091/gdbot/bridge.json").read_text(encoding="utf-8"))
    if discovery["pid"] != pid or discovery["pipe"] != PIPE_PREFIX + str(pid):
        raise RuntimeError("bridge discovery must match the launcher-owned process")
    output.mkdir(parents=True, exist_ok=True)
    torch.set_num_threads(CPU_THREADS)
    pools, _ = scaled_fixtures()
    report_path = output / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {
        "protocol": {"seeds": list(SEEDS), "k": K, "bc_epochs": BC_EPOCHS, "bc_lr": BC_LR,
                     "ppo_steps_per_fixture": PPO_STEPS_PER_FIXTURE, "ppo_lr": PPO_LR, "ppo_clip": PPO_CLIP,
                     "encoder": "topk", "attempt_cap": MAX_ATTEMPTS},
        "demos": {}, "bc": {}, "evaluation": {}, "complete": False}
    with BridgeClient(NamedPipeTransport(discovery["pipe"])) as client:
        client.require_isolated()
        client.request("set_mode", mode="dedicated")
        env = DrillEnv(client, "topk")
        demo_obs, demo_act = [], []
        for fixture in pools["train"]:
            demo = collect_demo(env, fixture)
            report["demos"][f"{fixture.family}/{fixture.variant}"] = None if demo is None else {
                "decisions": len(demo[1]), "presses": int(sum(demo[1]))}
            if demo:
                demo_obs += demo[0]
                demo_act += demo[1]
            print(f"demo {fixture.family}/{fixture.variant}: {report['demos'][f'{fixture.family}/{fixture.variant}']}", flush=True)
        env.leave()
        save_report(output, report)
        if not demo_act:
            raise RuntimeError("no demonstration completed on the k=4 grid")
        for seed in SEEDS:
            key = f"topk-{seed}"
            if f"{key}/bc_ppo/heldout" in report["evaluation"]:
                continue
            random.seed(seed)
            env = DrillEnv(client, "topk")  # only for the spaces; no level is loaded here
            model = model_for(env, "topk", seed=seed)
            started = perf_counter()
            report["bc"][key] = {"history": behaviour_clone(model, demo_obs, demo_act, seed),
                                 "samples": len(demo_act), "wall_s": perf_counter() - started}
            model.save(output / f"{key}-bc.zip")
            for split in ("validation", "heldout"):
                score(client, pools[split], f"{key}/bc/{split}", "topk", frozen_policy(model), MAX_ATTEMPTS, output, report)
            # PPO fine-tune from the cloned weights, gentler steps so it doesn't forget the demonstrations
            env = DrillEnv(client, "topk")
            model.learning_rate = PPO_LR
            model.lr_schedule = lambda _: PPO_LR
            model.clip_range = lambda _: PPO_CLIP
            for group in model.policy.optimizer.param_groups:
                group["lr"] = PPO_LR
            order = random.Random(seed).sample(range(len(pools["train"])), k=len(pools["train"]))
            started = perf_counter()
            for index in order:
                env.select(pools["train"][index])
                model.set_env(env, force_reset=True)
                model.learn(total_timesteps=PPO_STEPS_PER_FIXTURE, reset_num_timesteps=False)
                print(f"{key} ppo {pools['train'][index].family}: {model.num_timesteps} transitions", flush=True)
            env.leave()
            report["bc"][key]["ppo_wall_s"] = perf_counter() - started
            model.save(output / f"{key}-bc_ppo.zip")
            for split in ("validation", "heldout"):
                score(client, pools[split], f"{key}/bc_ppo/{split}", "topk", frozen_policy(model), MAX_ATTEMPTS, output, report)
        client.request("set_mode", mode="normal")
    report["summary"] = {label: metrics(rows) for label, rows in report["evaluation"].items()}
    report["complete"] = True
    save_report(output, report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    options = parser.parse_args()
    run(options.pid, options.output)
