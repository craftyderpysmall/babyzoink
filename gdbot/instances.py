"""Find and launch parallel bridge instances.

Slot 0 is the original single-instance layout: discovery in game/2.2091/gdbot/bridge.json, save in
gdbot/save/. Slot N >= 1 (started with `gdbot-launch.exe --instance N`) keeps its discovery, log and
save in gdbot/inst<N>/. mode.txt (the user's dedicated/background toggle) stays shared in gdbot/,
so one toggle drives every instance.
"""
import ctypes
import json
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from enum import StrEnum
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


def launch(slot: int, *, launcher: Path = LAUNCHER, timeout_s: float = 90.0, session: str | None = None) -> dict:
    """Start a launcher-owned GD for `slot` and return its fresh discovery record.

    session (M8): "keep" for supervisor recycles (the user's mode/overlay choices stay), "fresh" for a start
    the user asked for (dedicated, overlay on); None = the launcher's default (fresh). Launchers older than
    M8 ignore unknown arguments, so passing it to the pinned pre-CBF launcher is harmless.
    """
    if session not in (None, "fresh", "keep"):
        raise ValueError("session must be fresh or keep")
    path = instance_dir(slot) / "bridge.json"
    before = path.stat().st_mtime_ns if path.exists() else None
    args = [str(launcher)] + (["--instance", str(slot)] if slot else []) + (["--session", session] if session else [])
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


def _process_api():
    from ctypes import wintypes as w

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = w.HANDLE
    k32.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    k32.CloseHandle.argtypes = [w.HANDLE]
    k32.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)]
    k32.GetProcessTimes.argtypes = [w.HANDLE] + [ctypes.POINTER(w.FILETIME)] * 4
    k32.GetExitCodeProcess.argtypes = [w.HANDLE, ctypes.POINTER(w.DWORD)]
    k32.TerminateProcess.argtypes = [w.HANDLE, w.UINT]
    k32.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
    k32.WaitForSingleObject.restype = w.DWORD
    return k32


def _identity_on_handle(k32, handle):
    from ctypes import wintypes as w

    buf = ctypes.create_unicode_buffer(32768)
    size = w.DWORD(len(buf))
    if not k32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
        return None
    created, exited, kernel, user = w.FILETIME(), w.FILETIME(), w.FILETIME(), w.FILETIME()
    if not k32.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited),
                              ctypes.byref(kernel), ctypes.byref(user)):
        return None
    ticks = (created.dwHighDateTime << 32) | created.dwLowDateTime
    return buf.value, ticks / 1e7 - 11644473600.0


def _process_identity(pid: int):
    """(exe path, creation time as Unix seconds) of a live process, or None if it is gone or unreadable."""
    if sys.platform != "win32" or type(pid) is not int or pid <= 0:
        return None
    from ctypes import wintypes as w

    k32 = _process_api()
    h = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return None
    try:
        code = w.DWORD()
        if not k32.GetExitCodeProcess(h, ctypes.byref(code)) or code.value != 259:  # STILL_ACTIVE
            return None
        return _identity_on_handle(k32, h)
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


class StopResult(StrEnum):
    GONE = "gone"
    FOREIGN = "foreign"
    DENIED = "denied"
    TERMINATED = "terminated"
    STILL_RUNNING = "still_running"


class _CleanupHandle:
    def __init__(self, k32, handle):
        self.k32, self.handle = k32, handle

    def identity(self):
        return _identity_on_handle(self.k32, self.handle)

    def exited(self, timeout_s=0):
        wait = self.k32.WaitForSingleObject(self.handle, int(timeout_s * 1000))
        if wait not in (0, 258):  # WAIT_OBJECT_0 or WAIT_TIMEOUT
            raise ctypes.WinError(ctypes.get_last_error())
        return wait == 0

    def terminate(self):
        return bool(self.k32.TerminateProcess(self.handle, 1))


@contextmanager
def _open_for_cleanup(pid):
    if sys.platform != "win32":
        raise OSError("game slot cleanup requires Windows")
    k32 = _process_api()
    # PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_TERMINATE | SYNCHRONIZE
    handle = k32.OpenProcess(0x1000 | 0x0001 | 0x100000, False, pid)
    if not handle:
        error = ctypes.get_last_error()
        if error == 87:  # ERROR_INVALID_PARAMETER means the PID no longer exists
            yield None
            return
        raise ctypes.WinError(error)
    try:
        yield _CleanupHandle(k32, handle)
    finally:
        k32.CloseHandle(handle)


def _cleanup_snapshot(path: Path, slot: int):
    with path.open("rb") as source:
        record = json.load(source)
        written = os.fstat(source.fileno()).st_mtime
    if not isinstance(record, dict):
        raise ValueError("invalid slot discovery record")
    pid = record.get("pid")
    if type(pid) is not int or not 0 < pid <= 0xFFFFFFFF or record.get("instance", 0) != slot:
        raise ValueError("invalid process or slot in discovery record")
    return pid, written


def stop_slot_result(slot: int, *, timeout_s: float = 15.0, open_process=_open_for_cleanup) -> StopResult:
    """Verify and stop the discovered process through one Windows process handle."""
    if not 0 <= timeout_s < 0xFFFFFFFF / 1000:
        raise ValueError("invalid cleanup timeout")
    path = instance_dir(slot) / "bridge.json"
    try:
        pid, written = _cleanup_snapshot(path, slot)
    except FileNotFoundError:
        return StopResult.GONE
    except (OSError, ValueError):
        return StopResult.DENIED
    try:
        with open_process(pid) as process:
            if process is None or process.exited():
                return StopResult.GONE
            identity = process.identity()
            if identity is None:
                return StopResult.GONE if process.exited() else StopResult.DENIED
            exe, created = identity
            if Path(exe).resolve() != GAME_EXE.resolve() or not 0 <= written - created <= _SLACK_S:
                return StopResult.FOREIGN
            if _cleanup_snapshot(path, slot) != (pid, written):
                return StopResult.STILL_RUNNING  # discovery changed, so the caller must recheck before relaunch
            if not process.terminate():
                return StopResult.GONE if process.exited() else StopResult.DENIED
            return StopResult.TERMINATED if process.exited(timeout_s) else StopResult.STILL_RUNNING
    except (OSError, ValueError):
        return StopResult.DENIED


def stop_slot(slot: int, *, timeout_s: float = 15.0) -> bool:
    """Return whether a supervisor may safely proceed after cleanup."""
    return stop_slot_result(slot, timeout_s=timeout_s) in (StopResult.GONE, StopResult.FOREIGN, StopResult.TERMINATED)
