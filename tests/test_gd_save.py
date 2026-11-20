import base64
import gzip

import pytest

from tools import gd_save


@pytest.fixture
def bot_save(tmp_path, monkeypatch):
    monkeypatch.setattr(gd_save, "BOT", tmp_path)
    monkeypatch.setattr(gd_save, "owned_pid", lambda _: None)
    p = gd_save.path(0)
    p.parent.mkdir()
    encoded = base64.urlsafe_b64encode(gzip.compress(b"<dict></dict>"))
    p.write_bytes(bytes(byte ^ 11 for byte in encoded))
    return p


def test_save_keeps_backup_and_refuses_active_slot(bot_save, monkeypatch):
    monkeypatch.setattr(gd_save, "owned_pid", lambda _: 123)
    with pytest.raises(RuntimeError, match="close the bot game"):
        gd_save.save(0, "<dict>new</dict>")
    backup = bot_save.with_suffix(".dat.bak")
    assert not backup.exists()

    monkeypatch.setattr(gd_save, "owned_pid", lambda _: None)
    gd_save.save(0, "<dict>new</dict>")
    assert gd_save.load(backup) == "<dict></dict>"
    assert gd_save.load(bot_save) == "<dict>new</dict>"


def test_failed_replacement_keeps_the_original(bot_save, monkeypatch):
    original_replace = gd_save.os.replace

    def fail_primary(source, target):
        if target == bot_save:
            raise PermissionError("save unavailable")
        original_replace(source, target)

    monkeypatch.setattr(gd_save.os, "replace", fail_primary)
    with pytest.raises(PermissionError, match="save unavailable"):
        gd_save.save(0, "<dict>new</dict>")
    assert gd_save.load(bot_save) == "<dict></dict>"
    assert not list(bot_save.parent.glob("*.tmp"))
