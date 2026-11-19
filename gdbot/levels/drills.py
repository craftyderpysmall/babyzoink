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
MODE_PORTALS = {
    "cube": 12, "ship": 13, "ball": 47, "ufo": 111, "wave": 660,
    "robot": 745, "spider": 1331, "swing": 1933,
}
MINI_PORTAL = 101
PADS = {"yellow": 35, "pink": 140, "blue": 67}
ORBS = {"pink": 141, "blue": 84, "green": 1022, "black": 1330, "dash": 1704}
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

M5_NOTES = {
    "ship-corridor": "Alternate between broad upper and lower ship openings.",
    "ball-switches": "Switch gravity between the floor and a low ceiling.",
    "ufo-taps": "Lift with short UFO taps over two low obstacles.",
    "wave-corridor": "Alternate short wave climbs and dives through broad openings.",
    "robot-jumps": "Use a short jump and a longer held jump over different heights.",
    "spider-switches": "Teleport between the ground and a low ceiling.",
    "swing-corridor": "Invert thrust to thread alternating broad openings.",
    "yellow-pad": "Use the yellow pad to launch over a low hazard strip.",
    "pink-pad": "Use the weaker pink pad over a shorter hazard strip.",
    "blue-pad": "Use the blue pad to reach a low ceiling and return to normal gravity.",
    "pink-orb": "Chain a pink orb press out of a normal cube jump.",
    "blue-orb": "Press a blue orb to invert gravity onto the ceiling before returning.",
    "green-orb": "Press a green orb to flip and launch toward the ceiling.",
    "black-orb": "Use a black orb to land under a low hanging hazard.",
    "dash-orb": "Hold a horizontal dash over a short floor hazard strip.",
    "mini-cube": "Enter a mini portal before two single-spike jumps.",
    "ship-to-ball": "Fly across a short ship section before switching into ball.",
    "ufo-to-wave": "Tap through a low UFO obstacle and finish a wave section.",
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


def _ceiling(level, start, stop, y):
    for x in range(start, stop + 1, GRID):
        level.add(BLOCK, x, y)


def _mode_section(level, mode, entry, span, offset):
    first = entry + 240 + offset
    second = first + 270
    if mode in ("ship", "wave", "swing"):
        for x in (first, first + GRID):
            _column(level, x, 3)
        for x in (second, second + GRID):
            for y in (165, 195, 225, 255, 285):
                level.add(BLOCK, x, y)
    elif mode in ("ball", "spider"):
        _ceiling(level, entry - 30, entry + span, 165)
        _spikes(level, first, 2)
        level.add(SPIKE, second, 135, rotation=180)
    elif mode == "ufo":
        _column(level, first, 2)
        _spikes(level, second, 2)
    elif mode == "robot":
        _column(level, first, 1)
        _column(level, second, 2)


def build_m5_drill(family: str, split: str, seed: int) -> Drill:
    if family not in M5_NOTES or split not in ("train", "validation", "heldout"):
        raise ValueError("unknown M5 drill family or split")
    rng = random.Random(seed)
    level = LevelString()
    variant_offset = {"train": 0, "validation": GRID, "heldout": 2 * GRID}[split]
    # Disjoint entry ranges keep the three splits distinct even if their jitter matches.
    entry = GRID * rng.randint(8, 11) + 4 * variant_offset
    offset = GRID * rng.randrange(3) + variant_offset
    mode_families = {
        "ship-corridor": "ship", "ball-switches": "ball", "ufo-taps": "ufo",
        "wave-corridor": "wave", "robot-jumps": "robot", "spider-switches": "spider",
        "swing-corridor": "swing",
    }
    bridge = entry + 900
    final_x = bridge + 210
    if family in mode_families:
        mode = mode_families[family]
        level.add(MODE_PORTALS[mode], entry, GROUND_ROW)
        _mode_section(level, mode, entry, 840, offset)
    elif family.endswith("-pad"):
        kind = family.removesuffix("-pad")
        level.add(PADS[kind], entry, GROUND_ROW - 12)
        if kind == "blue":
            _ceiling(level, entry - GRID, entry + 450, 165)
            _spikes(level, entry + 120, 2)
            level.add(GRAVITY_NORMAL, entry + 390 + offset, 135)
        else:
            _spikes(level, entry + (45 if kind == "pink" else 60), 1 if kind == "pink" else 3)
            _spikes(level, entry + 510 + offset, 1)
    elif family.endswith("-orb"):
        kind = family.removesuffix("-orb")
        x = entry + 150 + offset
        level.add(ORBS[kind], x, 65 if kind != "dash" else 75)
        _spikes(level, x + (120 if kind == "green" else 30), 4 if kind == "dash" else 2)
        if kind in ("blue", "green"):
            _ceiling(level, x - 90, x + 480, 195)
            level.add(GRAVITY_NORMAL, x + 390, 165)
        elif kind == "black":
            level.add(BLOCK, x + 150, 105)
    elif family == "mini-cube":
        level.add(MINI_PORTAL, entry, GROUND_ROW)
        _spikes(level, entry + 240 + offset, 1)
        _spikes(level, entry + 510 + offset, 1)
    else:
        first, second = family.split("-to-")
        level.add(MODE_PORTALS[first], entry, GROUND_ROW)
        _mode_section(level, first, entry, 840, offset)
        # A portal column covers the safe vertical band of the first mode.
        for y in (45, 105, 165, 225):
            level.add(MODE_PORTALS[second], bridge, y)
        _mode_section(level, second, bridge, 840, offset)
        final_x = bridge + 1110
    # A high marker defines the end without adding a floor hazard at the finish.
    level.add(BLOCK, final_x, 450)
    level.objects.sort(key=lambda obj: (float(obj["2"]), float(obj["3"]), int(obj["1"])))
    return Drill(family, f"{split}-{seed}", split, seed, level)


def iter_m5_drills():
    for index, family in enumerate(M5_NOTES):
        for split, base in (("train", 5100), ("validation", 6100), ("heldout", 7100)):
            yield build_m5_drill(family, split, base + index)


def write_drills(output: Path, *, tape_root: Path | None = None, m5: bool = False) -> None:
    tape_root = output / "tapes" if tape_root is None else tape_root
    index = ["# Generated by python -m gdbot.levels.drills", "drills:"]
    for drill in iter_m5_drills() if m5 else iter_drills():
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
            "notes": (M5_NOTES if m5 else NOTES)[drill.family],
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
    parser.add_argument("--output", type=Path)
    parser.add_argument("--m5", action="store_true")
    options = parser.parse_args()
    default = Path("levels/drills/m5" if options.m5 else "levels/drills")
    write_drills(options.output or default, m5=options.m5)
