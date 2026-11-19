"""Per-attempt section telemetry for the per-mode performance ratings (docs/TELEMETRY.md).

A *section* is a maximal stretch of one game mode at one speed (mini and dual are part of the key
too). For every attempt, each section the player enters yields one JSONL row: how long it survived
inside, and whether it died there, got through (`cleared`), or the attempt stopped while inside
(censored: both false).

Stable section IDs: a section is the integer x where its boundary sits in the level (0 for the
level start, 1234 for a boundary first seen at x=1234). Boundaries are learned per level as
attempts cross them and persisted, so checkpoint/start-position attempts that begin mid-level map
to the same IDs as runs from zero.
"""
import bisect
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

MATCH_X = 60.0  # a boundary within 2 blocks of a known one is the same boundary


def _state(player: dict) -> tuple:
    return (player.get("mode", "cube"), round(float(player.get("speed", 1.0)), 2), bool(player.get("mini", False)))


@dataclass
class SectionMap:
    """Known section boundaries of one level: sorted x positions (the level start is implicit)."""
    boundaries: list = field(default_factory=list)

    def match(self, x: float) -> float:
        """Return the canonical boundary for a transition seen at x, registering it if new."""
        i = bisect.bisect_left(self.boundaries, x)
        for j in (i - 1, i):
            if 0 <= j < len(self.boundaries) and abs(self.boundaries[j] - x) <= MATCH_X:
                return self.boundaries[j]
        self.boundaries.insert(i, round(x, 1))
        return self.boundaries[i]

    def containing(self, x: float) -> float | None:
        """The boundary of the section containing x (None = the level-start section)."""
        i = bisect.bisect_right(self.boundaries, x)
        return self.boundaries[i - 1] if i else None

    @staticmethod
    def name(boundary: float | None) -> int:
        return 0 if boundary is None else max(1, int(round(boundary)))


class SectionMaps:
    """Per-level SectionMap registry persisted as JSON so IDs stay stable across runs."""

    def __init__(self, path: Path):
        self.path = Path(path)
        raw = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
        self.maps = {level: SectionMap(sorted(b)) for level, b in raw.items()}

    def get(self, level: str) -> SectionMap:
        return self.maps.setdefault(level, SectionMap())

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({k: v.boundaries for k, v in sorted(self.maps.items())}, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)


class SectionRecorder:
    """Feed one attempt's player states in tick order; collect section rows.

    begin(...) once per attempt, observe(tick, players) after every step (k ticks is fine: section
    timing is then exact to k ticks), end(terminal, tick) when the attempt stops.
    """

    def __init__(self, section_map: SectionMap):
        self.map = section_map
        self.rows = []
        self._open = None
        self._meta = None

    def begin(self, meta: dict, tick: int, players: list) -> None:
        if self._open is not None:
            raise RuntimeError("previous attempt not ended")
        self._meta = dict(meta)
        p = players[0]
        start_x = float(p["x"])
        # From zero the first section is the level start; from a checkpoint it is whichever known
        # section contains the start x (a new boundary is learned the first time it is crossed).
        boundary = self.map.containing(start_x) if self._meta.get("start") != "zero" else None
        self._enter(boundary, tick, players)

    def observe(self, tick: int, players: list) -> None:
        if self._open is None:
            raise RuntimeError("observe before begin")
        state = _state(players[0]) + (len(players) > 1,)
        if state != self._open["_state"]:
            boundary = self.map.match(float(players[0]["x"]))
            self._close(tick, players, died=False, cleared=True)
            self._enter(boundary, tick, players)

    def end(self, terminal: str | None, tick: int, players: list) -> list:
        """terminal: "death", "complete", or None (stopped/timeout: the open section is censored)."""
        if self._open is None:
            raise RuntimeError("end before begin")
        self._close(tick, players, died=terminal == "death", cleared=terminal == "complete")
        rows, self.rows, self._meta = self.rows, [], None
        return rows

    def _enter(self, boundary, tick, players):
        p = players[0]
        mode, speed, mini = _state(p)
        self._open = {"section": SectionMap.name(boundary), "mode": mode, "speed": speed, "mini": mini,
                      "dual": len(players) > 1, "entry_tick": int(tick), "entry_x": round(float(p["x"]), 1),
                      "_state": (mode, speed, mini, len(players) > 1)}

    def _close(self, tick, players, *, died, cleared):
        row = {k: v for k, v in self._open.items() if not k.startswith("_")}
        ticks = int(tick) - row["entry_tick"]
        if ticks <= 0 and not died:
            self._open = None  # zero-length (two transitions inside one step): no evidence
            return
        row.update(exit_tick=int(tick), exit_x=round(float(players[0]["x"]), 1),
                   ticks_in_section=max(1, ticks), died=bool(died), cleared=bool(cleared))
        self.rows.append({**self._meta, **row})
        self._open = None


