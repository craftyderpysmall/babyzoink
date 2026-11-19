"""GD memory per slot across levels: load the largest M6 online training levels one after another and
record the GD process's working set, private bytes and peak after each load, plus free system RAM.

Usage (slot claimed, GD running): python -I tools/m7/mem_probe.py --slot 0 [--count 8] [--out build/m7/mem.json]
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "m7"))
sys.path.insert(0, str(ROOT / "tools" / "m6"))
from gdbot.instances import discovery  # noqa: E402
from gdbot.protocol import BridgeClient, NamedPipeTransport  # noqa: E402
from perf_bench import Proc  # noqa: E402
from solve_pool import levels  # noqa: E402

import ctypes  # noqa: E402


class MEMSTAT(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong)] + [
        (n, ctypes.c_ulonglong) for n in ("total", "avail", "pagetotal", "pageavail", "virttotal", "virtavail", "ext")]


def avail_mb():
    m = MEMSTAT()
    m.dwLength = ctypes.sizeof(m)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
    return round(m.avail / 2**20)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--slot", type=int, default=0)
    ap.add_argument("--count", type=int, default=8)
    ap.add_argument("--out", default=str(ROOT / "build/m7/mem.json"))
    a = ap.parse_args()
    pool = sorted(levels(ROOT / "build/m6-scale", "online"), key=lambda x: -len(x[3]["data"]))[: a.count]
    d = discovery(a.slot)
    proc = Proc(d["pid"])
    rows = [{"stage": "menu", **proc.mem_mb(), "avail_system_mb": avail_mb()}]
    with BridgeClient(NamedPipeTransport(d["pipe"])) as c:
        c.require_isolated()
        c.request("set_mode", mode="dedicated")
        for key, name, _, spec in pool:
            t = time.perf_counter()
            c.load_level(spec)
            ep = c.request("reset", start={"kind": "zero"})["episode"]
            r = c.request("step_seq", episode=ep, actions=[0] * 500, k=4)
            row = {"stage": key, "name": name, "payload_kb": len(spec["data"]) // 1024, "load_s": round(time.perf_counter() - t, 1),
                   "ticks": r["ticks_advanced"], **{k: round(v) for k, v in proc.mem_mb().items()}, "avail_system_mb": avail_mb()}
            rows.append(row)
            print(json.dumps(row), flush=True)
            c.request("quit_level")
            time.sleep(1.0)
        rows.append({"stage": "menu-after", **{k: round(v) for k, v in proc.mem_mb().items()}, "avail_system_mb": avail_mb()})
        print(json.dumps(rows[-1]))
        c.request("set_mode", mode="normal")
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(rows, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
