"""Bounded practice search for forward-playing Geometry Dash drills."""

from collections import Counter
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path
from time import perf_counter

import numpy as np


@dataclass(frozen=True)
class Decision:
    x: float
    observation: object
    action: int


def save_demonstration(path: Path, observations, actions):
    """Publish a complete archive atomically so interrupted generations can retry."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    with temporary.open("wb") as file:
        np.savez(file, observations=np.asarray(observations, dtype=np.float32),
                 actions=np.asarray(actions, dtype=np.uint8))
    temporary.replace(path)


def demo_counts(paths):
    counts = np.zeros(2, dtype=np.int64)
    for path in paths:
        with np.load(path) as archive:
            actions = archive["actions"]
            counts += np.bincount(actions, minlength=2)
    return counts


def demo_batches(paths, rng, batch_size):
    """Shuffle archives and examples with at most one loaded archive at a time."""
    for index in rng.permutation(len(paths)):
        with np.load(paths[index]) as archive:
            observations, actions = archive["observations"], archive["actions"]
        order = rng.permutation(len(actions))
        for start in range(0, len(order), batch_size):
            batch = order[start:start + batch_size]
            yield observations[batch], actions[batch]
        del observations, actions


@dataclass
class PracticeCost:
    resets: int = 0
    ticks: int = 0
    transitions: int = 0
    wall_s: float = 0.0
    checkpoint_parity: list[bool] = field(default_factory=list)

    def reset(self, env, start=None):
        self.resets += 1
        return env.reset(options={"start": start} if start is not None else None)[0]

    def step(self, env, action):
        observation, _, _, truncated, info = env.step(action)
        self.transitions += 1
        self.ticks += info["ticks_advanced"]
        return observation, info["terminal"] or ("tick_limit" if truncated else None)


@dataclass(frozen=True)
class PracticeWindow:
    anchor: int
    target_x: float
    finish_required: bool


class DeathHotspots:
    """Keep isolated per-level death bins and widen verified end sections backwards."""

    def __init__(self):
        self.histogram = Counter()
        self.deaths = {}
        self.end_witnesses = Counter()

    def record(self, death_x, decisions):
        bucket = int(death_x // 60)
        self.histogram[bucket] += 1
        self.deaths[bucket] = (death_x, decisions)
        return bucket

    def window(self, finish_x, preferred):
        # Favor recurring reachable failures. A newer failure wins ties.
        bucket = max(self.histogram, key=lambda key: (self.histogram[key], key == preferred, key))
        death_x, decisions = self.deaths[bucket]
        near_end = finish_x - death_x <= 480
        lead = 155 + 100 * self.end_witnesses[bucket] if near_end else 155
        anchor = max((i for i, decision in enumerate(decisions) if decision.x <= death_x - lead), default=0)
        return bucket, decisions, PracticeWindow(anchor, death_x + 155, near_end)


def timing_candidates(actions, limit):
    """Shift a nearby press or release, or insert one short press before death."""
    if not actions or limit <= 0:
        return
    edges = [i for i, (before, after) in enumerate(pairwise(actions), 1) if before != after]
    seen = {tuple(actions)}
    shifts = (1, -1, 2, -2, 4, -4, 7, -7, 11, -11)
    for number in range(len(shifts)):
        changes = []
        for edge in reversed(edges[-4:]):
            offset = shifts[number]
            left, right = sorted((edge, edge + offset))
            if left >= 0 and right <= len(actions):
                changes.append((left, right, actions[edge - 1] if offset > 0 else actions[edge]))
        # The dead run may contain no jump. Sample a deterministic grid of short pulses.
        for lead in (7 + 3 * number, 23 + 3 * number):
            start = len(actions) - lead
            if start >= 0:
                changes.append((start, min(start + 2, len(actions)), 1))
        for left, right, action in changes:
            changed = tuple(actions[:left]) + (action,) * (right - left) + tuple(actions[right:])
            if changed not in seen:
                seen.add(changed)
                yield changed
                if len(seen) > limit:
                    return


def replay_prefix(env, decisions, cost, *, practice=False):
    """Return the encoded state after bringing the original level to an anchor."""
    observation = cost.reset(env)
    if practice:
        env.client.request("set_practice", enabled=True)
    for decision in decisions:
        observation, terminal = cost.step(env, decision.action)
        if terminal is not None:
            return None
    return observation


def x_position(env):
    return env.raw_observation["players"][0]["x"]


def verified_checkpoint(env, prefix, suffix, cost):
    if replay_prefix(env, prefix, cost, practice=True) is None:
        return None
    candidate = env.client.request("checkpoint_create")
    if abs(candidate["x"] - suffix[0].x) > 0.01:
        return None
    start = {"kind": "checkpoint", "checkpoint_id": candidate["checkpoint_id"]}
    observation = cost.reset(env, start)
    for index, decision in enumerate(suffix):
        # Reset clears the bridge's measured vx and the encoder's object history.
        # Replay the anchor's original action before requiring policy-observation parity.
        if abs(x_position(env) - decision.x) >= 0.01 or (
            index > 0 and not np.array_equal(observation, decision.observation)
        ):
            return None
        observation, terminal = cost.step(env, decision.action)
        if terminal:
            return start if terminal == "death" and index > 0 and index == len(suffix) - 1 else None
    return None


def practice_section(env, trace, window, choose, *, limit, start_trial=None):
    """Search one section. Prove the restore against the failed trace or replay its prefix."""
    cost = PracticeCost()
    started = perf_counter()
    prefix, suffix = trace[:window.anchor], trace[window.anchor:]
    checkpoint = None
    if env.hello.get("capabilities", {}).get("checkpoint"):
        checkpoint = verified_checkpoint(env, prefix, suffix, cost)
        cost.checkpoint_parity.append(checkpoint is not None)

    if checkpoint is not None:
        anchor_action = suffix[0].action
        suffix = suffix[1:]
    source = tuple(decision.action for decision in suffix)
    for candidate_actions in timing_candidates(source, limit):
        if start_trial is not None:
            start_trial()
        observation = cost.reset(env, checkpoint) if checkpoint else replay_prefix(env, prefix, cost)
        if observation is None:
            raise RuntimeError("clean prefix did not reach the recorded practice anchor")
        if checkpoint is not None:
            observation, terminal = cost.step(env, anchor_action)
            if terminal:
                raise RuntimeError("verified checkpoint unexpectedly ended during its warm-up decision")
        demonstration = []
        for index in range(len(source) + 160):
            action = candidate_actions[index] if index < len(source) else choose(env, observation, True)
            demonstration.append(Decision(x_position(env), observation, action))
            observation, terminal = cost.step(env, action)
            if terminal == "complete" or (
                terminal is None and not window.finish_required and x_position(env) >= window.target_x
            ):
                cost.wall_s = perf_counter() - started
                return demonstration, terminal == "complete", cost
            if terminal:
                break
    cost.wall_s = perf_counter() - started
    return [], False, cost
