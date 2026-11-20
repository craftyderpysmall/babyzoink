"""#31: why does the M6 solver stall? For a saved search prefix, ask:
  1. what is at the stall (player state, objects ahead),
  2. how far back must the search rewind to get past it (b segments),
  3. does finer input timing help (k=4 decisions vs k=1 ticks)?

Method: replay the saved prefix up to depth d-b from a clean 0% start, then try random hold/release
continuations (geometric run lengths) and record the furthest x. "Pass" = x beyond the stall by --margin.
Read-only for the solver: reads build/m6-scale/solutions/<level>.progress.json, writes build/m6-scale/diag/.

Usage: python tools/m6/stall_probe.py --slot 1 --level online:11280109 [--level online:977287] [--trials 300]
"""
import argparse
import json
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools/m5c"))
from gdbot.instances import discovery  # noqa: E402
from gdbot.protocol import BridgeClient, NamedPipeTransport, RemoteError  # noqa: E402
from solver import K, decision_payload  # noqa: E402

POOL = ROOT / "build/m6-scale"


def spec_for(key):
    level_id = key.split(":", 1)[1]
    record = json.loads((POOL / "online" / f"{level_id}.json").read_text(encoding="utf-8"))
    return {"kind": "level_string", "name": f"online-{level_id}", "data": record["data"]}


def random_tail(rng, n, mean_run):
    out, state = [], rng.random() < 0.5
    while len(out) < n:
        run = 1 + int(rng.expovariate(1.0 / mean_run))
        out += [int(state)] * run
        state = not state
    return out[:n]


class Probe:
    def __init__(self, client):
        self.c = client

    def play(self, prefix_k4, tail, k_tail):
        """Clean 0% run: prefix at k=4, then tail at k_tail. Returns (terminal, x_end)."""
        reset = self.c.request("reset", start={"kind": "zero"})
        if any(action > 1 for action in prefix_k4) and not reset.get("input_timing", {}).get("cbf"):
            raise ValueError("replaying a fractional prefix requires the CBF bridge")
        ep = reset["episode"]
        if k_tail == K:
            actions = prefix_k4 + tail
            r = self.c.request("step_seq", episode=ep, k=K, **decision_payload(actions))
        else:
            if prefix_k4:
                r = self.c.request("step_seq", episode=ep, k=K, **decision_payload(prefix_k4))
                if r["terminal"]:
                    return r["terminal"], r["player"]["x"]
            r = self.c.request("step_seq", episode=ep, actions=tail, k=k_tail)
        return r["terminal"], r["player"]["x"]


def probe_level(client, key, trials, backs, margin, seed, log):
    progress = json.loads((POOL / "solutions" / f"{key.replace(':', '_')}.progress.json").read_text(encoding="utf-8"))
    committed, seg_x = progress["committed"], progress["seg_x"]
    depth = len(committed)
    stall_x = seg_x[-1] if seg_x else 0.0
    client.load_level(spec_for(key))
    p = Probe(client)
    # the saved prefix must replay exactly (otherwise this is a restore problem, not a search gap)
    flat = [a for s in committed for a in s]
    term, x = p.play(flat, [], K) if flat else ("none", 0.0)
    report = {"level": key, "depth": depth, "stall_x": stall_x, "evals": progress["evals"],
              "prefix_replay": {"terminal": term, "x": x, "exact": abs(x - stall_x) < 1e-3}, "backs": {}}
    log(f"{key}: depth {depth}, stall x {stall_x:.1f}, prefix replay {term} at x={x:.1f}")
    # what is at the stall: the state and objects right there
    reset = client.request("reset", start={"kind": "zero"})
    if any(action > 1 for action in flat) and not reset.get("input_timing", {}).get("cbf"):
        raise ValueError("replaying a fractional prefix requires the CBF bridge")
    ep = reset["episode"]
    r = client.request("step_seq", episode=ep, k=K, **decision_payload(flat)) if flat else None
    obs = client.request("step", episode=ep, action=0, k=1)["obs"]
    pl = obs["players"][0]
    ahead = sorted(({"cat": o["cat"], "type_id": o["type_id"], "dx": round(o["x"] - pl["x"], 1),
                     "dy": round(o["y"] - pl["y"], 1)} for o in obs["objects"] if 0 <= o["x"] - pl["x"] <= 400),
                   key=lambda o: o["dx"])
    report["at_stall"] = {"player": {k: pl[k] for k in ("x", "y", "mode", "speed", "gravity_flipped", "mini",
                                                         "on_ground", "vy")},
                          "objects_ahead": ahead[:40]}
    log(f"  at stall: mode={pl['mode']} speed={pl['speed']} y={pl['y']:.1f} on_ground={pl['on_ground']}; "
        f"{len(ahead)} objects within 400: {sorted({o['cat'] for o in ahead})}")
    rng = random.Random(seed)
    for b in backs:
        if b > depth:
            continue
        pre = [a for s in committed[:depth - b] for a in s]
        horizon_decisions = 8 * b + 120  # rewound segments + about 2 s of play past the stall
        for k_tail in (K, 1):
            n = horizon_decisions * (K // k_tail)
            mean_run = 3 if k_tail == K else 12
            best, passed_at, t0 = -1.0, None, time.perf_counter()
            passing = None
            for t in range(trials):
                tail = random_tail(rng, n, mean_run)
                term, xe = p.play(pre, tail, k_tail)
                best = max(best, xe)
                if xe > stall_x + margin or term == "complete":
                    passed_at, passing = t + 1, tail
                    break
            report["backs"].setdefault(str(b), {})[f"k{k_tail}"] = {
                "best_x": round(best, 1), "passed_after": passed_at, "trials": passed_at or trials,
                "wall_s": round(time.perf_counter() - t0, 1),
                "passing_tail": passing}  # actions at k_tail, starting at depth - b (for tools/m6/watch.py)
            log(f"  back {b:2d} seg, k={k_tail}: best x {best:.1f} "
                f"({'PASS after ' + str(passed_at) if passed_at else 'no pass in ' + str(trials)})")
    client.request("quit_level")
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--slot", type=int, required=True)
    ap.add_argument("--level", action="append", required=True)
    ap.add_argument("--trials", type=int, default=300)
    ap.add_argument("--backs", type=int, nargs="+", default=[0, 1, 2, 4, 8, 16])
    ap.add_argument("--margin", type=float, default=300.0)
    ap.add_argument("--seed", type=int, default=31)
    a = ap.parse_args()
    out = POOL / "diag"
    out.mkdir(parents=True, exist_ok=True)
    log = lambda m: print(m, flush=True)  # noqa: E731
    with BridgeClient(NamedPipeTransport(discovery(a.slot)["pipe"])) as client:
        client.require_isolated()
        with_suppress = (RemoteError,)
        try:
            client.request("quit_level")
        except with_suppress:
            pass
        client.request("set_mode", mode="dedicated")
        try:
            for key in a.level:
                report = probe_level(client, key, a.trials, a.backs, a.margin, a.seed, log)
                (out / f"stall_{key.replace(':', '_')}.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
        finally:
            client.request("set_mode", mode="normal")


if __name__ == "__main__":
    main()
