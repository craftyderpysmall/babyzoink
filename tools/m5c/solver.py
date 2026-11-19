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
import random
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
    # Stall escape (#31): depth-first backtracking only reaches about one segment back within budget, but
    # tools/m6/stall_probe.py found stalls whose fix is 2-8 segments back (Dark Paradise: no pass from 0-1
    # back in 600 random tries; passes within 3-11 tries from 2-8 back). When the furthest depth hasn't
    # grown for STALL_EVALS evaluations, try random continuations from a few segments back and adopt one
    # that survives past the stall.
    STALL_EVALS = 400
    ESCAPE_BACKS = (2, 4, 8, 1)
    ESCAPE_TRIES = 40
    ESCAPE_AHEAD = 6       # segments past the stall a continuation must survive (plus the lookahead)

    def __init__(self, client, level: dict, *, seg=8, look=28, budget=20000, log=print, progress=None):
        self.c, self.level, self.seg, self.look, self.budget, self.log = client, level, seg, look, budget, log
        self.evals = 0
        self.ticks = 0
        self.verification_attempts = 0
        self.progress = progress              # Path for resumable state (saved at every re-anchor)

    def save_progress(self):
        if self.progress:
            tmp = self.progress.with_suffix(".tmp")
            tmp.write_text(json.dumps({"committed": self.committed, "seg_x": self.seg_x,
                                       "bad": sorted(self.bad), "evals": self.evals, "ticks": self.ticks,
                                       "verification_attempts": self.verification_attempts}),
                           encoding="utf-8")
            tmp.replace(self.progress)

    def load_progress(self):
        if self.progress and self.progress.exists():
            d = json.loads(self.progress.read_text(encoding="utf-8"))
            self.committed, self.seg_x, self.bad = d["committed"], d["seg_x"], set(d["bad"])
            self.evals, self.ticks = d["evals"], d["ticks"]
            self.verification_attempts = d.get("verification_attempts", self.verification_attempts)
            self.stack = [self.choices(0)] + [self.choices(s[-1]) for s in self.committed]
            self.log(f"  resuming at segment {len(self.committed)} (x {self.seg_x[-1] if self.seg_x else 0:.0f}); "
                     f"the replay check re-verifies the saved prefix")

    # -- bridge helpers -------------------------------------------------------------------------
    def reset_zero(self):
        reply = self.c.request("reset", start={"kind": "zero"})
        self.ep = reply["episode"]
        return reply

    def restore(self):
        """Go to the newest restore point: a real checkpoint, or a clean 0% start for depth 0."""
        if self.cps[-1] == 0:
            reply = self.reset_zero()
            self.c.request("set_practice", enabled=True)
        else:
            reply = self.c.request("reset", start={"kind": "checkpoint"})
            self.ep = reply["episode"]
        return reply

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
    def choices(self, previous):
        return candidates(self.seg, previous)

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
        """Candidate viability, or None if the restore did not reproduce the current boundary."""
        pre = self.prefix()
        check_restore = self.cps[-1] > 0
        best = -1
        for follow in self.followups():
            if self.evals >= self.budget:
                break
            self.restore()
            self.evals += 1
            r = self.run(pre + cand + follow, xs=check_restore)
            if check_restore and (len(r["xs"]) < len(pre) or
                                  abs(r["xs"][len(pre) - 1] - self.seg_x[-1]) > 1e-3):
                return None
            survived = r["decisions"] - len(pre)
            if r["terminal"] == "complete":
                return True, True, (cand + follow)[:survived + 1]
            if survived >= len(cand) + len(follow):
                return True, False, survived
            best = max(best, survived)
            if survived < len(cand):          # died inside the segment: no follow-up can help
                break
        return False, False, best

    def repair_boundary(self):
        """Exclude the restore point that failed and retry candidates from a fresh replay."""
        depth = len(self.committed)
        base = self.cps[-1]
        if base:
            self.bad.add(base)
        self.log(f"  restore did not reproduce depth {depth} from checkpoint depth {base}: re-anchoring")
        # If the older fallback failed across a long replay, retry from zero before
        # spending another full replay on each preceding checkpoint.
        older_failed = 0 < base < depth - self.KEEP_CHECKPOINTS
        self.rebuild(depth, allow_older_checkpoint=not older_failed)
        if len(self.committed) == depth:
            self.stack[-1] = self.choices(self.committed[-1][-1] if depth else 0)
        self.save_progress()

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

    # -- stall escape (#31) ------------------------------------------------------------------------
    def _random_tail(self, rng, n):
        out, state = [], rng.random() < 0.5
        while len(out) < n:
            out += [int(state)] * (1 + int(rng.expovariate(1.0 / 3)))
            state = not state
        return out[:n]

    def escape(self):
        """Random continuations from a few segments back, each checked by a clean replay from 0%.
        Returns True if the committed path was replaced by one that survives past the stall."""
        depth = len(self.committed)
        rng = random.Random(1000003 * depth + self.evals)
        self.escapes += 1
        for b in self.ESCAPE_BACKS:
            if b > depth:
                continue
            base = depth - b
            prefix = [a for s in self.committed[:base] for a in s]
            n_seg = b + self.ESCAPE_AHEAD
            for _ in range(self.ESCAPE_TRIES):
                if self.evals >= self.budget:
                    self.rebuild(len(self.committed))
                    return False
                tail = self._random_tail(rng, n_seg * self.seg + self.look)
                self.reset_zero()
                self.evals += 1
                r = self.run(prefix + tail)
                done = r["decisions"] - len(prefix)
                if r["terminal"] != "complete" and done < len(tail):
                    continue
                keep = tail[:n_seg * self.seg]
                self.log(f"  stall escape at segment {depth}: rewound {b}, adopted {n_seg} segments "
                         f"({r['terminal'] or 'survived'}; {self.evals} evals)")
                self.drop_checkpoints()
                self.cps = [0]
                del self.committed[base:], self.seg_x[base:]
                del self.stack[base + 1:]
                self.rebuild(base)
                for i in range(n_seg):
                    if not self.adopt(keep[i * self.seg:(i + 1) * self.seg]):
                        break
                return True
        self.log(f"  stall escape at segment {depth}: no continuation from {self.ESCAPE_BACKS} segments back")
        # trials reset to 0% with practice off, which drops every checkpoint: rebuild the restore points
        self.rebuild(len(self.committed))
        return False

    def adopt(self, seg):
        """Commit a given segment on the live path (same steps as a searched commit)."""
        depth = len(self.committed)
        self.restore()
        pr = self.run(self.prefix())
        if pr["terminal"] or (depth and abs(pr["player"]["x"] - self.seg_x[-1]) > 1e-3):
            self.repair_boundary()
            return False
        self.committed.append(seg)
        r = self.run_segment(seg, depth + 1, checkpoint=self.can_checkpoint(depth + 1))
        if r["terminal"]:
            self.committed.pop()
            if self.cps[-1] == depth + 1:
                self.c.request("checkpoint_pop")
                self.cps.pop()
            return False
        self.seg_x.append(r["xs"][-1])
        self.stack.append(self.choices(seg[-1]))
        return True

    # -- re-anchoring (backstop) ------------------------------------------------------------------
    def rebuild(self, target, *, allow_older_checkpoint=True):
        """Replay from 0% and rebuild recent checkpoints, falling back to an older release if needed."""
        self.anchors += 1
        self.drop_checkpoints()
        self.cps = [0]
        self.reset_zero()
        self.c.request("set_practice", enabled=True)
        eligible = [depth for depth in range(1, target + 1) if self.can_checkpoint(depth)]
        checkpoints = {depth for depth in eligible if depth >= target - self.KEEP_CHECKPOINTS}
        if allow_older_checkpoint and not checkpoints and eligible:
            checkpoints.add(eligible[-1])
        for depth in range(target):
            r = self.run_segment(self.committed[depth], depth + 1, checkpoint=depth + 1 in checkpoints)
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
                self.stack[depth] = self.choices(self.committed[-1][-1] if self.committed else 0)
                return self.rebuild(depth, allow_older_checkpoint=allow_older_checkpoint)
        return target

    def solve(self):
        self.c.load_level(self.level)
        self.committed, self.seg_x = [], []   # committed segments and the x recorded at each one's end
        self.stack = [self.choices(0)]         # candidate iterators per depth (depth = len(committed))
        self.anchors = self.drifts = 0
        self.bad = set()                      # depths whose checkpoint proved inexact anyway
        self.cps = [0]                        # restore points (depths); 0 = clean reset, not a checkpoint
        self.load_progress()
        self.rebuild(len(self.committed))
        furthest, t0, since_anchor = 0.0, time.perf_counter(), 0
        self.escapes = 0
        best_depth, best_at = len(self.committed), self.evals
        while self.evals < self.budget:
            depth = len(self.committed)
            if depth > best_depth:
                best_depth, best_at = depth, self.evals
            elif self.evals - best_at >= self.STALL_EVALS:
                best_at = self.evals          # one escape attempt per STALL_EVALS without progress
                if self.escape():
                    self.save_progress()
                    continue
            chosen = None
            stalled = False
            for cand in self.stack[-1]:
                if depth <= best_depth and self.evals - best_at >= self.STALL_EVALS:
                    stalled = True            # one segment's candidates can cost ~2,500 evals: check inside too
                    break
                trial = self.evaluate(cand)
                if trial is None:
                    self.repair_boundary()
                    break
                ok, complete, survived = trial
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
                    self.save_progress()
                    return None
                # every candidate failed: backtrack one segment
                if self.cps[-1] == depth:
                    self.c.request("checkpoint_pop")
                    self.cps.pop()
                self.committed.pop(), self.seg_x.pop(), self.stack.pop()
                continue
            if chosen is None:
                continue                      # (also when stalled: the escape runs at the top of the loop)
            self.restore()
            base = self.cps[-1]
            pr = self.run(self.prefix())      # warm-up + skipped segments up to the current depth
            if pr["terminal"] or (depth and abs(pr["player"]["x"] - self.seg_x[-1]) > 1e-3):
                self.repair_boundary()
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
            self.stack.append(self.choices(chosen[-1]))
            since_anchor += 1
            if since_anchor >= self.ANCHOR_EVERY:
                since_anchor = 0
                self.rebuild(len(self.committed))
                self.save_progress()
            x = r["xs"][-1]
            if x > furthest + 300:
                furthest = x
                self.log(f"  x={x:7.0f} segments={len(self.committed)} evals={self.evals} ticks={self.ticks} "
                         f"anchors={self.anchors} drifts={self.drifts}")
        self.log(f"  budget exhausted at {len(self.committed)} segments (furthest x {furthest:.0f})")
        self.save_progress()
        return None

    def finish(self, actions, t0):
        """Verify the full action list from a clean 0% run (practice off)."""
        self.drop_checkpoints()
        self.cps = [0]
        self.reset_zero()
        self.verification_attempts += 1
        self.save_progress()
        r = self.run(actions)
        verified = r["terminal"] == "complete"
        self.log(f"  verification from 0%: {r['terminal']} after {r['decisions']} decisions "
                 f"(anchors {self.anchors}, drifts {self.drifts})")
        return {"actions": actions, "k": K, "verified": verified, "evals": self.evals, "search_ticks": self.ticks,
                "verification_attempts": self.verification_attempts,
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
            out = a.output / (name.replace(":", "_").replace("/", "_") + ".json")
            prior = json.loads(out.read_text(encoding="utf-8")) if out.exists() else None
            if prior and prior.get("result") and prior["result"].get("verified"):
                print("  already solved (verified); skipping", flush=True)
                continue
            res = Solver(client, level_spec(name), seg=a.seg, look=a.look, budget=a.budget,
                         log=lambda m: print(m, flush=True), progress=out.with_suffix(".progress.json")).solve()
            out.write_text(json.dumps({"level": name, "result": res}, indent=1), encoding="utf-8")
            print(f"  -> {out.name}: {'VERIFIED CLEAR' if res and res['verified'] else 'no verified clear'}", flush=True)
            client.request("quit_level")
        client.request("set_mode", mode="normal")


if __name__ == "__main__":
    main()
