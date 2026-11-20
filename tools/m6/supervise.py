"""Keep one GD slot working through a list of M6 solve_pool jobs, restarting the slot whenever GD outgrows
its memory cap (solve_pool exits 75 after saving progress; the solver resumes from the saved prefix).

Each job is the solve_pool arguments after --slot, e.g. "--split drills" or "--split online --shards 2 --shard 1".
Usage (claim the slot first; Steam must be running):
  build/gdbot-venv/Scripts/python.exe -u tools/m6/supervise.py --slot 1 --job "--split drills" \
      --job "--split online --shards 2 --shard 1" [--max-private-mb 1500] [--min-avail-mb 900] [--log PATH]
State: build/m6-scale/supervise-slot<N>.json (pid, job, restarts, state).
"""
import argparse
import json
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from gdbot.instances import launch, owned_pid, stop_slot  # noqa: E402

RESTART = 75
MAX_RESTARTS_PER_JOB = 40
HUNG = -9  # the watchdog stopped a worker that had made no progress
QUIET_S = 600  # a hang: no new worker output for this long ...
IDLE_CPU_S = 1.0  # ... and GD used less than this much CPU over the last QUIET_S / 2
LOG_LIMIT = 5 * 1024 * 1024


def rotate_log(path: Path, limit: int = LOG_LIMIT) -> None:
    """Keep one previous log. Run only between workers, when their output handle is closed."""
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        return
    if size > limit:
        path.replace(path.with_suffix(path.suffix + ".prev"))


def gd_cpu_s(pid):
    """Total CPU seconds of `pid`, or None if it can't be read."""
    sys.path.insert(0, str(ROOT / "tools/m7"))
    from perf_bench import Proc  # noqa: E402
    try:
        return Proc(pid).cpu_s()
    except OSError:
        return None


class Watchdog:
    """Decides when a worker is hung: its log stopped growing AND the slot's GD stopped using CPU.

    A stalled-but-working search can be quiet for a long time (no progress lines), but GD stays busy running
    step_seq, so log silence alone is not a hang. A frozen GD (GL stall, dialog, deadlock) shows both.
    """

    def __init__(self, quiet_s=QUIET_S, idle_cpu_s=IDLE_CPU_S):
        self.quiet_s, self.idle_cpu_s = quiet_s, idle_cpu_s
        self.last_size, self.last_change = None, None
        self.cpu = []  # (time, cpu seconds)

    def hung(self, now, log_size, cpu_s):
        if self.last_size is None or log_size != self.last_size:
            self.last_size, self.last_change = log_size, now
        if cpu_s is not None:
            self.cpu.append((now, cpu_s))
            self.cpu = [(t, c) for t, c in self.cpu if now - t <= self.quiet_s]
        if now - self.last_change < self.quiet_s or not self.cpu:
            return False
        window = [(t, c) for t, c in self.cpu if now - t <= self.quiet_s / 2]
        if len(window) < 2 or window[-1][0] - window[0][0] < self.quiet_s / 4:
            return False
        return window[-1][1] - window[0][1] < self.idle_cpu_s


def run_worker(cmd, log_path, pid, *, poll_s=30.0, watchdog=None, clock=time.monotonic, sleep=time.sleep):
    """Run the worker; stop it (it is our own child) if the watchdog says it is hung. Returns its exit code."""
    watchdog = watchdog or Watchdog()
    with open(log_path, "a", encoding="utf-8") as out:
        proc = subprocess.Popen(cmd, stdout=out, stderr=subprocess.STDOUT, cwd=ROOT)
        while True:
            try:
                return proc.wait(timeout=poll_s)
            except subprocess.TimeoutExpired:
                pass
            try:
                size = Path(log_path).stat().st_size
            except OSError:
                size = 0
            if watchdog.hung(clock(), size, gd_cpu_s(pid)):
                proc.kill()
                proc.wait()
                return HUNG


def alive(slot, pid):
    """True only while `pid` is still this slot's bot GD (exe path and start time checked, not just the name)."""
    return owned_pid(slot, pid) is not None


def steam_running():
    return "steam.exe" in subprocess.run(["tasklist", "/FI", "IMAGENAME eq steam.exe", "/NH"],
                                         capture_output=True, text=True).stdout.lower()


