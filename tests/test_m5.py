import hashlib
import json
from collections import Counter
from pathlib import Path

import numpy as np

from gdbot.curriculum import demo_batches, demo_counts, save_demonstration
from gdbot.levels.drills import M5_NOTES, MODE_PORTALS, ORBS, PADS, build_m5_drill, iter_m5_drills, write_drills
from gdbot.levels.levelstring import LevelString


DRILLS = Path(__file__).resolve().parents[1] / "levels/drills/m5"


def test_m5_freezes_three_distinct_layouts_for_every_family(tmp_path):
    write_drills(tmp_path, tape_root=DRILLS / "tapes", m5=True)
    assert (tmp_path / "index.yaml").read_bytes() == (DRILLS / "index.yaml").read_bytes()
    counts = Counter()
    seen, objects = set(), set()
    hashes = [
        json.loads(line.split(": ", 1)[1])
        for line in (tmp_path / "index.yaml").read_text(encoding="utf-8").splitlines()
        if line.startswith("    sha256:")
    ]
    for drill, digest in zip(iter_m5_drills(), hashes, strict=True):
        counts[drill.family, drill.split] += 1
        path = Path(drill.family) / f"{drill.variant}.txt"
        payload = (tmp_path / path).read_bytes()
        assert (DRILLS / path).read_bytes() == payload
        assert hashlib.sha256(payload).hexdigest() == digest
        decoded = LevelString.decode(payload.decode("ascii"))
        assert decoded == build_m5_drill(drill.family, drill.split, drill.seed).level
        assert decoded.header["kA2"] == "0"
        assert digest not in seen
        seen.add(digest)
        objects.update(int(record["1"]) for record in decoded.objects)
    assert len(counts) == len(M5_NOTES) * 3 and set(counts.values()) == {1}
    assert {kind for mode, kind in MODE_PORTALS.items() if mode != "cube"} <= objects
    assert set(PADS.values()) | set(ORBS.values()) <= objects


def test_disk_demonstrations_read_all_rows_once_and_reproducibly(tmp_path):
    paths = [tmp_path / "a.npz", tmp_path / "b.npz"]
    save_demonstration(paths[0], [[1], [2], [3]], [0, 1, 1])
    save_demonstration(paths[1], [[4], [5]], [1, 0])
    assert demo_counts(paths).tolist() == [2, 3]

    def rows():
        output = []
        for observations, actions in demo_batches(paths, np.random.default_rng(5), 2):
            assert observations.dtype == np.float32 and len(actions) <= 2
            output.extend(zip(observations[:, 0].tolist(), actions.tolist()))
        return output

    assert rows() == rows()
    assert sorted(rows()) == [(1.0, 0), (2.0, 1), (3.0, 1), (4.0, 1), (5.0, 0)]
