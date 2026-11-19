"""Which coding agent runs this process: "claude", "codex" or None.

GDBOT_AGENT overrides. Otherwise the parent-process chain is searched for a claude or codex executable.
The bridge colours the GD window by agent (hello's "agent" field) so the user can tell slots apart.
"""
import ctypes
import os
import sys
from ctypes import wintypes
from functools import lru_cache


class _Entry(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_char * 260)]


def _process_table() -> dict:
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
    table, e = {}, _Entry()
    e.dwSize = ctypes.sizeof(e)
    ok = k32.Process32First(snap, ctypes.byref(e))
    while ok:
        table[e.th32ProcessID] = (e.th32ParentProcessID, e.szExeFile.decode(errors="replace").lower())
        ok = k32.Process32Next(snap, ctypes.byref(e))
    k32.CloseHandle(snap)
    return table


@lru_cache(maxsize=1)
def current_agent():
    env = os.environ.get("GDBOT_AGENT", "").strip().lower()
    if env:
        return env if env in ("claude", "codex") else None
    if sys.platform != "win32":
        return None
    try:
        table, pid = _process_table(), os.getpid()
    except OSError:
        return None
    for _ in range(32):
        if pid not in table:
            return None
        pid, name = table[pid]
        for agent in ("claude", "codex"):
            if agent in name:
                return agent
    return None
