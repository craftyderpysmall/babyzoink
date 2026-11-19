"""Per-slot throughput, CPU and memory for the live bridge, with and without draw-skip (set_render).

Replays a verified M5c search solution (default Stereo Madness, build/m5c/main_1.json) with step_seq
from a zero reset, repeatedly for --seconds per configuration, and records:
  ticks/s, GD process CPU (% of one core), frames drawn vs total, working set and private bytes;
  parity: the step_seq reply (tick, decisions, terminal, player) must match across configurations.
Usage (slot claimed, GD running in that slot):
  python -I tools/m7/perf_bench.py --slot 0 [--present 0 250 1000] [--seconds 20] [--out build/m7/perf.json]
"""
import argparse
import ctypes
import json
import sys
import time
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "m5c"))
from gdbot.instances import discovery  # noqa: E402
from gdbot.protocol import BridgeClient, NamedPipeTransport  # noqa: E402
from solver import level_spec  # noqa: E402

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
psapi = ctypes.WinDLL("psapi", use_last_error=True)


class PMC(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
        (n, ctypes.c_size_t) for n in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                                       "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage",
                                       "PagefileUsage", "PeakPagefileUsage", "PrivateUsage")]


class Proc:
    def __init__(self, pid):
        self.h = k32.OpenProcess(0x1000 | 0x0010, False, pid)  # QUERY_LIMITED_INFORMATION | VM_READ
        if not self.h:
            raise OSError(ctypes.get_last_error(), f"OpenProcess({pid})")

    def cpu_s(self):
        c, e, kt, ut = (wintypes.FILETIME() for _ in range(4))
        k32.GetProcessTimes(self.h, ctypes.byref(c), ctypes.byref(e), ctypes.byref(kt), ctypes.byref(ut))
        return sum((t.dwHighDateTime << 32 | t.dwLowDateTime) for t in (kt, ut)) / 1e7

    def mem_mb(self):
        m = PMC()
        m.cb = ctypes.sizeof(m)
        psapi.GetProcessMemoryInfo(self.h, ctypes.byref(m), m.cb)
        return {"working_set": m.WorkingSetSize / 2**20, "peak_working_set": m.PeakWorkingSetSize / 2**20,
                "private": m.PrivateUsage / 2**20}


class MEMSTAT(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong)] + [
        (n, ctypes.c_ulonglong) for n in ("total", "avail", "pagetotal", "pageavail", "virttotal", "virtavail", "ext")]


def avail_mb():
    """Available physical memory on the machine, in MB."""
    m = MEMSTAT()
    m.dwLength = ctypes.sizeof(m)
    k32.GlobalMemoryStatusEx(ctypes.byref(m))
    return round(m.avail / 2**20)


def parity_key(r):
    return {k: r.get(k) for k in ("tick", "ticks_advanced", "decisions", "terminal", "player")}


def run_config(c, proc, actions, k, present, mode, seconds):
    if present is not None:
        c.request("set_render", present_every_ms=present)
    f0 = c.request("set_render") if present is not None else None
    t0, cpu0, ticks, runs, first = time.perf_counter(), proc.cpu_s(), 0, 0, None
    while time.perf_counter() - t0 < seconds:
        ep = c.request("reset", start={"kind": "zero"})["episode"]
        r = c.request("step_seq", episode=ep, actions=actions, k=k)
        ticks += r["ticks_advanced"]
        runs += 1
        first = first or parity_key(r)
    wall, cpu = time.perf_counter() - t0, proc.cpu_s() - cpu0
    out = {"present_every_ms": present, "mode": mode, "runs": runs, "ticks": ticks, "wall_s": round(wall, 2),
           "ticks_per_s": round(ticks / wall), "cpu_pct_one_core": round(100 * cpu / wall, 1),
           "cpu_ms_per_1k_ticks": round(1000 * cpu / ticks * 1000, 2), "mem_mb": proc.mem_mb(), "parity": first}
    if f0:
        f1 = c.request("set_render")
        frames, drawn = f1["frames"] - f0["frames"], f1["presented"] - f0["presented"]
        out.update(frames=frames, presented=drawn, fps=round(frames / wall, 1))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--slot", type=int, default=0)
    ap.add_argument("--solution", default=str(ROOT / "build/m5c/main_1.json"))
    ap.add_argument("--present", type=int, nargs="+", default=[0, 250, 1000])
    ap.add_argument("--mode", default="dedicated", choices=("dedicated", "background"))
    ap.add_argument("--seconds", type=float, default=20.0)
    ap.add_argument("--truncate", type=int, default=150,
                    help="drop the last N decisions so runs end before the level does (each completion queues a "
                         "real-time end-animation callback; hundreds of them crash GD at quit_level)")
    ap.add_argument("--out", default=str(ROOT / "build/m7/perf.json"))
    a = ap.parse_args()
    sol = json.loads(Path(a.solution).read_text(encoding="utf-8"))
    actions, k = sol["result"]["actions"][: -a.truncate or None], sol["result"]["k"]
    d = discovery(a.slot)
    proc = Proc(d["pid"])
    results = {"slot": a.slot, "level": sol["level"], "decisions": len(actions), "k": k, "configs": []}
    with BridgeClient(NamedPipeTransport(d["pipe"])) as c:
        hello = c.require_isolated()
        has_render = hello.get("capabilities", {}).get("set_render", False)
        results["set_render_supported"] = has_render
        results["mem_menu_mb"] = proc.mem_mb()
        c.load_level(level_spec(sol["level"]))
        results["mem_level_loaded_mb"] = proc.mem_mb()
        c.request("set_mode", mode=a.mode)
        for p in a.present if has_render else [None]:
            r = run_config(c, proc, actions, k, p, a.mode, a.seconds)
            results["configs"].append(r)
            print(json.dumps({x: r[x] for x in r if x != "parity"}), flush=True)
        if has_render:
            c.request("set_render", present_every_ms=0)
        keys = [json.dumps(r["parity"], sort_keys=True) for r in results["configs"]]
        results["parity_identical"] = len(set(keys)) == 1
        print("parity identical across configs:", results["parity_identical"])
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps(results, indent=1), encoding="utf-8")
        print("wrote", a.out, flush=True)
        # Known pre-existing crash (also on the previous bridge): quit_level from mid-level after a long
        # dedicated run crashes GD in a CCFadeTo on a freed sprite atlas. Reset to tick 0 first.
        c.request("reset", start={"kind": "zero"})
        c.request("set_mode", mode="normal")
        c.request("quit_level")
        time.sleep(2.0)


if __name__ == "__main__":
    main()
