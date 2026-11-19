"""Find and launch parallel bridge instances.

Slot 0 is the original single-instance layout: discovery in game/2.2091/gdbot/bridge.json, save in
gdbot/save/. Slot N >= 1 (started with `gdbot-launch.exe --instance N`) keeps its discovery, log and
save in gdbot/inst<N>/. mode.txt (the user's dedicated/background toggle) stays shared in gdbot/,
so one toggle drives every instance.
"""
import ctypes
import json
import subprocess
import sys
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


GAME_EXE = GAME / "GeometryDash.exe"
_SLACK_S = 120.0  # discovery is written a few seconds after the process starts


def _process_identity(pid: int):
    """(exe path, creation time as Unix seconds) of a live process, or None if it is gone or unreadable."""
    if sys.platform != "win32" or type(pid) is not int or pid <= 0:
        return None
    from ctypes import wintypes as w
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = w.HANDLE
    k32.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    k32.CloseHandle.argtypes = [w.HANDLE]
    k32.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)]
    k32.GetProcessTimes.argtypes = [w.HANDLE] + [ctypes.POINTER(w.FILETIME)] * 4
    k32.GetExitCodeProcess.argtypes = [w.HANDLE, ctypes.POINTER(w.DWORD)]
    h = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return None
    try:
        code = w.DWORD()
        if not k32.GetExitCodeProcess(h, ctypes.byref(code)) or code.value != 259:  # STILL_ACTIVE
            return None
        buf = ctypes.create_unicode_buffer(32768)
        size = w.DWORD(len(buf))
        if not k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return None
        created, a, b, c = w.FILETIME(), w.FILETIME(), w.FILETIME(), w.FILETIME()
        if not k32.GetProcessTimes(h, ctypes.byref(created), ctypes.byref(a), ctypes.byref(b), ctypes.byref(c)):
            return None
        ticks = (created.dwHighDateTime << 32) | created.dwLowDateTime
        return buf.value, ticks / 1e7 - 11644473600.0
    finally:
        k32.CloseHandle(h)


def owned_pid(slot: int, pid: int | None = None, *, identity=_process_identity) -> int | None:
    """The slot's GD pid if, and only if, that process is still the bot copy this slot's discovery file describes.

    Checks: the pid is alive, its image is this repo's game/2.2091/GeometryDash.exe (never the user's Steam GD or
    another program that reused the pid), and it was created no later than the discovery file was written (a
    process created after the file is a pid reuse).
    """
    path = instance_dir(slot) / "bridge.json"
    try:
        record = discovery(slot)
        written = path.stat().st_mtime
    except (OSError, ValueError):
        return None
    if pid is None:
        pid = record.get("pid")
    if type(pid) is not int or pid != record.get("pid"):
        return None
    found = identity(pid)
    if not found:
        return None
    exe, created = found
    try:
        same_exe = Path(exe).resolve() == GAME_EXE.resolve()
    except OSError:
        same_exe = False
    if not same_exe or created > written + _SLACK_S:
        return None
    return pid


def stop_slot(slot: int, *, timeout_s: float = 15.0, identity=_process_identity) -> bool:
    """Force-close this slot's bot GD only if owned_pid() confirms it. Returns True once no owned process remains."""
    pid = owned_pid(slot, identity=identity)
    if pid is None:
        return True
    subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if identity(pid) is None:
            return True
        time.sleep(0.5)
    return False
