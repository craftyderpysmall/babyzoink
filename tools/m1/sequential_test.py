"""Regression test: several custom levels in one client session, then the same while minimized.

Usage (GD via gdbot-launch, RUNTIME claimed): python -I tools/m1/sequential_test.py
"""
import ctypes
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from gdbot.protocol import BridgeClient, NamedPipeTransport  # noqa: E402
from gdbot.replay import Tape, replay  # noqa: E402

MINIMIZE_AT = int(sys.argv[1]) if len(sys.argv) > 1 else None
TAPES = ["single-spike/train-1100", "double-spike/train-1101", "triple-spike/train-1102",
         "yellow-orb/train-1105", "single-spike/train-1100"]
d = json.loads((ROOT / "game/2.2091/gdbot/bridge.json").read_text(encoding="utf-8"))
hwnd = int(subprocess.run(["powershell", "-c", f"(Get-Process -Id {d['pid']}).MainWindowHandle"],
                          capture_output=True, text=True).stdout.strip())
ok = 0
with BridgeClient(NamedPipeTransport(d["pipe"])) as client:
    client.require_isolated()
    for i, name in enumerate(TAPES):
        if MINIMIZE_AT is not None and i == MINIMIZE_AT:
            ctypes.windll.user32.PostMessageW(hwnd, 0x0112, 0xF020, 0)  # WM_SYSCOMMAND SC_MINIMIZE, as the taskbar does
            time.sleep(1.5)
            iconic = ctypes.windll.user32.IsIconic(hwnd)
            ok += not iconic
            print(f"[{'FAIL' if iconic else 'PASS'}] minimize request leaves GD running (iconic={iconic})", flush=True)
        tape = Tape.load(ROOT / f"levels/drills/tapes/{name}.json")
        rows = replay(client, tape, settings=tape.settings, seed=tape.seed, trace=True, mode="dedicated")
        good = rows[-1].get("terminal") == tape.terminal
        ok += good
        print(f"[{'PASS' if good else 'FAIL'}] load {i + 1} {name}{' (minimized)' if MINIMIZE_AT is not None and i >= MINIMIZE_AT else ''}: "
              f"{len(rows)} ticks, {rows[-1].get('terminal')}", flush=True)
        client.request("quit_level")
    client.request("set_mode", mode="normal")
total = len(TAPES) + (MINIMIZE_AT is not None)
print(f"{ok}/{total} passed")
sys.exit(0 if ok == total else 1)
