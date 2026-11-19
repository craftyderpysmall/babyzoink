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
from gdbot.instances import discovery, launch  # noqa: E402

RESTART = 75
MAX_RESTARTS_PER_JOB = 40


def alive(pid):
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
    return "GeometryDash" in out


def steam_running():
    return "steam.exe" in subprocess.run(["tasklist", "/FI", "IMAGENAME eq steam.exe", "/NH"],
                                         capture_output=True, text=True).stdout.lower()


def kill(pid):
    # Only ever the GD process this slot's discovery file names; never anything else.
    subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)


def fresh_slot(slot, log):
    try:
        old = discovery(slot)["pid"]
        if alive(old):
            kill(old)
            time.sleep(3)
    except (OSError, KeyError, ValueError):
        pass
    for attempt in range(1, 6):
        if not steam_running():
            log("waiting for Steam (GD exits at startup without it)")
            time.sleep(60)
            continue
        found = launch(slot)
        time.sleep(8)
        if alive(found["pid"]):
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
            pid = fresh_slot(a.slot, log)
            save(state="running", job=job, game_pid=pid)
            cmd = [sys.executable, "-B", "-u", str(ROOT / "tools/m6/solve_pool.py"), "--slot", str(a.slot),
                   *shlex.split(job), "--budget", str(a.budget), "--look", str(a.look),
                   "--present-every-ms", str(a.present_every_ms),
                   "--max-private-mb", str(a.max_private_mb), "--min-avail-mb", str(a.min_avail_mb)]
            log(f"job '{job}': start (restart {restarts})")
            with open(log_path, "a", encoding="utf-8") as out:
                code = subprocess.run(cmd, stdout=out, stderr=subprocess.STDOUT, cwd=ROOT).returncode
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
    try:
        kill(discovery(a.slot)["pid"])
    except (OSError, KeyError, ValueError):
        pass
    save(state="done")
    log("all jobs done; slot closed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
