"""#34: slot cleanup only ever touches the slot's own bot GD (exe path + creation time verified)."""
import json
import os
import time

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


def test_stop_slot_never_kills_unowned(slot_dir, monkeypatch):
    calls = []
    monkeypatch.setattr(instances.subprocess, "run", lambda *a, **k: calls.append(a))
    written = (slot_dir / "bridge.json").stat().st_mtime
    foreign = lambda pid: (r"C:\Windows\notepad.exe", written - 5)
    assert instances.stop_slot(0, identity=foreign) is True
    assert calls == []


@pytest.mark.skipif(os.name != "nt", reason="Windows process API")
def test_real_identity_of_this_process():
    exe, created = instances._process_identity(os.getpid())
    assert exe.lower().endswith("python.exe")
    assert created <= time.time()
