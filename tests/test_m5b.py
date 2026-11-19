from copy import deepcopy

import numpy as np

from gdbot.env import GDEnv
from gdbot.mock_bridge import MOCK_LEVEL, MockBridge
from gdbot.obs import CATEGORIES, OBJECT_WIDTH, ObservationEncoder, ROUTE_WIDTH


def test_route_features_use_collision_geometry_and_keep_legacy_inputs():
    with MockBridge().client() as client:
        env = GDEnv(client, level=MOCK_LEVEL)
        env.reset()
        raw = deepcopy(env.raw_observation)
    player = raw["players"][0]
    player.update(x=0.0, y=105.0, vx=1.2982, mini=False, gravity_flipped=False)
    raw["window"].update(ahead_x=900.0, behind_x=90.0)
    raw["objects"] = [
        {"uid": 1, "type_id": 6, "cat": "solid", "x": 30, "y": 75, "w": 30, "h": 30,
         "rot": 0, "active": True, "params": {}},
        {"uid": 2, "type_id": 39, "cat": "hazard", "x": 60, "y": 96, "w": 6, "h": 6,
         "rot": 0, "active": True, "params": {}},
    ]
    plain = ObservationEncoder(layout="set").encode(raw, 1)
    route = ObservationEncoder(layout="set", route_geometry=True).encode(raw, 1)
    assert route["objects"].shape[1] == OBJECT_WIDTH + ROUTE_WIDTH
    np.testing.assert_array_equal(plain["mask"], route["mask"])
    np.testing.assert_allclose(plain["objects"][:2, 11], [0.006, 0.039])
    np.testing.assert_array_equal(route["objects"][:2, 11], [0, 0])
    assert route["objects"][1, 13 + CATEGORIES.index("hazard")] == 1
    np.testing.assert_allclose(route["objects"][0, -3:], [0, 0, 0])
    np.testing.assert_allclose(route["objects"][1, -3:], [0.7, 0.3, 1])
