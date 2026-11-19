"""M5c search-based teacher: find a clear of a level by deterministic search, no human input.

GD in lockstep is deterministic and bot checkpoints restore exactly, so a level can be solved
segment by segment: from a checkpoint, try candidate input patterns for the next S decisions
(k=4 ticks each), keep the first one that survives the segment plus a short lookahead, commit it,
checkpoint, and continue. If no candidate works, back up one segment and take that segment's next
candidate (depth-first search with a bounded budget). The final action list is verified by a clean
run from 0% (practice off); only verified clears are written as solutions/demos.

Usage: python tools/m5c/solver.py --slot 0 --level main:1 [--level drill:triple-spike/heldout-2102] --output build/m5c
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from gdbot.instances import discovery  # noqa: E402
from gdbot.protocol import BridgeClient, NamedPipeTransport, RemoteError  # noqa: E402

K = 4


def candidates(seg: int, prev: int):
    """Input patterns for one segment, cheapest/most natural first."""
    seen = set()

    def add(p):
        t = tuple(p)
        if t not in seen:
            seen.add(t)
            yield list(t)

    yield from add([prev] * seg)
    yield from add([1 - prev] * seg)
    for length in range(1, seg + 1):          # short taps first, then longer holds
        for start in range(seg - length + 1):
            for base in (0, 1):
                p = [base] * seg
                for i in range(start, start + length):
                    p[i] = 1 - base
                yield from add(p)


CONTINUATIONS = ("zeros", "ones", "alt")


def continuation(kind: str, n: int):
    return [0] * n if kind == "zeros" else [1] * n if kind == "ones" else [(i // 2) % 2 for i in range(n)]


class Solver:
    def __init__(self, client, level: dict, *, seg=8, look=28, budget=20000, log=print):
        self.c, self.level, self.seg, self.look, self.budget, self.log = client, level, seg, look, budget, log
        self.evals = 0
        self.ticks = 0

    # -- bridge helpers -------------------------------------------------------------------------
    def reset_zero(self):
        r = self.c.request("reset", start={"kind": "zero"})
        self.ep = r["episode"]
        return r

    def restore(self):
        r = self.c.request("reset", start={"kind": "checkpoint"})
        self.ep = r["episode"]
        return r

    def run(self, actions, xs=False):
        r = self.c.request("step_seq", episode=self.ep, actions=actions, k=K, xs=xs)
        self.ticks += r["ticks_advanced"]
        return r

    # -- search ---------------------------------------------------------------------------------
    def followups(self):
        """Simple continuations that test whether the state after a segment is still viable. The
        lookahead must outlast a jump's airtime, or "not yet" looks fine when it is already too late."""
        L = self.look
        yield [0] * L
        for j in range(L):                    # a single tap at every point
            yield [0] * j + [1] + [0] * (L - j - 1)
        yield [1] * L
        yield continuation("alt", L)

    def evaluate(self, cand):
        """Viability of a candidate from the current checkpoint: (ok, complete, decisions_survived)."""
        best = -1
        for follow in self.followups():
            self.restore()
            self.evals += 1
            r = self.run(cand + follow)
            if r["terminal"] == "complete":
                # the level ended during decision number `decisions`: keep the inputs up to it
                return True, True, (cand + follow)[:r["decisions"] + 1]
            survived = r["decisions"]
            if survived >= len(cand) + len(follow):
                return True, False, survived
            best = max(best, survived)
            if survived < len(cand):          # died inside the segment: no follow-up can help
                break
        return False, False, best

    # -- re-anchoring ----------------------------------------------------------------------------
    # A checkpoint restore is not always bit-exact (Codex measured 257/272 parity windows in M4), so
    # a path stitched from restores can drift from a real run. Every ANCHOR_EVERY commits the solver
    # replays the committed prefix from a clean 0% start, compares each segment's end x with what it
    # recorded, cuts back to the last matching segment, and rebuilds its checkpoints from that true
    # replay. Drift can then never compound.
    ANCHOR_EVERY = 16
    KEEP_CHECKPOINTS = 12

    def drop_checkpoints(self):
        while True:
            try:
                if self.c.request("checkpoint_pop")["count"] == 0:
                    return
            except RemoteError:
                return

    def rebuild(self, target):
        """Replay committed[:target] from 0% (practice on), creating checkpoints for the last
        KEEP_CHECKPOINTS depths. Returns the depth that actually matched (<= target)."""
        self.anchors += 1
        self.drop_checkpoints()
        self.reset_zero()
        self.c.request("set_practice", enabled=True)
        self.cps = []
        for depth in range(target + 1):
            if depth >= target - self.KEEP_CHECKPOINTS:
                self.c.request("checkpoint_create")
                self.cps.append(depth)
            if depth == target:
                return target
            r = self.run(self.committed[depth], xs=True)
            if r["terminal"] or abs(r["xs"][-1] - self.seg_x[depth]) > 1e-3:
                self.drifts += 1
                self.log(f"  drift at segment {depth} (replay {r['terminal'] or round(r['xs'][-1], 3)} vs "
                         f"search {round(self.seg_x[depth], 3)}): cutting back and re-anchoring")
                del self.committed[depth:], self.seg_x[depth:]
                del self.stack[depth + 1:]
                self.stack[depth] = candidates(self.seg, self.committed[-1][-1] if self.committed else 0)
                return self.rebuild(depth)
        return target

    def solve(self):
        self.c.load_level(self.level)
        self.committed, self.seg_x = [], []   # committed segments and the x recorded at each one's end
        self.stack = [candidates(self.seg, 0)]  # candidate iterators per depth (depth = len(committed))
        self.anchors = self.drifts = 0
        self.rebuild(0)
        furthest, t0, since_anchor = 0.0, time.perf_counter(), 0
        while self.evals < self.budget:
            depth = len(self.committed)
            chosen = None
            for cand in self.stack[-1]:
                ok, complete, survived = self.evaluate(cand)
                if complete:
                    actions = [a for s in self.committed for a in s] + survived  # survived = finishing inputs
                    self.log(f"  complete in search at segment {depth} ({self.evals} evals, {self.ticks} ticks)")
                    result = self.finish(actions, t0)
                    if result["verified"]:
                        return result
                    self.rebuild(len(self.committed))  # locate the drift, cut back, keep searching
                    break
                if ok:
                    chosen = cand
                    break
                if self.evals >= self.budget:
                    break
            else:
                if depth == 0:
                    self.log("  no candidate survives the first segment")
                    return None
                # every candidate failed: backtrack one segment
                self.c.request("checkpoint_pop")
                self.cps.pop()
                self.committed.pop(), self.seg_x.pop(), self.stack.pop()
                if not self.cps or self.cps[-1] != len(self.committed):
                    self.rebuild(len(self.committed))
                continue
            if chosen is None:
                continue
            self.restore()
            r = self.run(chosen, xs=True)
            if r["terminal"]:
                self.log(f"  commit died where evaluation survived ({r['terminal']}): re-anchoring")
                self.rebuild(len(self.committed))
                continue
            self.c.request("checkpoint_create")
            self.cps.append(depth + 1)
            self.committed.append(chosen)
            self.seg_x.append(r["xs"][-1])
            self.stack.append(candidates(self.seg, chosen[-1]))
            since_anchor += 1
            if since_anchor >= self.ANCHOR_EVERY:
                since_anchor = 0
                self.rebuild(len(self.committed))
            x = r["xs"][-1]
            if x > furthest + 300:
                furthest = x
                self.log(f"  x={x:7.0f} segments={len(self.committed)} evals={self.evals} ticks={self.ticks} "
                         f"anchors={self.anchors} drifts={self.drifts}")
        self.log(f"  budget exhausted at {len(self.committed)} segments (furthest x {furthest:.0f})")
        return None

    def finish(self, actions, t0):
        """Verify the full action list from a clean 0% run (practice off)."""
        self.drop_checkpoints()
        self.cps = []
        self.reset_zero()
        r = self.run(actions)
        verified = r["terminal"] == "complete"
        self.log(f"  verification from 0%: {r['terminal']} after {r['decisions']} decisions "
                 f"(anchors {self.anchors}, drifts {self.drifts})")
        return {"actions": actions, "k": K, "verified": verified, "evals": self.evals, "search_ticks": self.ticks,
                "anchors": self.anchors, "drifts": self.drifts,
                "wall_s": round(time.perf_counter() - t0, 2), "decisions": len(actions)}


