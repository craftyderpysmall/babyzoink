import base64
import gzip
import io
import json

import pytest

from gdbot.levels import levelstring, online
from gdbot.levels.levelstring import LevelString
from gdbot.protocol import BridgeClient, InProcessTransport


def _gz(inner):
    return base64.urlsafe_b64encode(gzip.compress(inner.encode())).decode()


INNER = "kS38,1_0_2_0;1,1,2,15,3,15;"


def test_parse_and_metadata():
    text = f"1:123:2:Test Level:4:{_gz(INNER)}:5:2:9:40:17::18:7:15:2:25:#abc#def"
    fields = online.parse_response(text)
    meta = online.metadata(fields)
    assert meta == {"id": 123, "name": "Test Level", "version": 2, "stars": 7, "demon": False,
                    "difficulty": "harder", "length": "medium", "platformer": False}
    demon = online.metadata({**fields, "17": "1", "43": "6"})
    assert demon["demon"] and demon["difficulty"] == "extreme_demon"


@pytest.mark.parametrize("reply", ["-1", "", "#x"])
def test_errors_are_reported(reply):
    with pytest.raises(LookupError):
        online.parse_response(reply)


def test_normalize_accepts_gzip_zlib_and_raw():
    import zlib
    for data in (_gz(INNER), base64.urlsafe_b64encode(zlib.compress(INNER.encode())).decode(), INNER):
        assert LevelString.decode(online.normalize_data(data)).objects


def test_download_uses_cache_without_network(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(online, "_post", lambda i, t: calls.append(i) or f"1:{i}:2:X:4:{_gz(INNER)}:9:10:18:2:15:1")
    first = online.download(55, cache=tmp_path)
    again = online.download(55, cache=tmp_path)
    assert calls == [55] and first == again == json.loads((tmp_path / "55.json").read_text())
    assert online.level_spec(first)["kind"] == "level_string"
    monkeypatch.setattr(online, "_post", lambda i, t: f"1:{i}:2:P:4:{_gz(INNER)}:15:5")
    with pytest.raises(ValueError):
        online.download(56, cache=tmp_path)


def test_size_limit_applies_before_bridge_transport(monkeypatch):
    monkeypatch.setattr(levelstring, "MAX_INNER_LEVEL", len(INNER) - 1)
    client = BridgeClient(InProcessTransport(lambda _: pytest.fail("unexpected transport call")))
    with pytest.raises(ValueError, match="decoded size limit"):
        client.load_level({"kind": "level_string", "name": "fixture", "data": _gz(INNER)})


def test_decompression_and_cache_reads_respect_independent_limits(monkeypatch):
    assert online.read_limited(io.BytesIO(b"journal"), limit=7) == b"journal"
    with pytest.raises(ValueError, match="byte limit"):
        online.read_limited(io.BytesIO(b"journal"), limit=6)
    monkeypatch.setattr(levelstring, "MAX_LEVEL_RECORDS", 1)
    with pytest.raises(ValueError, match="record limit"):
        online.normalize_data(_gz(INNER))
