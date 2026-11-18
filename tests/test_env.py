from copy import deepcopy

import numpy as np
import pytest
from gymnasium.error import ResetNeeded

from gdbot.baselines import TimingHeuristic
from gdbot.bench import benchmark
from gdbot.env import GDEnv
from gdbot.mock_bridge import MOCK_LEVEL, MockBridge
from gdbot.obs import ObservationEncoder
from gdbot.protocol import ProtocolError


@pytest.mark.parametrize("flag", ["saves_redirected", "http_blocked"])
def test_env_refuses_nonisolated_bridge(flag):
    mock = MockBridge(**{flag: False})
    with pytest.raises(ProtocolError, match="save redirection and HTTP blocking"):
        GDEnv(mock.client(), level=MOCK_LEVEL)
    assert mock.level is None


def test_env_preserves_terminal_tick_and_truncation():
    with MockBridge().client() as client:
        env = GDEnv(client, k=4)
        obs, info = env.reset(options={"level": MOCK_LEVEL, "start": {"kind": "zero"}})
        assert env.observation_space.contains(obs)
        assert info["tick"] == 0
        for _ in range(12):
            assert not env.step(0)[2]
        _, _, terminated, truncated, info = env.step(0)
        assert terminated and not truncated
        assert info["tick"] == 50 and info["ticks_advanced"] == 2
        with pytest.raises(ResetNeeded):
            env.step(0)
    with MockBridge().client() as client:
        env = GDEnv(client, level=MOCK_LEVEL, k=4, max_ticks=3)
        env.reset()
        _, _, terminated, truncated, info = env.step(0)
        assert not terminated and truncated
        assert info["tick"] == 3


@pytest.mark.parametrize("layout", ["topk", "set"])
def test_encoder_is_relative_and_excludes_level_identity_and_progress(layout):
    with MockBridge().client() as client:
        env = GDEnv(client, level=MOCK_LEVEL)
        env.reset()
        raw = deepcopy(env.raw_observation)
    shifted = deepcopy(raw)
    shifted.update(progress=0.9, level="another level")
    for entry in [*shifted["players"], *shifted["objects"]]:
        entry["x"] += 100
        entry["y"] += 100
    a = ObservationEncoder(layout=layout).encode(raw, 0)
    b = ObservationEncoder(layout=layout).encode(shifted, 0)
    if layout == "set":
        for key in a:
            np.testing.assert_allclose(a[key], b[key])
    else:
        np.testing.assert_allclose(a, b)


def test_encoder_tracks_velocity_and_reports_flags():
    with MockBridge().client() as client:
        env = GDEnv(client, level=MOCK_LEVEL)
        env.reset()
        raw = deepcopy(env.raw_observation)
    encoder = ObservationEncoder(layout="set", max_objects=1)
    assert encoder.encode(raw, 0)["mask"].sum() == 1
    raw["objects"][0]["x"] += 0.1
    raw["window"]["truncated"] = True
    raw["unsupported"] = ["toggle"]
    encoded = encoder.encode(raw, 4)
    assert encoded["objects"][0, 6] == pytest.approx(0.025)
    assert encoder.truncated
    assert encoder.unsupported == ("toggle",)
    encoder.reset()
    assert encoder.encode(raw, 0)["objects"][0, 6] == 0


def test_time_to_contact_uses_game_units_per_tick():
    with MockBridge().client() as client:
        env = GDEnv(client, level=MOCK_LEVEL)
        env.reset()
        raw = deepcopy(env.raw_observation)
    raw["players"][0]["vx"] = 1.25
    raw["objects"][0]["x"] = 60
    raw["window"]["ahead_x"] = 120
    encoded = ObservationEncoder(layout="set", horizon_s=0.25).encode(raw, 0)
    assert encoded["mask"].sum() == 1
    assert encoded["objects"][0, 8] == pytest.approx((60 - 0.35) / (1.25 * 240 * 0.25))


def test_heuristic_completes_toy_level():
    heuristic = TimingHeuristic()
    with MockBridge().client() as client:
        env = GDEnv(client, level=MOCK_LEVEL, k=4)
        env.reset()
        for _ in range(52):
            _, _, terminated, _, info = env.step(heuristic(env.raw_observation))
            if terminated:
                break
    assert info["terminal"] == "complete"


@pytest.mark.parametrize("stage", ["ipc", "observation"])
def test_bench_reports_actual_advanced_ticks(stage):
    with MockBridge().client() as client:
        result = benchmark(client, level=MOCK_LEVEL, steps=20, k=4, stage=stage)
    assert result.transitions == 20
    assert result.ticks == 78
    assert result.resets == 2
    assert result.step_p95_ms >= result.step_p50_ms > 0


@pytest.mark.parametrize("layout", ["topk", "set"])
def test_cpu_ppo_can_collect_and_update(layout):
    pytest.importorskip("stable_baselines3")
    with MockBridge().client() as client:
        result = benchmark(client, level=MOCK_LEVEL, steps=8, stage="ppo", layout=layout)
    assert result.transitions == 8
