"""Watch a saved search at 1x (real time) with human eyes, e.g. a solver stall (#31).

Fast-forwards (dedicated mode) to --lead-s seconds before the point of interest, then switches the bridge to
normal mode, where it serves one request per rendered frame (~60/s). Each request advances 4 physics ticks
(240 ticks/s = real time), so the game plays at 1x on screen. No bridge change needed.

Shows, in order:
  1. "stall": the solver's saved path into the stall, then the plain continuation it keeps dying on;
  2. "pass":  each passing continuation that tools/m6/stall_probe.py saved (by rewind b and timing k).

Usage: python tools/m6/watch.py --slot 1 --level online:11280109 [--lead-s 4] [--only stall|pass] [--loops 1]
Bring the slot's GD window to the front (taskbar) to watch. Your clicks in it are ignored while the bot drives.
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools/m6"))
from gdbot.instances import discovery  # noqa: E402
from gdbot.protocol import BridgeClient, NamedPipeTransport, RemoteError  # noqa: E402
from stall_probe import POOL, spec_for  # noqa: E402

K = 4
FRAME_TICKS = 4  # ticks per rendered frame at 1x (240 ticks/s / 60 frames/s)


def to_ticks(actions, k):
    return [a for a in actions for _ in range(k)]


def play_1x(client, ep, ticks, label):
    """Advance one rendered frame (4 ticks) per request in normal mode. Returns (terminal, x)."""
    client.request("set_mode", mode="normal")
    start = time.perf_counter()
    r = {"terminal": None, "player": {"x": 0.0}}
    for i in range(0, len(ticks), FRAME_TICKS):
        r = client.request("step_seq", episode=ep, actions=ticks[i:i + FRAME_TICKS], k=1)
        if r["terminal"]:
            break
    wall = time.perf_counter() - start
    played = min(len(ticks), i + FRAME_TICKS) if ticks else 0
    print(f"  {label}: {r['terminal'] or 'alive'} at x={r['player']['x']:.1f} "
          f"({played / 240:.1f} s of game in {wall:.1f} s wall)", flush=True)
    return r["terminal"], r["player"]["x"]


def show(client, prefix_ticks, start_tick, view_ticks, label, hold_s=1.5):
    client.request("set_mode", mode="dedicated")
    ep = client.request("reset", start={"kind": "zero"})["episode"]
    if start_tick:
        r = client.request("step_seq", episode=ep, actions=prefix_ticks[:start_tick], k=1)
        if r["terminal"]:
            print(f"  {label}: died while fast-forwarding at x={r['player']['x']:.1f}", flush=True)
            return
    play_1x(client, ep, prefix_ticks[start_tick:] + view_ticks, label)
    time.sleep(hold_s)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--slot", type=int, required=True)
    ap.add_argument("--level", required=True)
    ap.add_argument("--lead-s", type=float, default=4.0, help="seconds of play shown before the stall")
    ap.add_argument("--after-s", type=float, default=3.0, help="seconds shown after the stall (if alive)")
    ap.add_argument("--only", choices=["stall", "pass"])
    ap.add_argument("--loops", type=int, default=1)
    a = ap.parse_args()
    name = a.level.replace(":", "_")
    progress = json.loads((POOL / "solutions" / f"{name}.progress.json").read_text(encoding="utf-8"))
    committed = progress["committed"]
    probe_path = POOL / "diag" / f"stall_{name}.json"
    probe = json.loads(probe_path.read_text(encoding="utf-8")) if probe_path.exists() else {"backs": {}}
    full = to_ticks([x for s in committed for x in s], K)
    lead, after = int(a.lead_s * 240), int(a.after_s * 240)
    with BridgeClient(NamedPipeTransport(discovery(a.slot)["pipe"])) as client:
        client.require_isolated()
        try:
            client.request("quit_level")
        except RemoteError:
            pass
        client.request("set_render", present_every_ms=0)
        client.load_level(spec_for(a.level))
        try:
            for loop in range(a.loops):
                if a.only != "pass":
                    print(f"{a.level} stall at x={progress['seg_x'][-1]:.1f}: the solver's path, then no input",
                          flush=True)
                    show(client, full, max(0, len(full) - lead), [0] * after, "stall (release)")
                    show(client, full, max(0, len(full) - lead), [1] * after, "stall (hold)")
                if a.only != "stall":
                    for b, by_k in sorted(probe["backs"].items(), key=lambda kv: int(kv[0])):
                        for kname, res in by_k.items():
                            tail = res.get("passing_tail")
                            if not tail:
                                continue
                            pre = to_ticks([x for s in committed[:len(committed) - int(b)] for x in s], K)
                            tail_ticks = to_ticks(tail, int(kname[1:]))
                            print(f"{a.level} pass: rewind {b} segments, {kname} timing", flush=True)
                            show(client, pre, max(0, len(pre) - lead), tail_ticks[:len(full) - len(pre) + after],
                                 f"pass (back {b}, {kname})")
        finally:
            client.request("set_mode", mode="normal")
            try:
                client.request("quit_level")
            except RemoteError:
                pass


if __name__ == "__main__":
    main()
