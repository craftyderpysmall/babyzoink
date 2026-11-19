"""Diagnose the frozen M5 policy on the opening obstacles of official levels."""

import argparse
import hashlib
import json
import sys
from collections import Counter, deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "m5"))

import torch
from stable_baselines3 import PPO

from study import MAIN_LEVELS, ROOT, MainLevel, StudyEnv, fixtures, frozen_policy, save_report
from gdbot.baselines import TimingHeuristic
from gdbot.instances import discovery
from gdbot.obs import CATEGORIES, PLAYER_VECTOR_WIDTH, ObservationEncoder
from gdbot.protocol import PIPE_PREFIX, BridgeClient, NamedPipeTransport


def route_jump(observation, lead):
    player = observation["players"][0]
    if player["mode"] != "cube" or not player["on_ground"] or player["holding"]:
        return 0
    radius = 7.5 if player["mini"] else 15.0
    x, y, vx = player["x"], player["y"], player["vx"]
    sign = -1 if player["gravity_flipped"] else 1
    for item in observation["objects"]:
        if not item["active"] or item["cat"] not in ("hazard", "solid"):
            continue
        dy = (item["y"] - y) * sign
        half_height = item["h"] / 2
        # Ground tiles touch the feet but do not extend into the cube's route.
        if dy + half_height <= -radius + 1 or dy - half_height > radius:
            continue
        gap = item["x"] - item["w"] / 2 - x - radius
        if -4 <= gap <= max(1.0, vx) * lead:
            return 1
    return 0


class ProbeEncoder(ObservationEncoder):
    """Inference-only counterfactuals against the frozen weights."""

    def __init__(self, ablation):
        self.ablation = ablation
        super().__init__()

    def encode(self, observation, tick):
        player = observation["players"][0]
        canonical = {"solid": 1, "hazard": 8}
        objects = []
        for item in observation["objects"]:
            if self.ablation in ("route", "joint") and item["cat"] == "solid" and player["mode"] == "cube":
                sign = -1 if player["gravity_flipped"] else 1
                dy = (item["y"] - player["y"]) * sign
                if dy + item["h"] / 2 <= -16:
                    continue
            if self.ablation in ("ids", "joint") and item["cat"] in canonical:
                item = {**item, "type_id": canonical[item["cat"]]}
            objects.append(item)
        return super().encode({**observation, "objects": objects}, tick)


def selected_objects(env, state):
    encoder = env.encoder
    shape_start = PLAYER_VECTOR_WIDTH
    shape_end = shape_start + encoder.object_width * encoder.max_objects
    fields = state[shape_start:shape_end].reshape(encoder.max_objects, encoder.object_width)
    result = []
    for row in fields[state[shape_end:].astype(bool)]:
        category = next((key for i, key in enumerate(CATEGORIES) if row[13 + i]), None)
        result.append({
            "id": round(float(row[11]) * 1_000), "cat": category,
            "dx": round(float(row[0]) * encoder.ahead_x, 3),
            "dy": round(float(row[1]) * encoder.ahead_x, 3),
            "w": round(float(row[2]) * encoder.ahead_x, 3),
            "h": round(float(row[3]) * encoder.ahead_x, 3),
        })
    return result


