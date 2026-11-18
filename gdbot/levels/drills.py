"""Build the fixed, seeded M3 fixtures and their YAML index."""

import argparse
import hashlib
import json
import random
from dataclasses import dataclass
from pathlib import Path

from ..replay import Tape
from .levelstring import LevelString

# IDs and property references are catalogued in levels/drills/README.md.
BLOCK = 1
SPIKE = 8
GRAVITY_NORMAL = 10
GRAVITY_REVERSED = 11
YELLOW_ORB = 36
SPEED_FAST = 202
MOVE = 901
GRID = 30
GROUND_ROW = GRID // 2
NORMAL_UNITS_PER_SECOND = 1.2982 * 240

NOTES = {
    "single-spike": "One normal floor spike per jump.",
    "double-spike": "Two consecutive floor spikes per jump.",
    "triple-spike": "Three consecutive floor spikes per jump.",
    "block-steps": "Two-step platforms with a shorter step down.",
    "pillar-gaps": "Raised pillars separated by floor-level spike gaps.",
    "yellow-orb": "Yellow orb above a wide floor spike bed.",
    "gravity-portal": "Flip onto a low ceiling, jump its inverted hazard, and return.",
    "speed-change": "Fast speed portal before staggered single and double spikes.",
    "moving-geometry": "Needs trigger support. One Move trigger lowers a grouped solid into the route.",
}


@dataclass(frozen=True)
class Drill:
    family: str
    variant: str
    split: str
    seed: int
    level: LevelString
    progress_ok_dx: bool = True

    @property
    def needs_trigger_support(self) -> bool:
        return self.family == "moving-geometry"

    @property
    def nominal_seconds_1x(self) -> float:
        return max(float(obj["2"]) for obj in self.level.objects) / NORMAL_UNITS_PER_SECOND


def _spikes(level: LevelString, x: int, count: int) -> None:
    for index in range(count):
        level.add(SPIKE, x + GRID * index, GROUND_ROW)


def _column(level: LevelString, x: int, height: int) -> None:
    for index in range(height):
        level.add(BLOCK, x, GROUND_ROW + GRID * index)


def _anchors(rng: random.Random, split: str) -> list[int]:
    # Held-out layouts are shifted and have a different gap sequence.
    x = GRID * rng.randint(15, 19) + (45 if split == "heldout" else 0)
    anchors = []
    for _ in range(5):
        anchors.append(x)
        x += GRID * rng.randint(23, 29)
    return anchors


def build_drill(family: str, split: str, seed: int) -> Drill:
    if family not in NOTES or split not in ("train", "heldout"):
        raise ValueError("unknown drill family or split")
    rng = random.Random(seed)
    level = LevelString()
    anchors = _anchors(rng, split)
    x = anchors[1]
    spike_counts = {"single-spike": 1, "double-spike": 2, "triple-spike": 3}

    if family in spike_counts:
        for anchor in anchors:
            _spikes(level, anchor, spike_counts[family])
    elif family == "block-steps":
        heights = (1, 2, 2, 1) if split == "train" else (1, 1, 2, 2, 1)
        for anchor in anchors[::2]:
            for index, height in enumerate(heights):
                _column(level, anchor + index * GRID, height)
    elif family == "pillar-gaps":
        gaps = (60, 90, 60) if split == "train" else (90, 60, 90)
        for anchor in anchors[1::2]:
            column = anchor
            _column(level, column, 1)
            for gap in gaps:
                _spikes(level, column + GRID, gap // GRID - 1)
                column += gap
                _column(level, column, 1)
    elif family == "yellow-orb":
        for anchor in anchors[1::2]:
            _spikes(level, anchor, 6)
            level.add(YELLOW_ORB, anchor + 60 + (8 if split == "heldout" else 0), 70)
    elif family == "gravity-portal":
        level.add(GRAVITY_REVERSED, x, GROUND_ROW)
        ceiling_y = 195
        for offset in range(-60, 631, GRID):
            level.add(BLOCK, x + offset, ceiling_y)
        hazard_x = x + (330 if split == "train" else 360)
        level.add(SPIKE, hazard_x, ceiling_y - GRID, rotation=180)
        level.add(GRAVITY_NORMAL, x + 540, ceiling_y - GRID)
    elif family == "speed-change":
        level.add(SPEED_FAST, anchors[0], GROUND_ROW)
        for index, anchor in enumerate(anchors[1:]):
            _spikes(level, anchor, 1 + (index + int(split == "heldout")) % 2)
    elif family == "moving-geometry":
        target_group = 1
        level.add(MOVE, x, 105, properties={10: 0.55, 29: -120, 51: target_group})
        level.add(BLOCK, x + (240 if split == "train" else 210), 135, properties={57: target_group})

    # A final jumpable tile keeps the natural level end beyond the practice section.
    level.add(BLOCK, GRID * rng.randint(165, 180), GROUND_ROW)
    level.objects.sort(key=lambda obj: (float(obj["2"]), float(obj["3"]), int(obj["1"])))
    return Drill(family, f"{split}-{seed}", split, seed, level)


def iter_drills():
    for index, family in enumerate(NOTES):
        for split, seed in (("train", 1100 + index), ("heldout", 2100 + index)):
            yield build_drill(family, split, seed)


def write_drills(output: Path, *, tape_root: Path | None = None) -> None:
    tape_root = output / "tapes" if tape_root is None else tape_root
    index = ["# Generated by python -m gdbot.levels.drills", "drills:"]
    for drill in iter_drills():
        relative = Path(drill.family) / f"{drill.variant}.txt"
        file = output / relative
        file.parent.mkdir(parents=True, exist_ok=True)
        # The file contains the exact bridge data, so the digest includes no newline.
        encoded = drill.level.encode()
        payload = encoded.encode("ascii")
        file.write_bytes(payload)
        digest = hashlib.sha256(payload).hexdigest()
        tape_relative = relative.with_suffix(".json")
        tape_path = tape_root / tape_relative
        has_tape = False
        if tape_path.is_file():
            tape = Tape.load(tape_path)
            has_tape = (
                tape.terminal == "complete" and tape.seed == drill.seed
                and tape.level.get("data") == encoded and tape.settings.get("drill_sha256") == digest
            )
            if not has_tape:
                raise ValueError(f"completion tape does not match {drill.family}/{drill.variant}")
        entry = {
            "family": drill.family,
            "variant": drill.variant,
            "split": drill.split,
            "seed": drill.seed,
            "path": relative.as_posix(),
            "sha256": digest,
            "notes": NOTES[drill.family],
            "progress_ok_dx": drill.progress_ok_dx,
            "needs_trigger_support": drill.needs_trigger_support,
            "training_ready": has_tape,
            "tape": (Path("tapes") / tape_relative).as_posix() if has_tape else None,
            "nominal_seconds_1x": round(drill.nominal_seconds_1x, 2),
        }
        for number, (key, value) in enumerate(entry.items()):
            prefix = "  - " if number == 0 else "    "
            index.append(f"{prefix}{key}: {json.dumps(value)}")
    (output / "index.yaml").write_text("\n".join(index) + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("levels/drills"))
    write_drills(parser.parse_args().output)
