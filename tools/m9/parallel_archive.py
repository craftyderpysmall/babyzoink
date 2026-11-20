"""#59 parallel-slot archive: several game slots attack one stalled level at once (M9).

Each worker process drives its own slot with the full solver (GDBOT_SOLVER_V2=1 + GDBOT_SOLVER_ARCHIVE=1) on its own
COPY of the level's saved prefix. Workers differ only in the archive's random stream (a per-worker salt mixed into
Archive.digest), so their explorations diverge. The first verified clear wins and the other workers are stopped.
Shared solver files are not modified; the saved #19 files are never written.

Usage: python tools/m9/parallel_archive.py --level online:13124688 --slots 1 3 [--extra 3000] [--minutes 30]
Writes build/m9-research/parallel/<level>/{worker-<slot>.log, worker-<slot>.json, summary.json}.
"""
import argparse
import json
import multiprocessing as mp
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
POOL = ROOT / "build/m6-scale"


def worker(slot, level_key, salt, extra, out_dir, caps):
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    os.environ["GDBOT_SOLVER_V2"] = "1"
    os.environ["GDBOT_SOLVER_ARCHIVE"] = "1"
    from gdbot.instances import discovery
    from gdbot.protocol import BridgeClient, NamedPipeTransport
    from tools.m5c import archive as archive_mod
    from tools.m5c.solver import Solver

    original_init = archive_mod.Archive.__init__

    def salted_init(self, solver, seed):
        original_init(self, solver, seed)
        self.digest = f"{salt:016x}" + self.digest[16:]  # diverge the per-worker random stream only

    archive_mod.Archive.__init__ = salted_init
    archive_mod.Archive.MAX_TRIALS = caps["trials"]
    archive_mod.Archive.MAX_REPLAY_TICKS = caps["replay_ticks"]
    archive_mod.Archive.MAX_NODES = caps["nodes"]

    level_id = level_key.split(":", 1)[1]
    work = out_dir / f"worker-{slot}"
    work.mkdir(parents=True, exist_ok=True)
    prog = work / f"online_{level_id}.progress.json"
    saved = json.loads((POOL / f"solutions/online_{level_id}.progress.json").read_bytes())
    saved["input_timing"] = "cbf"  # fraction-free prefix: identical replay on the CBF bridge
    prog.write_text(json.dumps(saved), encoding="utf-8")
    level = {"kind": "level_string", "name": f"online-{level_id}",
             "data": json.loads((POOL / f"online/{level_id}.json").read_bytes())["data"]}
    log = open(out_dir / f"worker-{slot}.log", "w", encoding="utf-8")

    def say(m):
        if not m.startswith("  x=") or "segments=" in m:
            log.write(f"[{time.strftime('%H:%M:%S')}] {m}\n")
            log.flush()

    t0 = time.perf_counter()
    result = {"slot": slot, "salt": salt, "verified": False}
    with BridgeClient(NamedPipeTransport(discovery(slot)["pipe"])) as c:
        c.require_isolated()
        try:
            c.request("quit_level")
        except Exception:
            pass
        c.request("set_mode", mode="dedicated")
        s = Solver(c, level, budget=saved["evals"] + extra, progress=prog, look=40, log=say)
        res = s.solve()
        end = json.loads(prog.read_bytes())
        result.update(verified=bool(res and res.get("verified")), start_depth=len(saved["committed"]),
                      end_depth=len(end["committed"]), evals=end["evals"] - saved["evals"],
                      seconds=round(time.perf_counter() - t0, 1))
        if result["verified"]:
            (out_dir / "clear.json").write_text(json.dumps({"slot": slot, "actions": res["actions"], "k": res["k"]}),
                                                encoding="utf-8")
        try:
            c.request("quit_level")
        except Exception:
            pass
    (out_dir / f"worker-{slot}.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    log.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--level", required=True)
    ap.add_argument("--slots", type=int, nargs="+", required=True)
    ap.add_argument("--extra", type=int, default=3000, help="evaluations per worker beyond the saved prefix")
    ap.add_argument("--minutes", type=float, default=30)
    ap.add_argument("--trials", type=int, default=600)
    ap.add_argument("--replay-ticks", type=int, default=20_000_000)
    ap.add_argument("--nodes", type=int, default=20000)
    a = ap.parse_args()
    out = ROOT / "build/m9-research/parallel" / a.level.replace(":", "_") / f"{len(a.slots)}slots"
    out.mkdir(parents=True, exist_ok=True)
    (out / "clear.json").unlink(missing_ok=True)
    caps = {"trials": a.trials, "replay_ticks": a.replay_ticks, "nodes": a.nodes}
    procs = {s: mp.Process(target=worker, args=(s, a.level, 0x9E3779B97F4A7C15 * (i + 1) % (1 << 63), a.extra, out, caps))
             for i, s in enumerate(a.slots)}
    t0 = time.time()
    for p in procs.values():
        p.start()
    winner = None
    while any(p.is_alive() for p in procs.values()):
        if (out / "clear.json").exists():
            winner = json.loads((out / "clear.json").read_text())["slot"]
            break
        if time.time() - t0 > a.minutes * 60:
            break
        time.sleep(5)
    for p in procs.values():
        if p.is_alive():
            p.terminate()
        p.join(10)
    workers = [json.loads(f.read_text()) for f in sorted(out.glob("worker-*.json"))]
    summary = {"level": a.level, "slots": a.slots, "winner_slot": winner, "wall_s": round(time.time() - t0, 1),
               "workers": workers}
    (out / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
