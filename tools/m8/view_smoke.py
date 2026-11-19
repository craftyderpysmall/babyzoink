"""M8 #46 smoke test on a live slot: fast-path parity, watch-at-1x pacing, overlay, set_overlay.

1. Replays the verified Stereo Madness clear (build/m5c/main_1.json) with step_seq on the fast path:
   it must still complete, and the ticks/s are reported.
2. Same replay split into step (k=4) requests: the end tick must match step_seq exactly.
3. Sets view.json watch_slot to this slot and runs 480 ticks with step_seq k=1: the wall time must be
   about 2.0 s (240 ticks/s), then turns watch off.
4. set_overlay with a job and two lines, then a snapshot (BMP) for visual review.

Usage: python tools/m8/view_smoke.py --slot 3
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from gdbot.instances import BOT, discovery  # noqa: E402
from gdbot.protocol import BridgeClient, NamedPipeTransport, RemoteError  # noqa: E402

VIEW = BOT / "view.json"
TAB = chr(9)  # set_overlay lines: "Key<TAB>value" puts the key in the overlay's key column


def set_view(overlay=True, watch=None):
    tmp = VIEW.with_suffix(".tmp")
    tmp.write_text(json.dumps({"overlay": overlay, "watch_slot": watch}), encoding="utf-8")
    tmp.replace(VIEW)
    time.sleep(0.6)  # bridges poll view.json every 250 ms


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--slot", type=int, required=True)
    a = ap.parse_args()
    sol = json.loads((ROOT / "build/m5c/main_1.json").read_text(encoding="utf-8"))["result"]
    actions, k = sol["actions"], sol["k"]
    results = []
    with BridgeClient(NamedPipeTransport(discovery(a.slot)["pipe"])) as c:
        hello = c.require_isolated()
        caps = hello["capabilities"]
        results.append(("capabilities watch_1x/overlay/session", all(caps.get(x) for x in ("watch_1x", "overlay", "session")), caps))
        try:
            c.request("quit_level")
        except RemoteError:
            pass
        c.request("set_mode", mode="dedicated")
        c.request("set_overlay", job="#46 smoke test", lines=["Search" + TAB + "verifying Stereo Madness", "Build" + TAB + "M8 bridge test"])
        c.load_level({"kind": "main", "id": 1})
        # 1. fast path
        ep = c.request("reset", start={"kind": "zero"})["episode"]
        t0 = time.perf_counter()
        r = c.request("step_seq", episode=ep, actions=actions, k=k)
        wall = time.perf_counter() - t0
        results.append(("fast path: verified clear still completes", r["terminal"] == "complete",
                        f"{r['ticks_advanced']} ticks in {wall:.2f} s = {r['ticks_advanced'] / wall:,.0f} ticks/s"))
        end_seq = r["tick"]
        # 2. step parity
        ep = c.request("reset", start={"kind": "zero"})["episode"]
        last = None
        for act in actions:
            last = c.request("step", episode=ep, action=act, k=k)
            if last["terminal"]:
                break
        results.append(("step k=4 matches step_seq end tick", last["terminal"] == "complete" and last["tick"] == end_seq,
                        f"step end tick {last['tick']} vs step_seq {end_seq}"))
        # 3. watch at 1x
        ep = c.request("reset", start={"kind": "zero"})["episode"]
        set_view(True, a.slot)
        t0 = time.perf_counter()
        r = c.request("step_seq", episode=ep, actions=actions[:120], k=4)  # 480 ticks = 2.0 s at 1x
        wall = time.perf_counter() - t0
        results.append(("watch 1x: 480 ticks take about 2.0 s", 1.8 <= wall <= 2.4 and r["ticks_advanced"] == 480,
                        f"{r['ticks_advanced']} ticks in {wall:.2f} s"))
        # 4. overlay snapshot while watching (every frame drawn)
        snap = c.request("snapshot")  # written to the slot's folder: inst<N>/snapshot.bmp
        results.append(("snapshot written", Path(snap["path"]).exists(), snap["path"]))
        set_view(True, None)
        t0 = time.perf_counter()
        r = c.request("step_seq", episode=ep, actions=actions[120:240], k=4)
        wall = time.perf_counter() - t0
        results.append(("watch off: back to full speed", wall < 0.5, f"{r['ticks_advanced']} ticks in {wall:.2f} s"))
        c.request("quit_level")
    ok = 0
    for name, passed, detail in results:
        ok += bool(passed)
        print(f"{'PASS' if passed else 'FAIL'}  {name}: {detail}", flush=True)
    print(f"{ok}/{len(results)} passed")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
