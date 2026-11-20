"""Gymnasium environment for isolated bridge sessions."""

import gymnasium as gym
from gymnasium import spaces

from . import runmode
from .obs import ObservationEncoder
from .protocol import BridgeClient, ProtocolError


class GDEnv(gym.Env):
    metadata = {"render_modes": []}

    def __init__(
        self, client: BridgeClient, *, level: dict | None = None, k: int = 4,
        encoder: ObservationEncoder | None = None, max_ticks: int | None = None,
        death_penalty: float = 0.1, completion_bonus: float = 1.0,
    ):
        if type(k) is not int or k < 1:
            raise ValueError("k must be a positive integer")
        if max_ticks is not None and (type(max_ticks) is not int or max_ticks < 1):
            raise ValueError("max_ticks must be a positive integer")
        self.client = client
        self.hello = client.require_isolated()
        runmode.follow(self.hello.get("mode"))  # the user's dedicated/background toggle
        capabilities = self.hello.get("capabilities", {})
        if any(capabilities.get(key) is not True for key in ("reset", "step")):
            raise ProtocolError("bridge must support reset and step")
        self.encoder = encoder if encoder is not None else ObservationEncoder()
        self.observation_space = self.encoder.space
        self.action_space = spaces.Discrete(2)
        self.k = k
        self.max_ticks = max_ticks
        self.death_penalty = death_penalty
        self.completion_bonus = completion_bonus
        self.level = level
        self._loaded = None
        self._ready = False

    def reset(self, *, seed: int | None = None, options: dict | None = None):
        super().reset(seed=seed)
        self._ready = False
        options = options or {}
        level = options.get("level", self.level)
        if level is None:
            raise ValueError("reset needs a level selector")
        if level != self.level or self._loaded is None:
            self._loaded = self.client.load_level(level)
            self.level = level.copy()
        start = options.get("start", {"kind": "zero"})
        reply = self.client.request("reset", start=start)
        self.input_timing = "cbf" if reply.get("input_timing", {}).get("cbf") is True else "tick"
        self.episode = reply["episode"]
        self.tick = reply["tick"]
        self.raw_observation = reply["obs"]
        self.progress = self.raw_observation["progress"]
        self.encoder.reset()
        observation = self.encoder.encode(self.raw_observation, self.tick)
        self._ready = True
        return observation, self._info()

    def step(self, action, *, frac=0):
        if not self._ready:
            raise gym.error.ResetNeeded("reset the episode before stepping")
        if not self.action_space.contains(action):
            raise ValueError("action must be 0 (release) or 1 (hold)")
        count = self.k if self.max_ticks is None else min(self.k, self.max_ticks - self.tick)
        if frac and self.input_timing != "cbf":
            raise ValueError("fractional steps require the CBF bridge")
        timing = {"frac": frac} if frac else {}
        try:
            reply = self.client.step(episode=self.episode, tick=self.tick, action=int(action), k=count, **timing)
        except (ProtocolError, OSError, EOFError):
            self._ready = False
            raise
        runmode.follow(reply.get("mode"))
        advanced = reply["ticks_advanced"]
        terminal = reply["terminal"]
        self.tick = reply["tick"]
        self.raw_observation = reply["obs"]
        progress = self.raw_observation["progress"]
        reward = progress - self.progress
        if terminal == "death":
            reward -= self.death_penalty
        elif terminal == "complete":
            reward += self.completion_bonus
        self.progress = progress
        terminated = terminal is not None
        truncated = not terminated and self.max_ticks is not None and self.tick >= self.max_ticks
        self._ready = not (terminated or truncated)
        observation = self.encoder.encode(self.raw_observation, self.tick)
        return observation, reward, terminated, truncated, self._info(
            ticks_advanced=advanced, terminal=terminal, events=reply["events"],
        )

    def _info(self, **fields) -> dict:
        return {
            "episode_id": self.episode, "tick": self.tick, "progress": self.progress,
            "level_revision": self._loaded["revision"],
            "objects_truncated": self.encoder.truncated,
            "unsupported": self.encoder.unsupported,
            **fields,
        }

    def close(self):
        self._ready = False
        self.client.close()
