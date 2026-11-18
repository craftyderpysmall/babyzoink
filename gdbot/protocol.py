"""Protocol v0 framing and synchronous bridge client."""

import io
import json
import os
import struct
from collections.abc import Callable
from enum import StrEnum
from typing import BinaryIO, Protocol

VERSION = 0
PHYSICS_HZ = 240
_LENGTH = struct.Struct("<I")
MAX_FRAME_BYTES = 64 * 1024 * 1024
PIPE_PREFIX = "\\\\.\\pipe\\gdbot-"


class ErrorCode(StrEnum):
    BAD_REQUEST = "BAD_REQUEST"
    UNKNOWN_OP = "UNKNOWN_OP"
    NOT_IN_LEVEL = "NOT_IN_LEVEL"
    UNSUPPORTED = "UNSUPPORTED"
    BUILD_MISMATCH = "BUILD_MISMATCH"
    EPISODE_MISMATCH = "EPISODE_MISMATCH"
    INTERNAL = "INTERNAL"


class ProtocolError(RuntimeError):
    """Invalid frame or reply."""


class RemoteError(ProtocolError):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code


def pack_frame(message: dict) -> bytes:
    if not isinstance(message, dict):
        raise ProtocolError("frame must contain a JSON object")
    try:
        payload = json.dumps(message, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, TypeError) as exc:
        raise ProtocolError("message cannot be encoded as JSON") from exc
    if len(payload) > MAX_FRAME_BYTES:
        raise ProtocolError("frame exceeds maximum size")
    return _LENGTH.pack(len(payload)) + payload


def _read_exact(stream: BinaryIO, size: int) -> bytes:
    data = bytearray()
    while len(data) < size:
        chunk = stream.read(size - len(data))
        if not chunk:
            raise EOFError("bridge closed before the frame was complete")
        data.extend(chunk)
    return bytes(data)


def _reject_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant {value}")


def read_frame(stream: BinaryIO) -> dict:
    (size,) = _LENGTH.unpack(_read_exact(stream, _LENGTH.size))
    if not 0 < size <= MAX_FRAME_BYTES:
        raise ProtocolError(f"invalid frame size {size}")
    try:
        message = json.loads(_read_exact(stream, size).decode("utf-8"), parse_constant=_reject_constant)
    except (UnicodeError, ValueError) as exc:
        raise ProtocolError("invalid JSON payload") from exc
    if not isinstance(message, dict):
        raise ProtocolError("frame must contain a JSON object")
    return message


def write_bytes(stream: BinaryIO, data: bytes) -> None:
    pending = memoryview(data)
    while pending:
        written = stream.write(pending)
        if not written:
            raise EOFError("bridge stopped accepting data")
        pending = pending[written:]


def _unpack_frame(data: bytes) -> dict:
    stream = io.BytesIO(data)
    message = read_frame(stream)
    if stream.read(1):
        raise ProtocolError("unexpected data after frame")
    return message


class Transport(Protocol):
    def exchange(self, frame: bytes) -> dict: ...
    def close(self) -> None: ...


class InProcessTransport:
    """Exercise the same JSON codec as the pipe without a separate process."""

    def __init__(self, handle: Callable[[dict], dict]):
        self.handle = handle
        self.closed = False

    def exchange(self, frame: bytes) -> dict:
        if self.closed:
            raise EOFError("bridge transport is closed")
        return _unpack_frame(pack_frame(self.handle(_unpack_frame(frame))))

    def close(self) -> None:
        self.closed = True


class NamedPipeTransport:
    def __init__(self, name: str):
        if os.name != "nt":
            raise OSError("Windows named pipes require Windows")
        if not name.lower().startswith(PIPE_PREFIX):
            raise ValueError("expected a local gdbot named pipe")
        self.stream = open(name, "r+b", buffering=0)

    def exchange(self, frame: bytes) -> dict:
        write_bytes(self.stream, frame)
        return read_frame(self.stream)

    def close(self) -> None:
        self.stream.close()


class BridgeClient:
    """One client owns one strictly alternating request/reply stream."""

    def __init__(self, transport: Transport):
        self.transport = transport
        self._next_id = 1
        self._closed = False
        self._level_selector = None
        self._loaded_level = None

    def request(self, op: str, **fields) -> dict:
        if self._closed:
            raise ProtocolError("bridge client is closed")
        if "id" in fields:
            raise ValueError("request IDs are assigned by the client")
        request_id = self._next_id
        self._next_id += 1
        frame = pack_frame({"op": op, "id": request_id, **fields})
        try:
            reply = self.transport.exchange(frame)
            if type(reply.get("id")) is not int or reply["id"] != request_id:
                raise ProtocolError(f"unexpected reply ID for {op}")
            if type(reply.get("ok")) is not bool:
                raise ProtocolError(f"missing reply status for {op}")
            if not reply["ok"]:
                error = reply.get("error")
                if not isinstance(error, dict) or not all(isinstance(error.get(key), str) for key in ("code", "msg")):
                    raise ProtocolError(f"malformed error reply for {op}")
                raise RemoteError(error["code"], error["msg"])
        except RemoteError as exc:
            if exc.code == ErrorCode.BUILD_MISMATCH:
                self._discard()
            raise
        except (EOFError, OSError, ProtocolError):
            self._discard()
            raise
        if op == "load_level":
            self._level_selector = fields["level"].copy()
            self._loaded_level = reply["level"].copy()
        elif op == "quit_level":
            self._level_selector = None
            self._loaded_level = None
        return reply

    def load_level(self, level: dict) -> dict:
        """Reuse the current scene for the same selector so a reset can follow."""
        if self._closed:
            raise ProtocolError("bridge client is closed")
        if self._loaded_level is None or level != self._level_selector:
            return self.request("load_level", level=level)["level"]
        return self._loaded_level.copy()

    def hello(self) -> dict:
        reply = self.request("hello", proto=VERSION, client="gdbot/0.1")
        if type(reply.get("proto")) is not int or reply["proto"] != VERSION:
            self._discard()
            raise ProtocolError("unsupported bridge protocol")
        return reply

    def require_isolated(self) -> dict:
        reply = self.hello()
        isolation = reply.get("isolation")
        if not isinstance(isolation, dict) or any(
            isolation.get(key) is not True for key in ("saves_redirected", "http_blocked")
        ):
            self._discard()
            raise ProtocolError("bridge must confirm save redirection and HTTP blocking")
        return reply

    def step(self, *, episode: int, tick: int, action: int, k: int) -> dict:
        if type(action) is not int or action not in (0, 1) or type(k) is not int or k < 1:
            raise ValueError("step expects a binary action and a positive tick count")
        reply = self.request("step", episode=episode, action=action, k=k)
        advanced = reply.get("ticks_advanced")
        terminal = reply.get("terminal")
        if (
            reply.get("episode") != episode or type(advanced) is not int
            or not 1 <= advanced <= k or reply.get("tick") != tick + advanced
            or "terminal" not in reply or terminal not in (None, "death", "complete")
            or (terminal is None and advanced != k)
        ):
            self._discard()
            raise ProtocolError("bridge violated the step tick contract")
        return reply

    def _discard(self) -> None:
        self._closed = True
        self.transport.close()

    def close(self) -> None:
        if self._closed:
            return
        try:
            self.request("bye")
        finally:
            if not self._closed:
                self._discard()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()
