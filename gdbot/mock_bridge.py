"""Deterministic toy bridge for testing protocol behavior without a game."""

import hashlib
import json
import os

from .protocol import (
    PHYSICS_HZ, PIPE_PREFIX, VERSION, BridgeClient, ErrorCode, InProcessTransport,
    pack_frame, read_frame, write_bytes,
)

MOCK_BUILD = hashlib.sha256(b"gdbot-toy-bridge-v0").hexdigest()
MOCK_LEVEL = {"kind": "local", "name": "toy"}
_MODES = ("normal", "dedicated", "background")
_LENGTH = 20.0
_HAZARDS = (5.0, 14.0)


class _RequestError(Exception):
    def __init__(self, code: ErrorCode, message: str):
        super().__init__(message)
        self.code = code


class MockBridge:
    def __init__(self, *, saves_redirected: bool = True, http_blocked: bool = True):
        self.isolation = {"saves_redirected": saves_redirected, "http_blocked": http_blocked}
        self.level = None
        self.episode = 0
        self.in_episode = False
        self.tick = 0
        self.held = False
        self.trace_enabled = False
        self.mode = "normal"
        self.closed = False
        self._operations = {
            "hello": self._hello,
            "load_level": self._load_level,
            "reset": self._reset,
            "step": self._step,
            "set_mode": self._set_mode,
            "trace": self._trace,
            "bye": self._bye,
        }

    def client(self) -> BridgeClient:
        """Connect an in-process client to this mock session."""
        return BridgeClient(InProcessTransport(self.handle))

    def serve_named_pipe(self, name: str) -> None:
        """Serve a single mock session over a local Windows byte-mode pipe."""
        if os.name != "nt":
            raise OSError("Windows named pipes require Windows")
        if not name.lower().startswith(PIPE_PREFIX):
            raise ValueError("expected a local gdbot named pipe")
        import _winapi
        import msvcrt

        reject_remote_clients = 0x08
        handle = _winapi.CreateNamedPipe(
            name, _winapi.PIPE_ACCESS_DUPLEX | _winapi.FILE_FLAG_FIRST_PIPE_INSTANCE,
            _winapi.PIPE_WAIT | reject_remote_clients, 1, 65_536, 65_536, 0, _winapi.NULL,
        )
        try:
            try:
                _winapi.ConnectNamedPipe(handle)
            except OSError as exc:
                if exc.winerror != _winapi.ERROR_PIPE_CONNECTED:
                    raise
            fd = msvcrt.open_osfhandle(handle, os.O_RDWR | os.O_BINARY)
        except BaseException:
            _winapi.CloseHandle(handle)
            raise

        with os.fdopen(fd, "r+b", buffering=0) as stream:
            try:
                while not self.closed:
                    write_bytes(stream, pack_frame(self.handle(read_frame(stream))))
                # The client reads the bye reply before closing its handle.
                stream.read(1)
            except (BrokenPipeError, EOFError):
                pass
            finally:
                self.closed = True
                self.held = False

    def handle(self, request: dict) -> dict:
        if self.closed:
            raise EOFError("mock bridge is closed")
        request_id = request.get("id")
        try:
            op = request.get("op")
            if type(request_id) is not int or not isinstance(op, str):
                raise _RequestError(ErrorCode.BAD_REQUEST, "expected integer id and string op")
            handler = self._operations.get(op)
            if handler is None:
                raise _RequestError(ErrorCode.UNKNOWN_OP, op)
            return {"id": request_id, "ok": True, **handler(request)}
        except _RequestError as exc:
            return {"id": request_id, "ok": False, "error": {"code": exc.code, "msg": str(exc)}}

    def _hello(self, request: dict) -> dict:
        if type(request.get("proto")) is not int or request["proto"] != VERSION:
            raise _RequestError(ErrorCode.UNSUPPORTED, "unsupported protocol version")
        return {
            "proto": VERSION,
            "build": {"exe_sha256": MOCK_BUILD, "game_version": "mock-v0"},
            "capabilities": {
                "step": True, "reset": True, "startpos": False, "checkpoint": False,
                "trace": True, "modes": list(_MODES), "dual": False,
                "isolation": all(self.isolation.values()),
            },
            "isolation": self.isolation.copy(),
        }

    def _load_level(self, request: dict) -> dict:
        level = request.get("level")
        if not isinstance(level, dict):
            raise _RequestError(ErrorCode.BAD_REQUEST, "expected a level object")
        kind = level.get("kind")
        if kind == "level_string":
            raise _RequestError(ErrorCode.UNSUPPORTED, "inline level strings are reserved")
        if kind == "local" and isinstance(level.get("name"), str) and level["name"]:
            selector = {"kind": kind, "name": level["name"]}
        elif kind in ("main", "cached") and type(level.get("id")) is int:
            selector = {"kind": kind, "id": level["id"]}
        else:
            raise _RequestError(ErrorCode.BAD_REQUEST, "invalid level selector")
        revision = hashlib.sha256(json.dumps(selector, sort_keys=True).encode()).hexdigest()
        self.level = {
            "id": None, "name": f"Toy {kind}", **selector,
            "revision": revision, "length_x": _LENGTH,
        }
        self.in_episode = False
        self.held = False
        return {"level": self.level}

    def _reset(self, request: dict) -> dict:
        if self.level is None:
            raise _RequestError(ErrorCode.NOT_IN_LEVEL, "load a level before reset")
        start = request.get("start")
        if not isinstance(start, dict) or start.get("kind") not in ("zero", "startpos", "checkpoint"):
            raise _RequestError(ErrorCode.BAD_REQUEST, "invalid reset start")
        if start["kind"] != "zero":
            raise _RequestError(ErrorCode.UNSUPPORTED, "mock supports only zero starts")
        self.episode += 1
        self.in_episode = True
        self.tick = 0
        self.held = False
        self.y = self.vy = 0.0
        self.terminal = None
        return {"episode": self.episode, "tick": self.tick, "obs": self._observation()}

    def _step(self, request: dict) -> dict:
        if not self.in_episode:
            raise _RequestError(ErrorCode.NOT_IN_LEVEL, "reset before stepping")
        episode, action, count = (request.get(key) for key in ("episode", "action", "k"))
        if type(episode) is not int or type(action) is not int or action not in (0, 1) or type(count) is not int or count < 1:
            raise _RequestError(ErrorCode.BAD_REQUEST, "expected integer episode, binary action, and positive k")
        if episode != self.episode:
            raise _RequestError(ErrorCode.EPISODE_MISMATCH, "stale episode")
        if self.terminal:
            raise _RequestError(ErrorCode.NOT_IN_LEVEL, "terminal episode must be reset")
        before = self.tick
        if action and not self.held and self.y == 0:
            self.vy = 18.0
        self.held = bool(action)
        trace = []
        events = []
        for _ in range(count):
            self.tick += 1
            self.vy -= 100.0 / PHYSICS_HZ
            self.y += self.vy / PHYSICS_HZ
            if self.y <= 0:
                self.y = self.vy = 0.0
            if any(x <= self.x < x + 0.7 for x in _HAZARDS) and self.y < 0.45:
                self.terminal = "death"
            elif self.x >= _LENGTH:
                self.terminal = "complete"
            if self.terminal:
                events.append({"type": self.terminal, "tick": self.tick})
            if self.trace_enabled:
                trace.append({
                    "tick": self.tick, "players": [self._player()],
                    "button": {"held": self.held, "queued": 0},
                    "events": events.copy() if self.terminal else [],
                })
            if self.terminal:
                break
        reply = {
            "episode": self.episode, "tick": self.tick, "ticks_advanced": self.tick - before,
            "obs": self._observation(), "events": events, "terminal": self.terminal,
        }
        if self.trace_enabled:
            reply["trace"] = trace
        return reply

    @property
    def x(self) -> float:
        return self.tick / 10

    def _player(self) -> dict:
        return {
            "x": self.x, "y": self.y, "vx": 0.1, "vy": self.vy, "rot": 0.0,
            "mode": "cube", "speed": 1.0, "gravity_flipped": False, "mini": False,
            "on_ground": self.y == 0, "on_ceiling": False, "holding": self.held,
            "buffered": False, "dashing": False, "dead": self.terminal == "death",
        }

    def _observation(self) -> dict:
        objects = [
            {"uid": index, "cat": "hazard", "type_id": 1, "x": x, "y": 0.2,
             "w": 0.7, "h": 0.4, "rot": 0.0, "active": True, "params": {}}
            for index, x in enumerate(_HAZARDS, start=1)
            if -2 <= x - self.x <= 10
        ]
        return {
            "players": [self._player()], "objects": objects, "progress": min(1.0, self.x / _LENGTH),
            "window": {"ahead_x": 10.0, "behind_x": 2.0, "max_objects": 2, "truncated": False},
            "unsupported": [],
        }

    def _set_mode(self, request: dict) -> dict:
        mode = request.get("mode")
        if mode not in _MODES:
            raise _RequestError(ErrorCode.UNSUPPORTED, "unknown mode")
        self.mode = mode
        return {}

    def _trace(self, request: dict) -> dict:
        if type(request.get("enabled")) is not bool:
            raise _RequestError(ErrorCode.BAD_REQUEST, "expected boolean enabled")
        self.trace_enabled = request["enabled"]
        return {}

    def _bye(self, request: dict) -> dict:
        self.held = False
        self.closed = True
        return {}
