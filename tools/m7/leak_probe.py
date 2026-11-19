"""Which bot pattern grows GD memory? Runs each M5c-solver pattern in isolation on one level and records
the GD process's private bytes and working set after every batch.

Phases (each --iters iterations, same level, actions from a verified solution so the player survives):
  zero      practice off: reset to 0% + step_seq of --decisions decisions
  practice  practice on, one bot checkpoint at --cp-at decisions: reset to it + step_seq (GD's own
            auto-checkpoints fire and the bridge blocks them)
  keep      practice stays on: reset {"kind":"zero","practice":true} + step_seq (the fix for toggle)
  toggle    set_practice off/on + reset to 0% + step_seq (the solver's restore() at depth 0)
  cpcycle   practice on: reset to 0%, step, checkpoint_create, checkpoint_pop
Stops early when available system RAM falls below --min-avail-mb.
Usage (slot claimed, GD running): python -I tools/m7/leak_probe.py --slot 0 [--iters 300]
"""
import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "m7"))
sys.path.insert(0, str(ROOT / "tools" / "m5c"))
from gdbot.instances import discovery, instance_dir  # noqa: E402
from gdbot.protocol import BridgeClient, NamedPipeTransport  # noqa: E402
from mem_probe import avail_mb  # noqa: E402
from perf_bench import Proc  # noqa: E402
from solver import level_spec  # noqa: E402


def blocked(slot):
    hits = re.findall(r"(?:blocked|discarded) non-bot storeCheckpoint #(\d+)",
                      (instance_dir(slot) / "bridge.log").read_text(encoding="utf-8", errors="replace"))
    return int(hits[-1]) if hits else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--slot", type=int, default=0)
    ap.add_argument("--solution", default=str(ROOT / "build/m5c/main_1.json"))
    ap.add_argument("--iters", type=int, default=300)
    ap.add_argument("--batch", type=int, default=50)
    ap.add_argument("--decisions", type=int, default=1500)
    ap.add_argument("--cp-at", type=int, default=400)
    ap.add_argument("--phases", nargs="+", default=["zero", "practice", "toggle", "cpcycle"])
    ap.add_argument("--min-avail-mb", type=int, default=1200)
    ap.add_argument("--out", default=str(ROOT / "build/m7/leak.json"))
    a = ap.parse_args()
    sol = json.loads(Path(a.solution).read_text(encoding="utf-8"))
    acts, k = sol["result"]["actions"], sol["result"]["k"]
    d = discovery(a.slot)
    proc = Proc(d["pid"])
    rows = []
    with BridgeClient(NamedPipeTransport(d["pipe"])) as c:
        c.require_isolated()
        c.request("set_mode", mode="dedicated")
        c.load_level(level_spec(sol["level"]))

        def zero():
            return c.request("reset", start={"kind": "zero"})["episode"]

        for phase in a.phases:
            seg = acts[: a.decisions]
            if phase == "keep":
                zero()
                c.request("set_practice", enabled=True)
            if phase == "practice":
                ep = zero()
                c.request("set_practice", enabled=True)
                c.request("step_seq", episode=ep, actions=acts[: a.cp_at], k=k)
                c.request("checkpoint_create")
                seg = acts[a.cp_at: a.cp_at + a.decisions]
            m0, b0 = proc.mem_mb(), blocked(a.slot)
            for i in range(1, a.iters + 1):
                if phase == "zero":
                    ep = zero()
                elif phase == "practice":
                    ep = c.request("reset", start={"kind": "checkpoint"})["episode"]
                elif phase == "keep":  # practice stays on: reset {"kind":"zero","practice":true}
                    ep = c.request("reset", start={"kind": "zero", "practice": True})["episode"]
                elif phase == "toggle":
                    c.request("set_practice", enabled=False)
                    ep = zero()
                    c.request("set_practice", enabled=True)
                else:
                    ep = zero()
                    c.request("set_practice", enabled=True)
                    c.request("step_seq", episode=ep, actions=acts[: a.cp_at], k=k)
                    c.request("checkpoint_create")
                    c.request("checkpoint_pop")
                if phase != "cpcycle":
                    c.request("step_seq", episode=ep, actions=seg, k=k)
                if i % a.batch == 0:
                    m = proc.mem_mb()
                    row = {"phase": phase, "iter": i, "private_mb": round(m["private"]), "ws_mb": round(m["working_set"]),
                           "d_private_mb": round(m["private"] - m0["private"]), "blocked_cps": blocked(a.slot) - b0,
                           "avail_mb": avail_mb()}
                    rows.append(row)
                    print(json.dumps(row), flush=True)
                    if row["avail_mb"] < a.min_avail_mb:
                        print("stopping: system RAM low", flush=True)
                        break
            if phase == "practice":
                c.request("checkpoint_pop")
            if rows and rows[-1]["avail_mb"] < a.min_avail_mb:
                break
        c.request("set_practice", enabled=False)
        zero()
        c.request("set_mode", mode="normal")
        c.request("quit_level")
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(rows, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
