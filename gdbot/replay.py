"""Input-edge tapes and exact per-tick trace comparison."""

import json
import math
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from itertools import zip_longest
from pathlib import Path
from time import sleep

from .protocol import BridgeClient, ProtocolError


@dataclass(frozen=True)
class Tape:
    build_hash: str
    level: dict
    level_revision: str
    settings: dict
    seed: int | None
    start: dict
    total_ticks: int
    edges: tuple[tuple[int, int], ...]
    terminal: str | None = None
    version: int = 1
    finish_wait: tuple[int, float] | None = None

    def __post_init__(self):
        if self.version != 1 or type(self.total_ticks) is not int or self.total_ticks < 0:
            raise ValueError("invalid tape version or tick count")
        if self.terminal not in (None, "death", "complete"):
            raise ValueError("invalid tape terminal event")
        if self.finish_wait is not None:
            tick, seconds = self.finish_wait
            if (self.terminal != "complete" or type(tick) is not int or not 0 < tick < self.total_ticks
                    or type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds <= 0):
                raise ValueError("invalid finish wait")
        previous_tick, previous_action = 0, 0
        for tick, action in self.edges:
            if type(tick) is not int or not previous_tick < tick <= self.total_ticks:
                raise ValueError("edge tick must increase within the tape")
            if type(action) is not int or action not in (0, 1) or action == previous_action:
                raise ValueError("tape edges must change the held action")
            previous_tick, previous_action = tick, action

    def save(self, path: str | Path) -> None:
        data = json.dumps(asdict(self), separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        Path(path).write_text(data + "\n", encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        data["edges"] = tuple(tuple(edge) for edge in data["edges"])
        if data.get("finish_wait") is not None:
            data["finish_wait"] = tuple(data["finish_wait"])
        return cls(**data)


def record(
    client: BridgeClient, level: dict, actions: Iterable[tuple[int, int]],
    *, settings: dict, seed: int | None = None, start: dict | None = None,
) -> Tape:
    """Record (action, k) commands; edge ticks are one-based."""
    hello = client.require_isolated()
    loaded = client.load_level(level)
    start = {"kind": "zero"} if start is None else start
    reset = client.request("reset", start=start)
    tick, held, terminal = 0, 0, None
    edges = []
    for action, count in actions:
        reply = client.step(episode=reset["episode"], tick=tick, action=action, k=count)
        if action != held:
            edges.append((tick + 1, action))
        held, tick, terminal = action, reply["tick"], reply["terminal"]
        if terminal:
            break
    return Tape(
        hello["build"]["exe_sha256"], level, loaded["revision"], settings, seed, start,
        tick, tuple(edges), terminal,
    )


def replay(
    client: BridgeClient, tape: Tape, *, settings: dict, seed: int | None = None,
    mode: str | None = None, trace: bool = True, chunk_ticks: int = 240,
) -> list[dict]:
    """Replay with caller-verified settings and seed; v0 has no settings or RNG setter."""
    if type(chunk_ticks) is not int or chunk_ticks < 1:
        raise ValueError("chunk_ticks must be a positive integer")
    if settings != tape.settings or seed != tape.seed:
        raise ValueError("replay settings or seed do not match the tape")
    hello = client.require_isolated()
    if hello["build"]["exe_sha256"] != tape.build_hash:
        raise ProtocolError("replay build does not match the tape")
    if trace and hello["capabilities"].get("trace") is not True:
        raise ProtocolError("bridge does not support traces")
    loaded = client.load_level(tape.level)
    if loaded["revision"] != tape.level_revision:
        raise ProtocolError("replay level revision does not match the tape")
    if mode is not None:
        client.request("set_mode", mode=mode)
    reset = client.request("reset", start=tape.start)
    if trace:
        client.request("trace", enabled=True)
    rows = []
    tick, held, terminal = 0, 0, None
    edges = iter(tape.edges)
    edge = next(edges, None)
    wait_tick, wait_seconds = tape.finish_wait or (-1, 0)
    try:
        while tick < tape.total_ticks and not terminal:
            if edge is not None and edge[0] == tick + 1:
                held = edge[1]
                edge = next(edges, None)
            stop = edge[0] - 1 if edge is not None else tape.total_ticks
            if tick == wait_tick:
                # Native completion can be reported by a wall-clock scene callback.
                sleep(wait_seconds)
            elif tick < wait_tick:
                stop = min(stop, wait_tick)
            count = min(stop - tick, chunk_ticks)
            reply = client.step(episode=reset["episode"], tick=tick, action=held, k=count)
            terminal = reply["terminal"]
            if trace:
                batch = reply.get("trace")
                if not isinstance(batch, list) or [row.get("tick") for row in batch] != list(range(tick + 1, reply["tick"] + 1)):
                    raise ProtocolError("bridge did not return one trace row per advanced tick")
                # v0 may report the terminal event only in the step envelope.
                if terminal is not None:
                    batch[-1] = {**batch[-1], "terminal": terminal}
                rows.extend(batch)
            tick = reply["tick"]
        if not trace and (tick != tape.total_ticks or terminal != tape.terminal):
            raise ProtocolError(f"replay terminal diverged at tick {tick}: {terminal!r}")
    except BaseException:
        if trace:
            try:
                client.request("trace", enabled=False)
            except (ProtocolError, OSError, EOFError):
                pass
        raise
    if trace:
        client.request("trace", enabled=False)
    return rows


@dataclass(frozen=True)
class TraceDifference:
    tick: int
    field: str
    expected: object
    actual: object


_MISSING = object()


def _first_difference(expected, actual, path: str):
    if isinstance(expected, dict) and isinstance(actual, dict):
        for key in sorted(expected.keys() | actual.keys()):
            field = f"{path}.{key}" if path else key
            result = _first_difference(expected.get(key, _MISSING), actual.get(key, _MISSING), field)
            if result is not None:
                return result
    elif isinstance(expected, list) and isinstance(actual, list):
        for index, (left, right) in enumerate(zip_longest(expected, actual, fillvalue=_MISSING)):
            result = _first_difference(left, right, f"{path}[{index}]")
            if result is not None:
                return result
    elif type(expected) is not type(actual) or expected != actual:
        return path, expected, actual
    return None


def diff_traces(expected: Iterable[dict], actual: Iterable[dict]) -> TraceDifference | None:
    for left, right in zip_longest(expected, actual, fillvalue=_MISSING):
        if left is _MISSING:
            return TraceDifference(right["tick"], "row", "<missing>", right)
        if right is _MISSING:
            return TraceDifference(left["tick"], "row", left, "<missing>")
        if left["tick"] != right["tick"]:
            return TraceDifference(min(left["tick"], right["tick"]), "tick", left["tick"], right["tick"])
        difference = _first_difference(left, right, "")
        if difference is not None:
            field, previous, current = difference
            return TraceDifference(
                left["tick"], field,
                "<missing>" if previous is _MISSING else previous,
                "<missing>" if current is _MISSING else current,
            )
    return None