def level_spec(name: str) -> dict:
    kind, _, rest = name.partition(":")
    if kind == "main":
        return {"kind": "main", "id": int(rest)}
    if kind == "drill":
        family, variant = rest.split("/")
        for root in (ROOT / "levels/drills", ROOT / "levels/drills/m5"):
            p = root / family / f"{variant}.txt"
            if p.exists():
                return {"kind": "level_string", "name": f"{family}-{variant}", "data": p.read_text().strip()}
        raise FileNotFoundError(name)
    if kind == "online":
        rec = json.loads((ROOT / f"levels/online/{rest}.json").read_text(encoding="utf-8"))
        return {"kind": "level_string", "name": f"online-{rest}", "data": rec["data"]}
    raise ValueError(name)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--slot", type=int, default=0)
    ap.add_argument("--level", action="append", required=True)
    ap.add_argument("--output", type=Path, default=ROOT / "build/m5c")
    ap.add_argument("--seg", type=int, default=8)
    ap.add_argument("--look", type=int, default=28)
    ap.add_argument("--budget", type=int, default=20000)
    a = ap.parse_args()
    a.output.mkdir(parents=True, exist_ok=True)
    d = discovery(a.slot)
    with BridgeClient(NamedPipeTransport(d["pipe"])) as client:
        client.require_isolated()
        try:
            client.request("quit_level")
        except RemoteError:
            pass
        client.request("set_mode", mode="dedicated")
        for name in a.level:
            print(f"{name}:", flush=True)
            res = Solver(client, level_spec(name), seg=a.seg, look=a.look, budget=a.budget,
                         log=lambda m: print(m, flush=True)).solve()
            out = a.output / (name.replace(":", "_").replace("/", "_") + ".json")
            out.write_text(json.dumps({"level": name, "result": res}, indent=1), encoding="utf-8")
            print(f"  -> {out.name}: {'VERIFIED CLEAR' if res and res['verified'] else 'no verified clear'}", flush=True)
            client.request("quit_level")
        client.request("set_mode", mode="normal")


if __name__ == "__main__":
    main()