class TelemetryWriter:
    """Appends rows to build/telemetry/<run>.jsonl and keeps the shared section maps."""

    def __init__(self, run: str, root: Path | None = None):
        root = Path(root) if root else Path(__file__).resolve().parents[1] / "build" / "telemetry"
        root.mkdir(parents=True, exist_ok=True)
        self.run = run
        self.path = root / f"{run}.jsonl"
        self.maps = SectionMaps(root / "section_maps.json")

    def recorder(self, level: str) -> SectionRecorder:
        return SectionRecorder(self.maps.get(level))

    def write(self, rows: list) -> None:
        if not rows:
            return
        stamp = round(time.time(), 3)
        with self.path.open("a", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps({"run": self.run, "t": stamp, **row}, separators=(",", ":")) + "\n")
        self.maps.save()


def attempt_meta(*, level: str, attempt: int, start: str, generation: int = 0, seed: int | None = None,
                 zero_shot: bool = False, practice: bool = False) -> dict:
    """Standard attempt fields. level: "drill:<family>/<variant>", "official:<n>" or "online:<id>".
    start: "zero" | "checkpoint" | "startpos". zero_shot only for the first attempt from zero on an
    unseen level."""
    if type(generation) is not int or generation < 0 or type(attempt) is not int or attempt < 1:
        raise ValueError("generation must be an int >= 0 and attempt an int >= 1")
    if start not in ("zero", "checkpoint", "startpos"):
        raise ValueError("start must be zero, checkpoint or startpos")
    if zero_shot and (start != "zero" or attempt != 1):
        raise ValueError("zero_shot is only the first attempt from zero")
    return {"level": level, "attempt": attempt, "start": start, "generation": generation, "seed": seed,
            "zero_shot": zero_shot, "practice": practice}


class EnvTelemetry:
    """Two-call adapter for GDEnv-based runners:

        tel = EnvTelemetry(env, TelemetryWriter("m5-gen3-seed1207"))
        obs, info = env.reset(...);  tel.started(attempt_meta(level=..., attempt=n, start="zero"))
        obs, r, term, trunc, info = env.step(a);  tel.stepped(info, term, trunc)

    Rows are written when the attempt ends (death, completion, truncation). Call stopped() if the
    runner abandons an attempt mid-way (the open section is then censored).
    """

    def __init__(self, env, writer: TelemetryWriter):
        self.env, self.writer, self.rec = env, writer, None

    def started(self, meta: dict) -> None:
        self.rec = self.writer.recorder(meta["level"])
        self.rec.begin(meta, self.env.tick, self.env.raw_observation["players"])

    def stepped(self, info: dict, terminated: bool, truncated: bool) -> None:
        if self.rec is None:
            return
        players = self.env.raw_observation["players"]
        if terminated or truncated:
            self.writer.write(self.rec.end(info.get("terminal") if terminated else None, info["tick"], players))
            self.rec = None
        else:
            self.rec.observe(info["tick"], players)

    def stopped(self) -> None:
        if self.rec is not None:
            self.writer.write(self.rec.end(None, self.env.tick, self.env.raw_observation["players"]))
            self.rec = None
