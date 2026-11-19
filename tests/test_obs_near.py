from copy import deepcopy

import numpy as np

from gdbot.env import GDEnv
from gdbot.mock_bridge import MOCK_LEVEL, MockBridge
from gdbot.obs import NEAR_WIDTH, OBJECT_WIDTH, ObservationEncoder



def _raw():
    with MockBridge().client() as client:
        env = GDEnv(client, level=MOCK_LEVEL)
        env.reset()
        return deepcopy(env.raw_observation)


def test_default_encoder_is_unchanged_by_near_option():
    raw = _raw()
    plain = ObservationEncoder().encode(raw, 0)
    off = ObservationEncoder(near_x=None).encode(raw, 0)
    np.testing.assert_array_equal(plain, off)


def test_near_features_widen_rows_and_resolve_small_shifts():
    raw = _raw()
    enc = ObservationEncoder(layout="set", near_x=90.0)
    assert enc.object_width == OBJECT_WIDTH + NEAR_WIDTH
    assert enc.space["objects"].shape[1] == OBJECT_WIDTH + NEAR_WIDTH
    a = enc.encode(raw, 0)
    shifted = deepcopy(raw)
    shifted["players"][0]["x"] += 5.2  # one k=4 decision at 1x speed
    b = ObservationEncoder(layout="set", near_x=90.0).encode(shifted, 0)
    live = a["mask"].astype(bool) & b["mask"].astype(bool)
    coarse = np.abs(a["objects"][live, 0] - b["objects"][live, 0]).max()
    fine = np.abs(a["objects"][live, OBJECT_WIDTH] - b["objects"][live, OBJECT_WIDTH]).max()
    assert fine > 5 * coarse
    topk = ObservationEncoder(near_x=90.0)
    assert topk.encode(raw, 0).shape == topk.space.shape
