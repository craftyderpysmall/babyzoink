"""M4 live test: practice mode + bot checkpoints, including restore parity (plan Decision 5).

On a verified drill tape (single spike, train-1100):
  1. set_practice on; replay the tape to tick T1 (before the 2nd jump); checkpoint_create -> id1
  2. continue the tape to T2; checkpoint_create -> id2
  3. reset{checkpoint} restores id2: player x/y/vy match the values recorded at T2
  4. PARITY: from id2, replay the tape suffix; the per-tick trace must equal the continuous run's trace
     from T2 onward, and the run must complete
  5. checkpoint_pop removes id2; reset{checkpoint} restores id1 (x matches T1)
  6. no auto-checkpoints: count stays at what the bot created
  7. reset{zero} turns practice off and starts at x=0
Usage: python -I tools/m1/checkpoint_test.py
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from gdbot.protocol import BridgeClient, NamedPipeTransport  # noqa: E402

results = []


def check(name, cond, ev):
    results.append((name, bool(cond)))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}: {ev}", flush=True)


def row(s):
    p = s["obs"]["players"][0]
    return (round(p["x"], 3), round(p["y"], 3), round(p["vy"], 4), p["on_ground"], p["holding"])


def run(c, ep, tick, edges, until, abs_offset=0):
    """Step k=1 with tape edges (absolute ticks = tick + abs_offset) until abs tick `until` or terminal."""
    trace, action, s = [], edges_action_at(edges, tick + abs_offset), None
    while tick + abs_offset < until:
        action = edges.get(tick + abs_offset, action)
        s = c.step(episode=ep, tick=tick, action=action, k=1)
        tick = s["tick"]
        trace.append((tick + abs_offset, row(s)))
        if s["terminal"]:
            break
    return tick, trace, s


def edges_action_at(edges, t):
    a = 0
    for k in sorted(edges):
        if k <= t:
            a = edges[k]
    return a


def main():
    info = json.load(open(os.path.join(ROOT, "game", "2.2091", "gdbot", "bridge.json")))
    c = BridgeClient(NamedPipeTransport(info["pipe"]))
    c.require_isolated()
    tape = json.load(open(os.path.join(ROOT, "levels", "drills", "tapes", "single-spike", "train-1100.json")))
    edges = dict(tape["edges"])
    T1, T2 = 800, 1700  # between the tape's jumps (316, 963, 1517, 2187 ...)
    c.request("load_level", level=tape["level"])

    # continuous reference run (practice off)
    r = c.request("reset", start={"kind": "zero"})
    _, ref, last = run(c, r["episode"], r["tick"], edges, 99999)
    ref_by_tick = dict(ref)
    check("0 reference run completes", last and last["terminal"] == "complete", f"terminal={last and last['terminal']} at {ref[-1][0]}")

    # practice run with checkpoints
    r = c.request("reset", start={"kind": "zero"})
    pr = c.request("set_practice", enabled=True)
    ep, tick = r["episode"], r["tick"]
    tick, tr1, _ = run(c, ep, tick, edges, T1)
    cp1 = c.request("checkpoint_create")
    tick, tr2, _ = run(c, ep, tick, edges, T2)
    cp2 = c.request("checkpoint_create")
    check("1 practice + 2 checkpoints", pr["practice"] and cp1["checkpoint_id"] != cp2["checkpoint_id"] and cp2["count"] == 2,
          f"cp1={cp1} cp2={cp2}")
    pre_ok = tr1[-1][1] == ref_by_tick[T1] and tr2[-1][1] == ref_by_tick[T2]
    check("2 practice mode doesn't change physics before checkpoints", pre_ok,
          f"T1 {tr1[-1][1]} vs ref {ref_by_tick[T1]}; T2 {tr2[-1][1]} vs ref {ref_by_tick[T2]}")

    # restore newest (cp2) and replay suffix with absolute tick offset T2
    r = c.request("reset", start={"kind": "checkpoint"})
    restored = row(r)
    check("3 restore newest checkpoint", r["start"].get("checkpoint_id") == cp2["checkpoint_id"]
          and abs(restored[0] - ref_by_tick[T2][0]) < 0.01,
          f"start={r['start']} restored {restored} vs ref@T2 {ref_by_tick[T2]} (tick after restore {r['tick']})")
    _, suf, last = run(c, r["episode"], r["tick"], edges, 99999, abs_offset=T2 - r["tick"])
    first_div = next((t for t, v in suf if ref_by_tick.get(t) != v), None)
    check("4 PARITY: checkpoint suffix == continuous run", first_div is None and last and last["terminal"] == "complete",
          f"{len(suf)} ticks compared; first divergence at abs tick {first_div}"
          + ("" if first_div is None else f": {dict(suf)[first_div]} vs {ref_by_tick.get(first_div)}")
          + f"; terminal={last and last['terminal']}")

    pop = c.request("checkpoint_pop")
    r = c.request("reset", start={"kind": "checkpoint"})
    check("5 pop then restore previous", pop["removed"] == cp2["checkpoint_id"] and pop["count"] == 1
          and abs(row(r)[0] - ref_by_tick[T1][0]) < 0.01, f"pop={pop} restored x={row(r)[0]} vs ref@T1 {ref_by_tick[T1][0]}")

    # no auto-checkpoints after a long practice segment
    _, _, _ = run(c, r["episode"], r["tick"], edges, T1 + 1500, abs_offset=T1 - r["tick"])
    cp3 = c.request("checkpoint_create")
    check("6 no practice auto-checkpoints", cp3["count"] == 2, f"count after one more bot checkpoint = {cp3['count']} (expect 2)")

    r = c.request("reset", start={"kind": "zero"})
    pr = None
    try:
        c.request("reset", start={"kind": "checkpoint"})
        practice_off = False
    except Exception as e:  # expected: no checkpoint after a zero reset
        practice_off = "BAD_REQUEST" in str(e)
    check("7 zero reset = clean start, practice off", row(r)[0] < 1 and practice_off, f"x={row(r)[0]} checkpoint-after-zero rejected={practice_off}")
    c.request("quit_level")
    c.close()
    print(f"\n{sum(o for _, o in results)}/{len(results)} checks passed")


if __name__ == "__main__":
    main()
