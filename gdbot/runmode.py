"""Make the Python trainer follow the bridge's run mode (the user's dedicated/background toggle).

The bridge reports `mode` in every step/hello reply. The user switches it with Ctrl+Alt+B or
tools/mode.ps1. On a change this process adopts the matching CPU share:
  dedicated : torch uses all physical cores, normal priority, all hardware threads
  background: torch uses 2 threads, BELOW_NORMAL priority, the same 4 highest-numbered hardware
              threads GD uses, so the user's own apps keep the rest of the machine
  normal    : treated like dedicated (real-time pacing is limited by the game, not by Python)
Modes change pacing only, never results.
"""
import ctypes
import os
import sys
import time

_current = None
_log = []  # (unix time, mode) of each switch, for the trainer's report


def _physical_cores() -> int:
    n = os.cpu_count() or 2
    return max(1, n // 2)  # SMT machines expose 2 hardware threads per core


def kernel32():
    """kernel32 with 64-bit-safe prototypes (HANDLE and DWORD_PTR must not be truncated to int)."""
    from ctypes import wintypes as w
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.GetCurrentProcess.restype = w.HANDLE
    k.GetPriorityClass.argtypes = [w.HANDLE]
    k.GetPriorityClass.restype = w.DWORD
    k.SetPriorityClass.argtypes = [w.HANDLE, w.DWORD]
    k.SetPriorityClass.restype = w.BOOL
    k.GetProcessAffinityMask.argtypes = [w.HANDLE, ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_size_t)]
    k.GetProcessAffinityMask.restype = w.BOOL
    k.SetProcessAffinityMask.argtypes = [w.HANDLE, ctypes.c_size_t]
    k.SetProcessAffinityMask.restype = w.BOOL
    return k


def _set_process_cpu(background: bool) -> None:
    if sys.platform != "win32":
        return
    k32 = kernel32()
    h = k32.GetCurrentProcess()
    BELOW_NORMAL, NORMAL = 0x00004000, 0x00000020
    k32.SetPriorityClass(h, BELOW_NORMAL if background else NORMAL)
    proc_mask, sys_mask = ctypes.c_size_t(), ctypes.c_size_t()
    if not k32.GetProcessAffinityMask(h, ctypes.byref(proc_mask), ctypes.byref(sys_mask)):
        return
    mask = sys_mask.value
    if background:
        four, n = 0, 0
        for b in range(63, -1, -1):  # the 4 highest-numbered hardware threads, same as the bridge
            if mask & (1 << b) and n < 4:
                four |= 1 << b
                n += 1
        mask = four or mask
    k32.SetProcessAffinityMask(h, mask)


def follow(mode) -> bool:
    """Adopt `mode` if it differs from the current one. Returns True when something changed."""
    global _current
    if mode not in ("dedicated", "background", "normal") or mode == _current:
        return False
    background = mode == "background"
    try:
        import torch
        torch.set_num_threads(2 if background else _physical_cores())
    except ImportError:
        pass
    _set_process_cpu(background)
    _current = mode
    _log.append((time.time(), mode))
    print(f"[gdbot] run mode -> {mode}", flush=True)
    return True


def current():
    return _current


def history():
    return list(_log)
