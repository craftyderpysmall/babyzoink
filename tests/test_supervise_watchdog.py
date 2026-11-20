"""#36: the supervisor restarts a hung slot, but never a quiet search that is still working."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/m6"))

import supervise  # noqa: E402


def test_rotation_keeps_only_the_previous_oversized_log(tmp_path):
    log = tmp_path / "slot.log"
    previous = tmp_path / "slot.log.prev"
    supervise.rotate_log(log, limit=4)
    log.write_bytes(b"1234")
    supervise.rotate_log(log, limit=4)
    assert log.exists() and not previous.exists()
    log.write_bytes(b"12345")
    supervise.rotate_log(log, limit=4)
    assert not log.exists() and previous.read_bytes() == b"12345"
    log.write_bytes(b"67890")
    supervise.rotate_log(log, limit=4)
    assert not log.exists() and previous.read_bytes() == b"67890"


def drive(dog, minutes, log_grows, cpu_per_min):
    size, cpu = 0, 0.0
    for m in range(minutes * 2):  # 30 s polls
        t = m * 30.0
        if log_grows:
            size += 100
        cpu += cpu_per_min / 2
        if dog.hung(t, size, cpu):
            return t
    return None


def test_frozen_gd_is_hung_after_quiet_period():
    t = drive(supervise.Watchdog(), 30, log_grows=False, cpu_per_min=0.0)
    assert t is not None and t >= supervise.QUIET_S


def test_quiet_but_busy_search_is_not_hung():
    # A stall like Dark Paradise: no progress lines for an hour, GD busy running step_seq.
    assert drive(supervise.Watchdog(), 60, log_grows=False, cpu_per_min=50.0) is None


def test_logging_worker_is_not_hung():
    assert drive(supervise.Watchdog(), 60, log_grows=True, cpu_per_min=0.0) is None


def test_unreadable_cpu_never_triggers():
    dog = supervise.Watchdog()
    assert not any(dog.hung(m * 30.0, 0, None) for m in range(200))