def close_slot(slot, log):
    # Never a bare taskkill on a pid from a file: stop_slot verifies the process is this slot's bot GD first.
    if not stop_slot(slot):
        log(f"slot {slot}: bot GD did not exit after taskkill")
        return False
    return True


def fresh_slot(slot, log, launcher=None):
    if not close_slot(slot, log):
        raise RuntimeError(f"slot {slot}: could not close the previous bot GD")
    for attempt in range(1, 6):
        if not steam_running():
            log("waiting for Steam (GD exits at startup without it)")
            time.sleep(60)
            continue
        try:
            # every supervisor launch is a recycle: keep the user's Ctrl+Alt+B / overlay / watch choices (M8)
            found = launch(slot, session="keep", **({"launcher": launcher} if launcher else {}))
        except (RuntimeError, OSError, subprocess.TimeoutExpired) as error:
            # e.g. the closed GD still holds the slot's bridge DLL copy for a moment after exiting
            log(f"slot {slot} launch failed (attempt {attempt}): {error}; retrying")
            time.sleep(15)
            continue
        time.sleep(8)
        if alive(slot, found["pid"]):
            log(f"slot {slot} up, pid {found['pid']}")
            return found["pid"]
        log(f"slot {slot} exited at startup (attempt {attempt}); retrying")
        time.sleep(20)
    raise RuntimeError(f"slot {slot} would not stay up")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--slot", type=int, required=True)
    ap.add_argument("--job", action="append", required=True)
    ap.add_argument("--budget", type=int, default=6000)
    ap.add_argument("--look", type=int, default=40)
    ap.add_argument("--present-every-ms", type=int, default=1000)
    ap.add_argument("--max-private-mb", type=int, default=1500)
    ap.add_argument("--min-avail-mb", type=int, default=900)
    ap.add_argument("--log", type=Path)
    ap.add_argument("--launcher", type=Path,
                    help="gdbot-launch.exe to use (e.g. mod/build/pinned-pre-cbf/ so a new bridge build can't reach this run)")
    a = ap.parse_args()
    state_path = ROOT / f"build/m6-scale/supervise-slot{a.slot}.json"
    log_path = a.log or ROOT / f"build/m6-scale/supervise-slot{a.slot}.log"
    state = {"slot": a.slot, "jobs": a.job, "restarts": 0, "state": "starting"}

    def log(message):
        line = f"[{datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S}Z] {message}"
        print(line, flush=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def save(**kw):
        state.update(kw, updated_utc=datetime.now(timezone.utc).isoformat())
        state_path.write_text(json.dumps(state, indent=1), encoding="utf-8")

    for job in a.job:
        restarts = 0
        while True:
            try:
                rotate_log(log_path)
            except OSError as error:
                log(f"log rotation failed: {error}")
            pid = fresh_slot(a.slot, log, a.launcher)
            save(state="running", job=job, game_pid=pid)
            cmd = [sys.executable, "-B", "-u", str(ROOT / "tools/m6/solve_pool.py"), "--slot", str(a.slot),
                   *shlex.split(job), "--budget", str(a.budget), "--look", str(a.look),
                   "--present-every-ms", str(a.present_every_ms),
                   "--max-private-mb", str(a.max_private_mb), "--min-avail-mb", str(a.min_avail_mb)]
            log(f"job '{job}': start (restart {restarts})")
            code = run_worker(cmd, log_path, pid)
            if code == HUNG:
                log(f"job '{job}': watchdog: no output for {QUIET_S // 60} min and GD idle; restarting the slot")
            if code == 0:
                log(f"job '{job}': finished")
                break
            restarts += 1
            state["restarts"] += 1
            if code != RESTART:
                log(f"job '{job}': worker exited with code {code}; relaunching the slot and resuming")
            if restarts > MAX_RESTARTS_PER_JOB:
                save(state=f"stopped: {restarts} restarts on job '{job}'")
                log("too many restarts; stopping")
                return 1
            time.sleep(5)
    if not close_slot(a.slot, log):
        save(state="done; slot still running (close it by hand)")
        return 1
    save(state="done")
    log("all jobs done; slot closed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
