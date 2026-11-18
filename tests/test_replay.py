from copy import deepcopy

import pytest

from gdbot.mock_bridge import MOCK_LEVEL, MockBridge
from gdbot.protocol import BridgeClient, InProcessTransport
from gdbot.replay import Tape, diff_traces, record, replay


def test_tape_round_trip_and_mock_parity(tmp_path):
    settings = {"resolution": "pinned"}
    with MockBridge().client() as client:
        tape = record(client, MOCK_LEVEL, [(0, 4), (1, 4), (1, 4), (0, 60)], settings=settings)
    assert tape.edges == ((5, 1), (13, 0))
    path = tmp_path / "tape.json"
    tape.save(path)
    assert Tape.load(path) == tape
    with MockBridge().client() as client:
        visible = replay(client, tape, settings=settings, mode="normal", chunk_ticks=1)
        for mode in ("dedicated", "background"):
            other = replay(client, tape, settings=settings, mode=mode, chunk_ticks=4)
            assert diff_traces(visible, other) is None
        with pytest.raises(ValueError, match="settings"):
            replay(client, tape, settings={})
    assert len(visible) == tape.total_ticks
    assert visible[4]["button"]["held"]


def test_diff_identifies_first_tick_and_nested_field():
    expected = [{"tick": 8, "players": [{"x": 1, "vy": 0.0}]}, {"tick": 9}]
    actual = deepcopy(expected)
    actual[0]["players"][0]["vy"] = -0.5
    actual[1]["extra"] = 1
    difference = diff_traces(expected, actual)
    assert (difference.tick, difference.field, difference.expected, difference.actual) == (8, "players[0].vy", 0.0, -0.5)
    assert diff_traces(expected, expected[:1]).tick == 9


def test_replay_reuses_scene_and_includes_envelope_terminal():
    mock = MockBridge()
    loads = 0

    def handle(request):
        nonlocal loads
        if request["op"] == "load_level":
            loads += 1
            assert loads == 1, "this bridge can only load from the menu"
        reply = mock.handle(request)
        for row in reply.get("trace", []):
            row["events"] = []
        return reply

    with BridgeClient(InProcessTransport(handle)) as client:
        tape = record(client, MOCK_LEVEL, [(0, 64)], settings={})
        rows = replay(client, tape, settings={}, chunk_ticks=4)
    assert rows[-1]["tick"] == 50
    assert rows[-1]["terminal"] == "death"
    assert loads == 1


def test_replay_pauses_only_at_recorded_tick(tmp_path, monkeypatch):
    mock = MockBridge()
    waits = []
    monkeypatch.setattr("gdbot.replay.sleep", lambda seconds: waits.append((mock.tick, seconds)))
    with mock.client() as client:
        tape = record(client, MOCK_LEVEL, [(0, 24)], settings={})
        prepared = Tape(
            tape.build_hash, tape.level, tape.level_revision, {}, None, tape.start, 24, (),
            "complete", finish_wait=(7, 1.2),
        )
        path = tmp_path / "wait.json"
        prepared.save(path)
        assert Tape.load(path) == prepared
        rows = replay(client, prepared, settings={}, chunk_ticks=24)
    assert waits == [(7, 1.2)]
    assert [row["tick"] for row in rows] == list(range(1, 25))
