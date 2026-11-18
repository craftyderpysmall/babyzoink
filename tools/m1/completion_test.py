"""Tick-driven completion test: replay verified drill tapes with NO wall-clock finish wait.

Pass if: terminal == "complete" arrives at the end-crossing tick (a few ticks before the tape's old
wall-clock finish tick; measured 11 earlier on two drills), and an immediate
reset followed by 600 idle ticks never reports a stale "complete" (GD's real levelComplete arrives later
on a wall-clock timer and must be suppressed for the new episode).
Usage: python -I tools/m1/completion_test.py
"""
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from gdbot.protocol import BridgeClient, NamedPipeTransport  # noqa: E402

TAPES = ["single-spike/train-1100.json", "gravity-portal/heldout-2106.json"]


def main():
    info = json.load(open(os.path.join(ROOT, "game", "2.2091", "gdbot", "bridge.json")))
    c = BridgeClient(NamedPipeTransport(info["pipe"]))
    c.require_isolated()
    c.request("set_mode", mode="dedicated")
    ok_all = True
    for rel in TAPES:
        tape = json.load(open(os.path.join(ROOT, "levels", "drills", "tapes", rel)))
        c.request("load_level", level=tape["level"])
        for trial in range(2):
            r = c.request("reset", start={"kind": "zero"})
            ep, tick = r["episode"], r["tick"]
            edges = dict(tape["edges"])
            action, term = 0, None
            t0 = time.perf_counter()
            while tick < tape["total_ticks"] + 50:
                action = edges.get(tick, action)
                s = c.step(episode=ep, tick=tick, action=action, k=1)
                tick = s["tick"]
                if s["terminal"]:
                    term = (s["terminal"], tick)
                    break
            el = time.perf_counter() - t0
            # immediately reset and idle: a stale complete must not leak into the new episode
            r = c.request("reset", start={"kind": "zero"})
            ep2, t2, leak = r["episode"], r["tick"], None
            for _ in range(150):
                s = c.step(episode=ep2, tick=t2, action=0, k=4)
                t2 = s["tick"]
                if s["terminal"] == "complete":
                    leak = t2
                    break
                if s["terminal"]:
                    break
            ok = term is not None and term[0] == "complete" and 0 <= tape["finish_wait"][0] - term[1] <= 20 and leak is None
            ok_all &= ok
            print(f"[{'PASS' if ok else 'FAIL'}] {rel} trial {trial}: terminal={term} (tape finish tick "
                  f"{tape['finish_wait'][0]}), replay {el:.2f}s wall, stale complete in next episode: {leak}", flush=True)
        c.request("quit_level")
    c.request("set_mode", mode="normal")
    c.close()
    print("ALL PASS" if ok_all else "SOME FAILED")


if __name__ == "__main__":
    main()
