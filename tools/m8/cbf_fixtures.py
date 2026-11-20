"""#47 CBF live fixtures across game modes (M8). For each drill's verified training tape:

  parity:  the tape at k=1 with no fracs == the same with explicit all-zero fracs (terminal, end tick, end x/y)
  safety:  with f in {0.25, 0.5, 0.75} on every press/release: no bridge error, and two runs are identical
  onset:   at the tape's first press, player y and vy one and two ticks after a press at fraction f
           (reported; for non-buffering states the effect should change smoothly with f)

Dual: on Because I Loved Her (online:26791333) after dual mode starts, a press at f in {0, .25, .5, .75}:
both players reported, deterministic, player 2 also responds.

Usage: python tools/m8/cbf_fixtures.py --slot 3 [--family ship-corridor ...] [--no-dual]
Writes build/m8/cbf-fixtures.json.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools/m6"))
from gdbot.instances import discovery  # noqa: E402
from gdbot.protocol import BridgeClient, NamedPipeTransport, RemoteError  # noqa: E402

FAMILIES = ["ship-corridor", "wave-corridor", "ufo-taps", "yellow-orb", "blue-orb", "dash-orb", "robot-jumps",
            "ball-switches", "spider-switches", "swing-corridor", "gravity-portal", "moving-geometry", "black-orb"]


def tape_for(family):
    for root in (ROOT / "levels/drills/m5/tapes", ROOT / "levels/drills/tapes"):
        d = root / family
        if d.exists():
            files = sorted(d.glob("train-*.json"))
            if files:
                return json.loads(files[0].read_text(encoding="utf-8"))
    return None


def per_tick(tape):
    actions, cur, last = [], 0, 0
    edges = dict((t, a) for t, a in tape["edges"])
    for t in range(1, tape["total_ticks"] + 1):
        if t in edges:
            cur = edges[t]
        actions.append(cur)
    return actions


def run(c, actions, fracs=None):
    ep = c.request("reset", start={"kind": "zero"})["episode"]
    kw = {"fracs": fracs} if fracs is not None else {}
    r = c.request("step_seq", episode=ep, actions=actions, k=1, **kw)
    p = r["player"]
    return {"terminal": r["terminal"], "tick": r["tick"], "x": round(p["x"], 4), "y": round(p["y"], 4)}


def fracs_at_changes(actions, f):
    out, prev = [], 0
    for a in actions:
        out.append(f if a != prev else 0.0)
        prev = a
    return out


def onset(c, actions, f):
    first = next((i for i, a in enumerate(actions) if a == 1), None)
    if first is None:
        return None
    ep = c.request("reset", start={"kind": "zero"})["episode"]
    if first:
        c.request("step_seq", episode=ep, actions=actions[:first], k=1)
    r1 = c.request("step", episode=ep, action=1, k=1, frac=f)
    r2 = c.request("step", episode=ep, action=1, k=1)
    p1, p2 = r1["obs"]["players"][0], r2["obs"]["players"][0]
    return {"mode": p1["mode"], "on_ground": p1["on_ground"], "y1": round(p1["y"], 4), "vy1": round(p1["vy"], 4),
            "y2": round(p2["y"], 4), "vy2": round(p2["vy"], 4)}


def fixture(c, family):
    tape = tape_for(family)
    if not tape:
        return {"family": family, "skipped": "no training tape"}
    try:
        c.request("quit_level")
    except RemoteError:
        pass
    c.load_level(tape["level"])
    acts = per_tick(tape)
    base = run(c, acts)
    zero = run(c, acts, [0.0] * len(acts))
    res = {"family": family, "ticks": len(acts), "base": base, "parity_zero": base == zero, "fractions": {}}
    for f in (0.25, 0.5, 0.75):
        a = run(c, acts, fracs_at_changes(acts, f))
        b = run(c, acts, fracs_at_changes(acts, f))
        res["fractions"][str(f)] = {"result": a, "deterministic": a == b}
    res["onset"] = {str(f): onset(c, acts, f) for f in (0.0, 0.25, 0.5, 0.75)}
    c.request("quit_level")
    return res


def dual_fixture(c):
    from stall_probe import spec_for
    prog = json.loads((ROOT / "build/m6-scale/solutions/online_26791333.progress.json").read_text(encoding="utf-8"))
    flat = [a for s in prog["committed"] for a in s]
    start = 4300  # decisions: dual mode is on from ~4224 (#56)
    prefix = flat[:start]
    try:
        c.request("quit_level")
    except RemoteError:
        pass
    c.load_level(spec_for("online:26791333"))
    out = {}
    for f in (0.0, 0.25, 0.5, 0.75):
        rows = []
        for _ in range(2):
            ep = c.request("reset", start={"kind": "zero"})["episode"]
            r = c.request("step_seq", episode=ep, actions=prefix + [0], k=4)
            r1 = c.request("step", episode=ep, action=1, k=1, frac=f)
            r2 = c.request("step", episode=ep, action=1, k=1)
            ps = r2["obs"]["players"]
            rows.append({"dual": r2["obs"].get("dual"), "terminal": r2["terminal"],
                         "p1": [round(ps[0]["y"], 4), round(ps[0]["vy"], 4)],
                         "p2": [round(ps[1]["y"], 4), round(ps[1]["vy"], 4)] if len(ps) > 1 else None})
        out[str(f)] = {"run": rows[0], "deterministic": rows[0] == rows[1]}
    c.request("quit_level")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--slot", type=int, required=True)
    ap.add_argument("--family", action="append")
    ap.add_argument("--no-dual", action="store_true")
    a = ap.parse_args()
    report = {"fixtures": [], "dual": None}
    with BridgeClient(NamedPipeTransport(discovery(a.slot)["pipe"])) as c:
        c.require_isolated()
        c.request("set_mode", mode="dedicated")
        for fam in a.family or FAMILIES:
            r = fixture(c, fam)
            report["fixtures"].append(r)
            if "skipped" in r:
                print(f"{fam}: skipped ({r['skipped']})", flush=True)
                continue
            det = all(v["deterministic"] for v in r["fractions"].values())
            ys = [r["onset"][k]["y2"] if r["onset"][k] else None for k in ("0.0", "0.25", "0.5", "0.75")]
            mode = r["onset"]["0.0"]["mode"] if r["onset"]["0.0"] else "-"
            print(f"{fam}: base {r['base']['terminal']} @ {r['base']['tick']}; f=0 parity {r['parity_zero']}; "
                  f"fractions deterministic {det}; results {[v['result']['terminal'] for v in r['fractions'].values()]}; "
                  f"onset ({mode}) y after 2 ticks {ys}", flush=True)
        if not a.no_dual:
            report["dual"] = dual_fixture(c)
            for f, v in report["dual"].items():
                print(f"dual f={f}: {v['run']} deterministic {v['deterministic']}", flush=True)
    out = ROOT / "build/m8/cbf-fixtures.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
