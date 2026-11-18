"""Live test for the run-mode toggle (dedicated / background / auto).

Usage (GD running via gdbot-launch, RUNTIME claimed): python -I tools/m1/mode_test.py
"""
import ctypes
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from gdbot.protocol import BridgeClient, NamedPipeTransport  # noqa: E402

BOT = os.path.join(ROOT, "game", "2.2091", "gdbot")
MODE_FILE = os.path.join(BOT, "mode.txt")
results = []


def check(name, cond, ev):
    results.append((name, bool(cond)))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}: {ev}", flush=True)


def gd_proc_info(pid):
    ps = (f"$p=Get-Process -Id {pid}; '{{0}} {{1}}' -f $p.PriorityClass, [Convert]::ToString([int64]$p.ProcessorAffinity, 2)")
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True).stdout.strip()
    prio, mask = out.split() if " " in out else (out, "")
    return prio, mask.count("1")


def press_ctrl_alt_b():
    u = ctypes.windll.user32
    VK_CONTROL, VK_MENU, VK_B, UP = 0x11, 0x12, 0x42, 0x0002
    for vk in (VK_CONTROL, VK_MENU, VK_B):
        u.keybd_event(vk, 0, 0, 0)
    time.sleep(0.05)
    for vk in (VK_B, VK_MENU, VK_CONTROL):
        u.keybd_event(vk, 0, UP, 0)


def steps_until_mode(c, ep, tick, want, timeout=5.0):
    t0 = time.time()
    s = None
    while time.time() - t0 < timeout:
        s = c.step(episode=ep, tick=tick, action=0, k=1)
        tick = s["tick"]
        if s.get("mode") == want:
            return tick, s, time.time() - t0
        if s["terminal"]:
            r = c.request("reset", start={"kind": "zero"}); ep, tick = r["episode"], r["tick"]
        time.sleep(0.05)
    return tick, s, None


def rate(c, k=4, secs=3.0):
    r = c.request("reset", start={"kind": "zero"}); ep, tick = r["episode"], r["tick"]
    n, ticks, t0 = 0, 0, time.perf_counter()
    while time.perf_counter() - t0 < secs:
        s = c.step(episode=ep, tick=tick, action=(n // 40) % 2, k=k); tick = s["tick"]; n += 1; ticks += s["ticks_advanced"]
        if s["terminal"]:
            r = c.request("reset", start={"kind": "zero"}); ep, tick = r["episode"], r["tick"]
    return ticks / (time.perf_counter() - t0) / 240


def trace(c, tape):
    r = c.request("reset", start={"kind": "zero"}); ep, tick = r["episode"], r["tick"]
    rows = []
    for a in tape:
        s = c.step(episode=ep, tick=tick, action=a, k=1); tick = s["tick"]
        p = s["obs"]["players"][0]
        rows.append((tick, round(p["x"], 4), round(p["y"], 4), round(p["vy"], 4)))
        if s["terminal"]:
            rows.append(("terminal", s["terminal"]))
            break
    return rows


def main():
    if os.path.exists(MODE_FILE):
        os.remove(MODE_FILE)
    info = json.load(open(os.path.join(BOT, "bridge.json")))
    pid = info["pid"]
    c = BridgeClient(NamedPipeTransport(info["pipe"]))
    h = c.require_isolated()
    check("0 hello reports mode", "mode" in h, f"mode={h.get('mode')}")
    c.request("load_level", level={"kind": "main", "id": 1})
    sm = c.request("set_mode", mode="dedicated")
    r = c.request("reset", start={"kind": "zero"}); ep, tick = r["episode"], r["tick"]
    prio, n = gd_proc_info(pid)
    check("1 client set_mode dedicated", sm["mode"] == "dedicated" and prio == "Normal" and n >= 8, f"priority={prio} threads={n}")
    x_ded = rate(c)

    open(MODE_FILE, "w").write("background")
    r = c.request("reset", start={"kind": "zero"}); ep, tick = r["episode"], r["tick"]
    tick, s, dt = steps_until_mode(c, ep, tick, "background")
    prio, n = gd_proc_info(pid)
    check("2 mode.txt background applies", dt is not None and prio == "BelowNormal" and n == 4,
          f"applied after {dt and round(dt, 2)}s; priority={prio} threads={n}")
    sm = c.request("set_mode", mode="dedicated")
    check("3 user choice overrides client", sm.get("overridden_by_user") and sm["mode"] == "background", f"reply={sm}")
    x_bg = rate(c)

    press_ctrl_alt_b()
    r = c.request("reset", start={"kind": "zero"}); ep, tick = r["episode"], r["tick"]
    tick, s, dt = steps_until_mode(c, ep, tick, "dedicated")
    fileval = open(MODE_FILE).read().strip() if os.path.exists(MODE_FILE) else None
    check("4 Ctrl+Alt+B toggles to dedicated", dt is not None and fileval == "dedicated", f"after {dt and round(dt, 2)}s; mode.txt={fileval}")

    open(MODE_FILE, "w").write("auto")
    c.request("set_mode", mode="background")  # ignored until auto is applied
    r = c.request("reset", start={"kind": "zero"}); ep, tick = r["episode"], r["tick"]
    time.sleep(2.0)
    sm = c.request("set_mode", mode="background")
    check("5 auto hands control back to client", not sm.get("overridden_by_user") and sm["mode"] == "background", f"reply={sm}")

    tape = [0] * 100 + [1] * 18 + [0] * 140 + [1] * 10 + [0] * 200
    c.request("set_mode", mode="dedicated"); a = trace(c, tape)
    c.request("set_mode", mode="background"); b = trace(c, tape)
    div = next((i for i, (p, q) in enumerate(zip(a, b)) if p != q), None)
    check("6 same tape, both modes: identical trace", a == b, f"{len(a)} rows; first divergence {div}")
    check("7 throughput", True, f"dedicated {x_ded:.1f}x real time, background {x_bg:.1f}x real time (k=4)")
    c.request("set_mode", mode="normal")
    c.request("quit_level")
    c.close()
    if os.path.exists(MODE_FILE):
        os.remove(MODE_FILE)
    print(f"\n{sum(o for _, o in results)}/{len(results)} checks passed")


if __name__ == "__main__":
    main()
