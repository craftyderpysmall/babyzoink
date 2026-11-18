"""Find the PlayerObject field that records a pending (fresh) orb press, via debug_peek.

Reproduces Codex's held-out yellow-orb case (handoffs/2026-11-18-codex-to-claude-orb-diagnosis.md):
  A: press at 997 and hold continuously            -> no orb boost
  B: press 997, release 998, press 1051 and hold   -> boost at 1056
  C: press 997, release 998, pulse 1051 only       -> no boost (early press released)
Dumps player bytes 0x900..0xb00 each tick 1046..1057 and reports byte offsets whose value differs
between B and A/C at tick 1055 while A, B and C all agree at tick 1050 (before the re-press).
Usage: python -I tools/m1/orb_probe.py
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from gdbot.protocol import BridgeClient, NamedPipeTransport  # noqa: E402

LO, HI = 0x900, 0xB00
CASES = {
    "A_hold": {997: 1},
    "B_repress_hold": {997: 1, 998: 0, 1051: 1},
    "C_early_pulse": {997: 1, 998: 0, 1051: 1, 1052: 0},
}


def run(c, edges):
    r = c.request("reset", start={"kind": "zero"})
    ep, tick, action = r["episode"], r["tick"], 0
    dumps, vys = {}, {}
    while tick < 1058:
        action = edges.get(tick, action)
        s = c.step(episode=ep, tick=tick, action=action, k=1)
        tick = s["tick"]
        if 1046 <= tick <= 1057:
            pk = c.request("debug_peek", target="player1", off=LO, len=HI - LO)
            dumps[tick] = bytes.fromhex(pk["hex"])
            pl = s["obs"]["players"][0]
            vys[tick] = (round(pl["vy"], 3), int(pl["buffered"]))
        if s["terminal"]:
            break
    return dumps, vys


def main():
    info = json.load(open(os.path.join(ROOT, "game", "2.2091", "gdbot", "bridge.json")))
    c = BridgeClient(NamedPipeTransport(info["pipe"]))
    c.require_isolated()
    tape = json.load(open(os.path.join(ROOT, "levels", "drills", "tapes", "yellow-orb", "heldout-2105.json")))
    c.request("load_level", level=tape["level"])
    res = {name: run(c, e) for name, e in CASES.items()}
    for name, (_, vys) in res.items():
        print(name, "vy by tick:", vys)
    A, B, C = (res[k][0] for k in CASES)
    cands = []
    for i in range(HI - LO):
        if not all(t in d for d in (A, B, C) for t in (1050, 1055)):
            break
        same_before = A[1050][i] == B[1050][i] == C[1050][i]
        b_unique = B[1055][i] != A[1055][i] and B[1055][i] != C[1055][i]
        if same_before and b_unique:
            off = LO + i
            seq = lambda d: [d[t][i] for t in range(1048, 1057) if t in d]
            cands.append(off)
            print(f"+0x{off:03x}: A={seq(A)} B={seq(B)} C={seq(C)}")
    print("candidates:", [hex(o) for o in cands])
    c.request("quit_level")
    c.close()


if __name__ == "__main__":
    main()
