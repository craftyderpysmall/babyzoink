"""Fixed-size policy features from protocol v0 observations."""

import math

import numpy as np
from gymnasium import spaces

from .protocol import PHYSICS_HZ

MODES = ("cube", "ship", "ball", "ufo", "wave", "robot", "spider", "swing")
CATEGORIES = (
    "solid", "hazard", "orb", "pad", "portal_mode", "portal_gravity", "portal_size",
    "portal_speed", "portal_dual", "portal_teleport", "other",
)
ORB_KINDS = (
    "yellow", "pink", "red", "blue", "green", "black", "dash_green", "dash_pink", "spider", "toggle",
)
PLAYER_FLAGS = ("gravity_flipped", "mini", "on_ground", "on_ceiling", "holding", "buffered", "dashing", "dead")
PLAYER_WIDTH = 8 + len(MODES) + len(PLAYER_FLAGS)
PLAYER_VECTOR_WIDTH = 2 * PLAYER_WIDTH + 2
OBJECT_WIDTH = 13 + len(CATEGORIES) + len(ORB_KINDS) + len(MODES)
NEAR_WIDTH = 3  # dx/near_x, gap/near_x, contact ticks/NEAR_TICKS (opt-in, see near_x)
NEAR_TICKS = 60


def _one_hot(value, options: tuple) -> list[int]:
    return [int(value == option) for option in options]


def _orientation(degrees: float) -> tuple[float, float]:
    radians = math.radians(degrees)
    return math.sin(radians), math.cos(radians)


class ObservationEncoder:
    def __init__(
        self, *, layout: str = "topk", max_objects: int = 32,
        horizon_s: float = 0.75, ahead_x: float = 900.0, behind_x: float = 90.0,
        near_x: float | None = None,
    ):
        # near_x (opt-in): extra fine-scale timing features per object. dx/ahead_x moves only ~0.006
        # per k=4 decision, too coarse for narrow windows like triple spike.
        if layout not in ("topk", "set"):
            raise ValueError("layout must be topk or set")
        if max_objects < 1 or any(not math.isfinite(value) or value <= 0 for value in (horizon_s, ahead_x, behind_x)):
            raise ValueError("object count, horizon, and window limits must be positive")
        self.layout = layout
        self.max_objects = max_objects
        self.horizon_s = horizon_s
        self.ahead_x = ahead_x
        self.behind_x = behind_x
        self.near_x = near_x
        self.object_width = OBJECT_WIDTH + (NEAR_WIDTH if near_x else 0)
        if layout == "topk":
            shape = (PLAYER_VECTOR_WIDTH + max_objects * (self.object_width + 1),)
            self.space = spaces.Box(-np.inf, np.inf, shape, np.float32)
        else:
            self.space = spaces.Dict({
                "player": spaces.Box(-np.inf, np.inf, (PLAYER_VECTOR_WIDTH,), np.float32),
                "objects": spaces.Box(-np.inf, np.inf, (max_objects, self.object_width), np.float32),
                "mask": spaces.Box(0, 1, (max_objects,), np.float32),
            })
        self.reset()

    def reset(self) -> None:
        self.previous_tick = None
        self.previous_objects = {}
        self.truncated = False
        self.unsupported = ()

    def encode(self, observation: dict, tick: int) -> np.ndarray | dict[str, np.ndarray]:
        players = observation["players"]
        origin = players[0]
        window = observation["window"]
        ahead = min(self.ahead_x, window["ahead_x"])
        behind = min(self.behind_x, window["behind_x"])
        ticks_elapsed = tick - self.previous_tick if self.previous_tick is not None else 0
        candidates = []
        current_objects = {}
        for obj in observation["objects"]:
            uid = obj["uid"]
            position = obj["x"], obj["y"]
            current_objects[uid] = position
            previous = self.previous_objects.get(uid) if ticks_elapsed > 0 else None
            vx, vy = (
                ((position[0] - previous[0]) / ticks_elapsed, (position[1] - previous[1]) / ticks_elapsed)
                if previous else (0.0, 0.0)
            )
            dx, dy = position[0] - origin["x"], position[1] - origin["y"]
            sine, cosine = _orientation(obj["rot"])
            half_span = (abs(cosine) * obj["w"] + abs(sine) * obj["h"]) / 2
            if dx - half_span > ahead or dx + half_span < -behind:
                continue
            closing_speed = (origin["vx"] - vx) * PHYSICS_HZ
            gap = max(0.0, dx - half_span)
            if gap and (closing_speed <= 0 or gap > closing_speed * self.horizon_s):
                continue
            contact = gap / closing_speed if gap else 0.0
            params = obj["params"]
            destination = params.get("to")
            speed = float(destination) if obj["cat"] == "portal_speed" and type(destination) in (int, float) else 0.0
            row = [
                dx / self.ahead_x, dy / self.ahead_x,
                obj["w"] / self.ahead_x, obj["h"] / self.ahead_x,
                sine, cosine, vx, vy, contact / self.horizon_s,
                float(obj["active"]), float(previous is not None), obj["type_id"] / 1000.0, speed,
                *_one_hot(obj["cat"], CATEGORIES), *_one_hot(params.get("kind"), ORB_KINDS),
                *_one_hot(destination, MODES),
            ]
            if self.near_x:
                row += [min(4.0, max(-2.0, dx / self.near_x)), min(4.0, gap / self.near_x),
                        min(4.0, contact * PHYSICS_HZ / NEAR_TICKS)]
            candidates.append(((contact, abs(dx), abs(dy), uid), row))

        self.previous_tick = tick
        self.previous_objects = current_objects
        self.truncated = bool(window["truncated"]) or len(candidates) > self.max_objects
        self.unsupported = tuple(observation["unsupported"])
        player = np.zeros(PLAYER_VECTOR_WIDTH, dtype=np.float32)
        for i, body in enumerate(players[:2]):
            start = i * PLAYER_WIDTH
            player[start:start + PLAYER_WIDTH] = [
                (body["x"] - origin["x"]) / self.ahead_x,
                (body["y"] - origin["y"]) / self.ahead_x,
                body["vx"], body["vy"] / PHYSICS_HZ,
                *_orientation(body["rot"]), body["speed"], 1.0,
                *_one_hot(body["mode"], MODES),
                *(float(body[key]) for key in PLAYER_FLAGS),
            ]
        player[-2:] = self.truncated, bool(self.unsupported)

        objects = np.zeros((self.max_objects, self.object_width), dtype=np.float32)
        mask = np.zeros(self.max_objects, dtype=np.float32)
        for i, (_, row) in enumerate(sorted(candidates, key=lambda item: item[0])[:self.max_objects]):
            objects[i] = row
            mask[i] = 1
        if self.layout == "topk":
            return np.concatenate((player, objects.ravel(), mask))
        return {"player": player, "objects": objects, "mask": mask}
