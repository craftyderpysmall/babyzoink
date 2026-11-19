import base64
import gzip
import json

import pytest

from gdbot.levels import online
from gdbot.levels.levelstring import LevelString


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
