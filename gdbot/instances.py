"""Find and launch parallel bridge instances.

Slot 0 is the original single-instance layout: discovery in game/2.2091/gdbot/bridge.json, save in
gdbot/save/. Slot N >= 1 (started with `gdbot-launch.exe --instance N`) keeps its discovery, log and
save in gdbot/inst<N>/. mode.txt (the user's dedicated/background toggle) stays shared in gdbot/,
so one toggle drives every instance.
"""
import json
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GAME = ROOT / "game" / "2.2091"
BOT = GAME / "gdbot"
LAUNCHER = ROOT / "mod" / "build" / "Release" / "gdbot-launch.exe"


def instance_dir(slot: int = 0) -> Path:
    if type(slot) is not int or not 0 <= slot <= 63:
        raise ValueError("slot must be an int in 0..63")
    return BOT if slot == 0 else BOT / f"inst{slot}"


def discovery(slot: int = 0) -> dict:
    """The slot's bridge.json: {"pipe", "pid", "proto", "instance"} ("instance" absent on older bridges)."""
    return json.loads((instance_dir(slot) / "bridge.json").read_text(encoding="utf-8"))


def launch(slot: int, *, launcher: Path = LAUNCHER, timeout_s: float = 90.0) -> dict:
    """Start a launcher-owned GD for `slot` and return its fresh discovery record."""
    path = instance_dir(slot) / "bridge.json"
    before = path.stat().st_mtime_ns if path.exists() else None
    args = [str(launcher)] + (["--instance", str(slot)] if slot else [])
    done = subprocess.run(args, capture_output=True, text=True, timeout=timeout_s)
    if done.returncode != 0:
        raise RuntimeError(f"gdbot-launch failed for slot {slot}: {done.stderr.strip() or done.stdout.strip()}")
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if path.exists() and path.stat().st_mtime_ns != before:
            return discovery(slot)
        time.sleep(0.1)
    raise RuntimeError(f"slot {slot} launched but {path} was not rewritten")
