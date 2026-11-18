import io
import os
import struct
from concurrent.futures import Future
from threading import Thread
from time import monotonic, sleep
from uuid import uuid4

import pytest

from gdbot.mock_bridge import MOCK_LEVEL, MockBridge
from gdbot.protocol import (
    PIPE_PREFIX, BridgeClient, ErrorCode, InProcessTransport, NamedPipeTransport, ProtocolError,
    RemoteError, pack_frame, read_frame,
)


class FragmentedStream(io.BytesIO):
    def read(self, size=-1):
        return super().read(min(2, size))


def test_little_endian_framing_handles_partial_reads_and_unicode():
    message = {"op": "load_level", "name": "café"}
    frame = pack_frame(message)
    assert frame[:4] == (len(frame) - 4).to_bytes(4, "little")
    assert read_frame(FragmentedStream(frame)) == message


@pytest.mark.parametrize(
    ("frame", "error"),
    [(b"", EOFError), (struct.pack("<I", 10) + b"{}", EOFError),
     (struct.pack("<I", 0), ProtocolError), (struct.pack("<I", 2) + b"[]", ProtocolError)],
)
def test_invalid_frame_fails(frame, error):
    with pytest.raises(error):
        read_frame(io.BytesIO(frame))


def test_bad_reply_id_poisoned_connection():
    transport = InProcessTransport(lambda request: {"id": request["id"] + 1, "ok": True})
    with pytest.raises(ProtocolError, match="reply ID"):
        BridgeClient(transport).hello()
    assert transport.closed


def test_successful_quit_invalidates_level_cache():
    loads = []

    def handle(request):
        reply = {"id": request["id"], "ok": True}
        if request["op"] == "load_level":
            loads.append(request["level"])
            reply["level"] = {"revision": str(len(loads))}
        return reply

    client = BridgeClient(InProcessTransport(handle))
    assert client.load_level(MOCK_LEVEL)["revision"] == "1"
    assert client.load_level(MOCK_LEVEL)["revision"] == "1"
    client.request("quit_level")
    assert client.load_level(MOCK_LEVEL)["revision"] == "2"


def test_mock_freeze_trace_reset_and_early_stop():
    mock = MockBridge()
    with mock.client() as client:
        client.require_isolated()
        client.request("load_level", level=MOCK_LEVEL)
        reset = client.request("reset", start={"kind": "zero"})
        client.request("set_mode", mode="background")
        client.request("trace", enabled=True)
        assert mock.tick == 0
        first = client.step(episode=reset["episode"], tick=0, action=0, k=4)
        assert first["tick"] == first["ticks_advanced"] == 4
        assert [row["tick"] for row in first["trace"]] == [1, 2, 3, 4]
        client.hello()
        assert mock.tick == 4
        terminal = client.step(episode=reset["episode"], tick=4, action=0, k=100)
        assert terminal["terminal"] == "death"
        assert terminal["tick"] == 50
        assert terminal["ticks_advanced"] == len(terminal["trace"]) == 46
        assert terminal["trace"][-1]["events"] == terminal["events"]
        next_reset = client.request("reset", start={"kind": "zero"})
        assert next_reset["tick"] == 0
        assert next_reset["episode"] != reset["episode"]
        with pytest.raises(RemoteError) as exc:
            client.step(episode=reset["episode"], tick=0, action=0, k=1)
        assert exc.value.code == ErrorCode.EPISODE_MISMATCH
        first_tick = client.step(episode=next_reset["episode"], tick=0, action=1, k=1)
        assert first_tick["trace"][0]["button"]["held"] is True
    assert mock.closed
    assert not mock.held


@pytest.mark.skipif(os.name != "nt", reason="requires Windows named pipes")
def test_mock_round_trip_over_windows_pipe():
    mock = MockBridge()
    name = PIPE_PREFIX + f"test-{os.getpid()}-{uuid4().hex}"
    done = Future()

    def serve():
        try:
            mock.serve_named_pipe(name)
        except BaseException as exc:
            done.set_exception(exc)
        else:
            done.set_result(None)

    Thread(target=serve, daemon=True).start()
    deadline = monotonic() + 3
    while True:
        try:
            transport = NamedPipeTransport(name)
            break
        except FileNotFoundError:
            if done.done():
                done.result()
            if monotonic() >= deadline:
                raise
            sleep(0.01)
    with BridgeClient(transport) as client:
        assert client.require_isolated()["capabilities"]["trace"] is True
        client.request("load_level", level=MOCK_LEVEL)
        reset = client.request("reset", start={"kind": "zero"})
        assert client.step(episode=reset["episode"], tick=0, action=1, k=4)["tick"] == 4
    done.result(timeout=3)
