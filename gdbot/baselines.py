"""A ground-jump timing baseline for simple static hazard drills."""

from .protocol import PHYSICS_HZ


class TimingHeuristic:
    def __init__(self, *, jump_lead_s: float = 0.08):
        if jump_lead_s <= 0:
            raise ValueError("jump lead time must be positive")
        self.jump_lead_s = jump_lead_s

    def __call__(self, observation: dict) -> int:
        player = observation["players"][0]
        if player["mode"] != "cube" or player["holding"] or not player["on_ground"] or player["vx"] <= 0:
            return 0
        for obj in observation["objects"]:
            if obj["cat"] != "hazard" or not obj["active"]:
                continue
            dx = obj["x"] - obj["w"] / 2 - player["x"]
            dy = obj["y"] - player["y"]
            if 0 <= dx <= player["vx"] * PHYSICS_HZ * self.jump_lead_s and abs(dy) <= max(obj["h"], 0.5):
                return 1
        return 0
