import hashlib
import json
from pathlib import Path

import pytest

from gdbot.levels.drills import NOTES, build_drill, iter_drills, write_drills
from gdbot.levels.levelstring import CLASSIC_CUBE, LevelString
from gdbot.replay import Tape

FIXTURES = Path(__file__).resolve().parents[1] / "levels" / "drills"


def test_builder_round_trip_preserves_object_properties_and_header():
    level = LevelString()
    level.add(8, 30.25, 15, rotation=180, flip_x=True, flip_y=True, scale=1.25, properties={57: "1.3"})
    assert level.inner().endswith(";1,8,2,30.25,3,15,6,180,4,1,5,1,32,1.25,57,1.3;")
    assert level.header == CLASSIC_CUBE
    assert level.encode().startswith("H4sI")
    assert LevelString.parse(level.inner()) == LevelString.decode(level.encode()) == level


@pytest.mark.parametrize("record", ("1,8,2,0", "1,8,2,0,3,15,1,9", "1,8,2,0,3"))
def test_builder_rejects_incomplete_or_ambiguous_object_records(record):
    with pytest.raises(ValueError):
        LevelString.parse(f"kA2,0;{record};")


@pytest.mark.parametrize("family", NOTES)
def test_drill_seed_and_split_are_reproducible(family):
    train = build_drill(family, "train", 1872)
    heldout = build_drill(family, "heldout", 1872)
    assert train.level.encode() == build_drill(family, "train", 1872).level.encode()
    assert train.level.inner() != build_drill(family, "train", 1873).level.inner()
    assert train.level.inner() != heldout.level.inner()


def _index(path: Path):
    # The generator uses only JSON scalar values in a YAML list of mappings.
    for line in path.read_text(encoding="utf-8").splitlines()[2:]:
        if line.startswith("  - "):
            entry = {}
            yield entry
        key, value = line[4:].split(": ", 1)
        entry[key] = json.loads(value)


def test_manifest_hashes_match_regenerated_payloads_and_disjoint_splits(tmp_path):
    write_drills(tmp_path, tape_root=FIXTURES / "tapes")
    assert (tmp_path / "index.yaml").read_bytes() == (FIXTURES / "index.yaml").read_bytes()
    entries = list(_index(FIXTURES / "index.yaml"))
    drills = list(iter_drills())
    assert len(entries) == len(drills) == 2 * len(NOTES)
    layouts = {"train": set(), "heldout": set()}
    for entry, drill in zip(entries, drills, strict=True):
        payload = (FIXTURES / entry["path"]).read_bytes()
        assert payload == (tmp_path / entry["path"]).read_bytes()
        assert hashlib.sha256(payload).hexdigest() == entry["sha256"]
        assert LevelString.decode(payload.decode("ascii")) == drill.level
        assert entry["progress_ok_dx"]
        assert entry["training_ready"] is bool(entry["tape"])
        if entry["tape"]:
            tape = Tape.load(FIXTURES / entry["tape"])
            assert tape.terminal == "complete" and tape.seed == drill.seed
            assert tape.settings["drill_sha256"] == entry["sha256"]
        assert 10 <= entry["nominal_seconds_1x"] <= 25
        assert entry["needs_trigger_support"] == (drill.family == "moving-geometry")
        layouts[entry["split"]].add(drill.level.inner())
    assert len(layouts["train"]) == len(layouts["heldout"]) == len(NOTES)
    assert layouts["train"].isdisjoint(layouts["heldout"])
