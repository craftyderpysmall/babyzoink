"""#34: slot cleanup only ever touches the slot's own bot GD (exe path + creation time verified)."""
import json
import os
import time
from contextlib import contextmanager

import pytest

from gdbot import instances


@pytest.fixture
def slot_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(instances, "BOT", tmp_path)
    monkeypatch.setattr(instances, "GAME_EXE", tmp_path / "GeometryDash.exe")
    (tmp_path / "GeometryDash.exe").write_bytes(b"")
    (tmp_path / "bridge.json").write_text(json.dumps({"pid": 4242, "pipe": "x", "proto": 0}), encoding="utf-8")
    return tmp_path


def test_owned_when_exe_and_start_time_match(slot_dir):
    written = (slot_dir / "bridge.json").stat().st_mtime
    ident = lambda pid: (str(slot_dir / "GeometryDash.exe"), written - 5)
    assert instances.owned_pid(0, identity=ident) == 4242


def test_users_own_steam_gd_with_reused_pid_is_not_owned(slot_dir):
    written = (slot_dir / "bridge.json").stat().st_mtime
    ident = lambda pid: (r"C:\Program Files (x86)\Steam\steamapps\common\Geometry Dash\GeometryDash.exe", written - 5)
    assert instances.owned_pid(0, identity=ident) is None


def test_process_started_after_discovery_is_pid_reuse(slot_dir):
    written = (slot_dir / "bridge.json").stat().st_mtime
    ident = lambda pid: (str(slot_dir / "GeometryDash.exe"), written + 3600)
    assert instances.owned_pid(0, identity=ident) is None


def test_dead_process_and_foreign_pid(slot_dir):
    assert instances.owned_pid(0, identity=lambda pid: None) is None
    assert instances.owned_pid(0, 999, identity=lambda pid: ("x", 0)) is None


class FakeHandle:
    def __init__(self, slot_dir, *, image=None, ready=True):
        self.file = slot_dir / "bridge.json"
        self.image = image or slot_dir / "GeometryDash.exe"
        self.ready = ready
        self.calls = []

    @contextmanager
    def open(self, pid):
        self.calls.append(("open", pid))
        try:
            yield self
        finally:
            self.calls.append("close")

    def exited(self, timeout_s=0):
        self.calls.append(("wait", timeout_s))
        return bool(timeout_s) and self.ready

    def identity(self):
        self.calls.append("identity")
        return str(self.image), self.file.stat().st_mtime - 5

    def terminate(self):
        self.calls.append("terminate")
        return True


def test_stop_slot_never_terminates_unowned_process(slot_dir):
    process = FakeHandle(slot_dir, image=slot_dir / "notepad.exe")
    assert instances.stop_slot_result(0, open_process=process.open) == instances.StopResult.FOREIGN
    assert process.calls == [("open", 4242), ("wait", 0), "identity", "close"]


@pytest.mark.parametrize("ready, outcome", [(True, "terminated"), (False, "still_running")])
def test_cleanup_checks_and_stops_through_the_same_handle(slot_dir, ready, outcome):
    process = FakeHandle(slot_dir, ready=ready)
    assert instances.stop_slot_result(0, open_process=process.open, timeout_s=2) == outcome
    assert process.calls == [("open", 4242), ("wait", 0), "identity", "terminate", ("wait", 2), "close"]


def test_cleanup_refuses_relaunch_if_discovery_changes(slot_dir, monkeypatch):
    process = FakeHandle(slot_dir)
    original_identity = process.identity

    def replace_discovery():
        identity = original_identity()
        process.file.write_text(json.dumps({"pid": 9000, "instance": 0}), encoding="utf-8")
        return identity

    monkeypatch.setattr(process, "identity", replace_discovery)
    assert instances.stop_slot_result(0, open_process=process.open) == instances.StopResult.STILL_RUNNING
    assert "terminate" not in process.calls and process.calls[-1] == "close"


def test_access_denied_does_not_report_a_closed_slot(slot_dir):
    def denied(_):
        raise PermissionError("query denied")

    assert instances.stop_slot_result(0, open_process=denied) == instances.StopResult.DENIED


@pytest.mark.skipif(os.name != "nt", reason="Windows process API")
def test_real_identity_of_this_process():
    exe, created = instances._process_identity(os.getpid())
    assert exe.lower().endswith("python.exe")
    assert created <= time.time()
