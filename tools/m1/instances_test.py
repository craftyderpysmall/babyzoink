"""Live test for parallel GD instances (gdbot-launch --instance N).

Checks: each slot gets its own pid, pipe, discovery, log and save dir; isolation holds in every slot;
the same tape replayed on two instances at the same time gives byte-identical traces, equal to a solo
replay; aggregate throughput with two instances vs one; the user's mode.txt reaches both.
Usage (RUNTIME claimed; slot 0 may be running or not):
  python -I tools/m1/instances_test.py [--launcher mod/build-dev/Release/gdbot-launch.exe] [--slots 1 2]
"""
import argparse
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from gdbot.instances import BOT, instance_dir, launch, stop_slot  # noqa: E402
from gdbot.protocol import BridgeClient, NamedPipeTransport  # noqa: E402
from gdbot.replay import Tape, diff_traces, replay  # noqa: E402

TAPE = ROOT / "levels/drills/tapes/triple-spike/train-1102.json"
results = []


def check(name, cond, ev):
    results.append((name, bool(cond)))
    print(f"[{'PASS' if cond else 'FAIL'}] {name}: {ev}", flush=True)


def run_tape(pipe, tape, out, key):
    with BridgeClient(NamedPipeTransport(pipe)) as client:
        hello = client.require_isolated()
        client.request("set_mode", mode="dedicated")
        started = time.perf_counter()
        rows = replay(client, tape, settings=tape.settings, seed=tape.seed, trace=True)
        out[key] = {"rows": rows, "wall_s": time.perf_counter() - started, "hello": hello,
                    "mode": client.request("set_mode", mode="normal")}
        client.request("quit_level")
        time.sleep(2.0)  # let the menu transition finish before the client disconnects


def parallel(discs, tape):
    out, threads = {}, []
    for slot, d in discs.items():
        t = threading.Thread(target=run_tape, args=(d["pipe"], tape, out, slot))
        threads.append(t)
        t.start()
    for t in threads:
        t.join()
    return out


def main(launcher, slots):
    tape = Tape.load(TAPE)
    real_save = Path(os.environ["LOCALAPPDATA"]) / "GeometryDash"
    real_before = {p: p.stat().st_mtime_ns for p in real_save.glob("*.dat")} if real_save.exists() else {}
    discs = {}
    for slot in slots:
        discs[slot] = launch(slot, launcher=launcher)
        print(f"slot {slot}: {discs[slot]}", flush=True)
    time.sleep(6)  # let both reach the menu
    pids = {d["pid"] for d in discs.values()}
    pipes = {d["pipe"] for d in discs.values()}
    check("distinct pids and pipes", len(pids) == len(slots) == len(pipes), discs)
    check("discovery reports its slot", all(d.get("instance") == s for s, d in discs.items()),
          {s: d.get("instance") for s, d in discs.items()})
    check("per-slot logs", all((instance_dir(s) / "bridge.log").exists() for s in slots),
          [str(instance_dir(s) / "bridge.log") for s in slots])

    solo = parallel({slots[0]: discs[slots[0]]}, tape)[slots[0]]
    both = parallel(discs, tape)
    for s in slots:
        h = both[s]["hello"]
        check(f"slot {s} isolated", h["isolation"]["saves_redirected"], h["isolation"])
        diff = diff_traces(solo["rows"], both[s]["rows"])
        check(f"slot {s} parallel trace == solo trace", diff is None and solo["rows"][-1].get("terminal") == "complete",
              f"{len(both[s]['rows'])} rows, terminal {both[s]['rows'][-1].get('terminal')}, diff {diff}")
    ticks = len(solo["rows"])
    solo_rate = ticks / solo["wall_s"]
    agg = len(slots) * ticks / max(b["wall_s"] for b in both.values())
    check("parallel throughput above solo", agg > solo_rate * 1.2,
          f"solo {solo_rate:,.0f} ticks/s; {len(slots)} instances {agg:,.0f} ticks/s aggregate")
    for s in slots:
        saves = list((instance_dir(s) / "save").glob("*"))
        check(f"slot {s} save dir used", bool(saves), [p.name for p in saves][:4])

    mode_file = BOT / "mode.txt"
    previous = mode_file.read_text(encoding="utf-8") if mode_file.exists() else None
    try:
        mode_file.write_text("background", encoding="utf-8")
        time.sleep(2.5)
        modes = {}
        for s, d in discs.items():
            with BridgeClient(NamedPipeTransport(d["pipe"])) as c:
                modes[s] = c.hello().get("mode")
        check("shared mode.txt reaches every slot", all(m == "background" for m in modes.values()), modes)
    finally:
        if previous is None:
            mode_file.write_text("auto", encoding="utf-8")
        else:
            mode_file.write_text(previous, encoding="utf-8")
    time.sleep(1.5)
    real_after = {p: p.stat().st_mtime_ns for p in real_save.glob("*.dat")} if real_save.exists() else {}
    check("real save untouched", real_before == real_after, f"{len(real_after)} files")
    for s in discs:
        stop_slot(s)  # verified: only this slot's bot GD, never a reused pid
    passed = sum(ok for _, ok in results)
    print(f"{passed}/{len(results)} passed", flush=True)
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--launcher", type=Path, default=ROOT / "mod/build-dev/Release/gdbot-launch.exe")
    ap.add_argument("--slots", type=int, nargs="+", default=[1, 2])
    a = ap.parse_args()
    sys.exit(main(a.launcher, a.slots))