def loss_trace(env, select, model=None, *, max_progress=None, keep_raw=False):
    state, _ = env.reset()
    start = env.raw_observation["players"][0]
    tail = deque(maxlen=30)
    press_samples = []
    coverage = {}
    decisions = native_truncated = encoder_truncated = issued_presses = 0
    held = 0
    while True:
        obs = env.raw_observation
        player = obs["players"][0]
        for obj in obs["objects"]:
            coverage.setdefault(obj["uid"], (obj["type_id"], obj["cat"]))
        action = select(env, state)
        native_truncated += int(obs["window"]["truncated"])
        encoder_truncated += int(env.encoder.truncated)
        issued_presses += int(action == 1 and held == 0)
        probability = None
        if model is not None:
            with torch.no_grad():
                inputs = model.policy.obs_to_tensor(state)[0]
                probability = float(model.policy.get_distribution(inputs).distribution.probs[0, 1])
        previous = {"tick": env.tick, "player": player, "raw_count": len(obs["objects"]),
                    "window": obs["window"], "encoded_truncated": env.encoder.truncated,
                    "selected": selected_objects(env, state), "action": action, "p_press": probability}
        if keep_raw:
            previous["raw"] = obs
        tail.append(previous)
        if keep_raw and action == 1 and held == 0:
            press_samples.append(previous)
        held = action
        state, _, terminated, truncated, info = env.step(action)
        decisions += 1
        terminal = info["terminal"]
        if terminated or truncated or max_progress is not None and info["progress"] >= max_progress:
            return {
                "start": start, "terminal": terminal or ("tick_limit" if truncated else "progress_gate"),
                "tick": env.tick, "progress": info["progress"], "decisions": decisions,
                "presses": issued_presses, "native_truncated": native_truncated,
                "encoder_truncated": encoder_truncated,
                "object_coverage": [
                    {"id": key[0], "cat": key[1], "count": count}
                    for key, count in sorted(Counter(coverage.values()).items())
                ],
                "terminal_player": env.raw_observation["players"][0], "tail": list(tail),
                "press_samples": press_samples[:8],
            }


def diagnose(client, checkpoint, output):
    output.mkdir(parents=True, exist_ok=True)
    model = PPO.load(checkpoint, device="cpu")
    deterministic = frozen_policy(model)
    env = StudyEnv(client, "topk")
    env.max_ticks = 7_000
    known_drills = {f.family: f for f in fixtures()["heldout"]}
    report = {
        "model_sha256": hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
        "bridge": client.require_isolated(), "official": {}, "controls": {}, "complete": False,
    }
    for family in ("single-spike", "double-spike", "block-steps"):
        env.select(known_drills[family])
        report["controls"][family] = loss_trace(env, lambda e, obs: deterministic(e, obs, True), model, keep_raw=True)
        env.leave()
    for i, name in enumerate(MAIN_LEVELS, 1):
        env.select(MainLevel(i, name))
        reference = loss_trace(env, lambda e, obs: deterministic(e, obs, True), model, keep_raw=True)
        probes = {}
        for lead in (0.12, 0.09, 0.15, 0.07, 0.17, 0.20):
            policy = TimingHeuristic(jump_lead_s=lead)
            probe = loss_trace(env, lambda e, _: policy(e.raw_observation), max_progress=0.10)
            probes[str(lead)] = probe
            if probe["progress"] >= 0.10:
                break
        route_probes = {}
        for lead in (22, 16, 28, 34, 10, 40):
            probe = loss_trace(env, lambda e, _: route_jump(e.raw_observation, lead), max_progress=0.10)
            route_probes[str(lead)] = probe
            if probe["progress"] >= 0.10:
                break
        original_encoder = env.encoder
        counterfactuals = {}
        for ablation in ("ids", "route", "joint"):
            env.encoder = ProbeEncoder(ablation)
            counterfactuals[ablation] = loss_trace(env, lambda e, obs: deterministic(e, obs, True), model)
        env.encoder = original_encoder
        env.leave()
        report["official"][str(i)] = {
            "name": name, "frozen": reference, "visible_geometry_probes": probes,
            "route_probes": route_probes, "counterfactuals": counterfactuals,
        }
        save_report(output, report)
        print(name, f"frozen {reference['progress']:.2%}",
              f"route best {max(p['progress'] for p in route_probes.values()):.2%}",
              {key: f"{result['progress']:.2%}" for key, result in counterfactuals.items()}, flush=True)
    report["complete"] = True
    save_report(output, report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--slot", type=int, required=True)
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, default=ROOT / "build/m5-curriculum/g03-s2357/policy.zip")
    options = parser.parse_args()
    bridge = discovery(options.slot)
    if bridge["instance"] != options.slot or bridge["pid"] != options.pid or bridge["pipe"] != PIPE_PREFIX + str(options.pid):
        raise RuntimeError("slot discovery did not match the launcher-owned game")
    with BridgeClient(NamedPipeTransport(bridge["pipe"])) as client:
        client.require_isolated()
        client.request("set_mode", mode="dedicated")
        diagnose(client, options.checkpoint, options.output)
