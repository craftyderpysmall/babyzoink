import json
import sys
from math import exp
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/site"))

from gddl import cache_update
from rating import Anchor, Section, posterior, summarize


def test_recovers_known_skills_from_censored_sections_and_orders_generations():
    rng = np.random.default_rng(8105)
    theta = {("wave", 1): 4.25, ("wave", 2): 5.35}
    slope = 0.55
    levels = {f"online:{i}": Anchor(i, f"GDDL {i}", True) for i in (1, 3, 5, 7)}
    rows = []
    for (mode, generation), skill in theta.items():
        for level, anchor in levels.items():
            for index, offset in enumerate((-0.45, -0.15, 0.15, 0.45)):
                for seconds in rng.exponential(1 / exp(-skill + slope * anchor.score + offset), 260):
                    rows.append(Section(
                        mode, generation, level, index, 1.0, False, False, "zero", 1,
                        max(1, round(240 * min(seconds, 10))), seconds < 10, True,
                    ))
    fits, fitted_slope = posterior(rows, levels)
    for key, truth in theta.items():
        fit = fits[key]
        assert fit["theta_interval"][0] <= truth <= fit["theta_interval"][1]
    assert fitted_slope == pytest.approx(slope, abs=0.15)
    view = summarize(rows, levels)["zero_shot"]["trend"]
    assert view[0]["calibration"] == view[1]["calibration"] == "gddl"
    assert view[1]["rating"] > view[0]["rating"]
    assert sum(row["entries"] for row in view) == len(rows)


def test_practice_and_unverified_evidence_remain_separate():
    data = {
        "mode": "cube", "generation": 1, "level": "drill:one/train-1", "section": 0, "speed": 1,
        "mini": False, "dual": False, "start": "zero", "attempt": 1, "ticks_in_section": 6000,
        "died": False, "zero_shot": True,
    }
    first = Section.from_row(data)
    checkpoint = Section.from_row({**data, "start": "checkpoint", "attempt": 2, "zero_shot": False, "cleared": True})
    fallback = Section.from_row({**data, "attempt": 3, "zero_shot": False, "practice": True})
    reports = summarize([first, checkpoint, fallback], {first.level: Anchor(0, "Drill")})
    assert reports["zero_shot"]["trend"][0]["rating"] is None
    assert reports["full"]["trend"][0]["seconds"] == 25
    assert reports["all"]["trend"][0]["checkpoint_entries"] == 1
    assert reports["all"]["trend"][0]["seconds"] == 75
    assert reports["full"]["trend"][0]["levels"][0]["mean_attempts_to_first_section_clear"] is None
    assert reports["all"]["trend"][0]["levels"][0]["mean_attempts_to_first_section_clear"] == 2
    with pytest.raises(ValueError, match="first attempt"):
        Section.from_row({**data, "start": "checkpoint"})


def test_gddl_public_response_is_parsed_without_overwriting_cached_anchor(tmp_path, monkeypatch):
    monkeypatch.setattr("gddl.sleep", lambda _: None)
    path = tmp_path / "cache.json"
    seen = []

    def fetch(route):
        seen.append(route)
        if route == "/version":
            return "3.5.9"
        return json.dumps({"ID": 123, "Rating": 3.125, "RatingCount": 14, "Meta": {"Name": "Test level"}})

    cache, errors = cache_update(path, [123], fetch=fetch)
    assert not errors
    assert cache["levels"]["123"]["rating"] == 3.125
    assert cache["levels"]["123"]["fetched_at"] and cache["api_version"] == "3.5.9"
    assert seen == ["/version", "/levels/123"]
    seen.clear()
    assert cache_update(path, [123], fetch=fetch)[0]["levels"] == cache["levels"]
    assert seen == ["/version"]
