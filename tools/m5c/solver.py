"""M5c search-based teacher: find a clear of a level by deterministic search, no human input.

GD in lockstep is deterministic, so a level can be solved segment by segment: from a restore point,
try candidate input patterns for the next S decisions (k=4 ticks each), keep the first one that
survives the segment plus a lookahead, commit it, checkpoint, and continue. If no candidate works,
back up one segment and take that segment's next candidate (depth-first search, bounded budget).
The final action list is verified by a clean run from 0% (practice off); only verified clears are
written as solutions/demos.

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


def alternating(n: int):
    return [(i // 2) % 2 for i in range(n)]


class Solver:
    """Checkpoint-backed depth-first segment search.

    Restore exactness (tools/m5c/restore_probe.py on the verified Stereo Madness clear): restoring a
    GD practice checkpoint and pressing immediately differs from the real run (the press is buffered;
    ship vy/y/rot also drift): 36/197 segment probes mismatched. With ONE released warm-up decision
    replayed between restore and the segment, 0/107 mismatched. So the checkpoint for depth d is
    created one decision before the boundary, only where that last decision is released (0), and
    every evaluation replays that 0 first. Depth 0 needs no checkpoint: its restore is a clean reset.
    Re-anchoring from a clean replay every ANCHOR_EVERY commits remains as a backstop.
    """
    ANCHOR_EVERY = 16
    KEEP_CHECKPOINTS = 12

    def __init__(self, client, level: dict, *, seg=8, look=28, budget=20000, log=print):
        self.c, self.level, self.seg, self.look, self.budget, self.log = client, level, seg, look, budget, log
        self.evals = 0
        self.ticks = 0

    # -- bridge helpers -------------------------------------------------------------------------
    def reset_zero(self):
        self.ep = self.c.request("reset", start={"kind": "zero"})["episode"]

    def restore(self):
        """Go to the newest restore point: a real checkpoint, or a clean 0% start for depth 0."""
        if self.cps[-1] == 0:
            self.reset_zero()
            self.c.request("set_practice", enabled=True)
        else:
            self.ep = self.c.request("reset", start={"kind": "checkpoint"})["episode"]

    def run(self, actions, xs=False):
        if not actions:
            return {"terminal": None, "decisions": 0, "xs": [], "ticks_advanced": 0}
        r = self.c.request("step_seq", episode=self.ep, actions=actions, k=K, xs=xs)
        self.ticks += r["ticks_advanced"]
        return r

    def drop_checkpoints(self):
        while True:
            try:
                if self.c.request("checkpoint_pop")["count"] == 0:
                    return
            except RemoteError:
                return

    # -- search ---------------------------------------------------------------------------------
    def followups(self):
        """Simple continuations that test whether the state after a segment is still viable. The
        lookahead must outlast a jump's airtime, or "not yet" looks fine when it is already too late."""
        L = self.look
        yield [0] * L
        for j in range(L):                    # a single tap at every point
            yield [0] * j + [1] + [0] * (L - j - 1)
        yield [1] * L
        yield alternating(L)

    def can_checkpoint(self, depth):
        """The checkpoint for `depth` sits before the last decision of segment depth-1, which must be
        a release (it is replayed as the warm-up); never at depths proven bad."""
        return depth > 0 and depth not in self.bad and self.committed[depth - 1][-1] == 0

    def prefix(self):
        """Inputs from the newest restore point to the current depth: the released warm-up decision
        (for a real checkpoint) plus any committed segments whose checkpoints were skipped."""
        base = self.cps[-1]
        warm = [0] if base > 0 else []
        return warm + [a for s in self.committed[base:] for a in s]

    def evaluate(self, cand):
        """Viability of a candidate at the current depth: (ok, complete, survived | finishing inputs)."""
        pre = self.prefix()
        best = -1
        for follow in self.followups():
            self.restore()
            self.evals += 1
            r = self.run(pre + cand + follow)
            survived = r["decisions"] - len(pre)
            if r["terminal"] == "complete":
                return True, True, (cand + follow)[:survived + 1]
            if survived >= len(cand) + len(follow):
                return True, False, survived
            best = max(best, survived)
            if survived < len(cand):          # died inside the segment: no follow-up can help
                break
        return False, False, best

    def run_segment(self, seg, depth_after, *, checkpoint):
        """Run one segment on the live path. With `checkpoint`, create the checkpoint for
        depth_after just before its last (released) decision. Returns the reply for the final part."""
        if checkpoint:
            r = self.run(seg[:-1])
            if r["terminal"]:
                return r
            self.c.request("checkpoint_create")
            self.cps.append(depth_after)
            return self.run(seg[-1:], xs=True)
        return self.run(seg, xs=True)

    # -- re-anchoring (backstop) ------------------------------------------------------------------
    def rebuild(self, target):
        """Replay committed[:target] from a clean 0% start (practice on), re-creating checkpoints for
        the last KEEP_CHECKPOINTS depths and checking each segment's end x against the search. On a
        mismatch, cut back to the last matching segment. Returns the matched depth."""
        self.anchors += 1
        self.drop_checkpoints()
        self.cps = [0]
        self.reset_zero()
        self.c.request("set_practice", enabled=True)
        for depth in range(target):
            want = depth + 1 >= target - self.KEEP_CHECKPOINTS and self.can_checkpoint(depth + 1)
            r = self.run_segment(self.committed[depth], depth + 1, checkpoint=want)
            end = r["xs"][-1] if r.get("xs") else None
            if r["terminal"] or end is None or abs(end - self.seg_x[depth]) > 1e-3:
                self.drifts += 1
                # The search reached this segment from an inexact restore at some depth <= `depth`.
                # Exclude a window of restore points below the first not-yet-excluded depth at once,
                # rather than one per re-anchor cycle.
                mark = depth
                while mark in self.bad and mark > 0:
                    mark -= 1
                for m in range(max(1, mark - 3), mark + 1):
                    self.bad.add(m)
                self.log(f"  drift at segment {depth} (replay {r['terminal'] or end} vs search "
                         f"{round(self.seg_x[depth], 3)}): cutting back; no checkpoints at "
                         f"{sorted(b for b in self.bad if b > depth - 20)}")
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
        self.bad = set()                      # depths whose checkpoint proved inexact anyway
        self.cps = [0]                        # restore points (depths); 0 = clean reset, not a checkpoint
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
                if self.cps[-1] == depth:
                    self.c.request("checkpoint_pop")
                    self.cps.pop()
                self.committed.pop(), self.seg_x.pop(), self.stack.pop()
                continue
            if chosen is None:
                continue
            self.restore()
            base = self.cps[-1]
            pr = self.run(self.prefix())      # warm-up + skipped segments up to the current depth
            if pr["terminal"]:
                # In practice mode a dead player is respawned, so never keep running after a death.
                self.log(f"  replay to depth {depth} died ({pr['terminal']}, base {base}): re-anchoring")
                self.rebuild(len(self.committed))
                continue
            self.committed.append(chosen)
            r = self.run_segment(chosen, depth + 1, checkpoint=self.can_checkpoint(depth + 1))
            if r["terminal"]:
                self.committed.pop()
                if self.cps[-1] == depth + 1:
                    self.c.request("checkpoint_pop")
                    self.cps.pop()
                self.log(f"  commit died where evaluation survived ({r['terminal']}, base {base}): re-anchoring")
                self.rebuild(len(self.committed))
                continue
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
        self.cps = [0]
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
