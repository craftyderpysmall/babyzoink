import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from gdbot.sections import SectionMap, SectionRecorder, TelemetryWriter, attempt_meta


def P(x, mode="cube", speed=1.0, mini=False, dual=False):
    p = {"x": x, "mode": mode, "speed": speed, "mini": mini}
    return [p, dict(p)] if dual else [p]


def run(rec, states, terminal, start="zero", attempt=1):
    rec.begin(attempt_meta(level="drill:t/x", attempt=attempt, start=start), states[0][0], states[0][1])
    for tick, players in states[1:-1]:
        rec.observe(tick, players)
    return rec.end(terminal, states[-1][0], states[-1][1])


def test_sections_split_on_mode_speed_mini_and_dual_and_end_states():
    m = SectionMap()
    rows = run(SectionRecorder(m), [
        (0, P(0)), (100, P(130)), (104, P(136, "ship")), (300, P(400, "ship")), (304, P(406, "ship", 2.0)),
        (400, P(600, "ship", 2.0, mini=True)), (500, P(800, "ship", 2.0, mini=True, dual=True)),
        (520, P(830, "ship", 2.0, mini=True, dual=True))], "death")
    assert [r["section"] for r in rows] == [0, 136, 406, 600, 800]
    assert [r["mode"] for r in rows] == ["cube", "ship", "ship", "ship", "ship"]
    assert [r["cleared"] for r in rows] == [True] * 4 + [False]
    assert rows[-1]["died"] and rows[-1]["dual"] and rows[-1]["ticks_in_section"] == 20
    assert rows[0]["ticks_in_section"] == 104 and rows[0]["zero_shot"] is False


def test_completion_clears_and_timeout_censors():
    m = SectionMap()
    done = run(SectionRecorder(m), [(0, P(0)), (50, P(70)), (60, P(80))], "complete")
    assert done[-1]["cleared"] and not done[-1]["died"]
    cut = run(SectionRecorder(m), [(0, P(0)), (50, P(70)), (60, P(80))], None)
    assert not cut[-1]["cleared"] and not cut[-1]["died"]


def test_ids_are_stable_across_attempts_and_checkpoint_starts():
    m = SectionMap()
    first = run(SectionRecorder(m), [(0, P(0)), (200, P(262, "wave")), (400, P(500, "wave")), (410, P(510, "wave"))], "death")
    again = run(SectionRecorder(m), [(0, P(0)), (196, P(255, "wave")), (220, P(290, "wave"))], "death", attempt=2)
    assert first[1]["section"] == again[1]["section"] == 262
    from_cp = run(SectionRecorder(m), [(0, P(480, "wave")), (40, P(530, "wave"))], "death", start="checkpoint")
    assert from_cp[0]["section"] == 262 and from_cp[0]["start"] == "checkpoint"


def test_meta_rules():
    with pytest.raises(ValueError):
        attempt_meta(level="x", attempt=2, start="zero", zero_shot=True)
    with pytest.raises(ValueError):
        attempt_meta(level="x", attempt=1, start="checkpoint", zero_shot=True)


def test_writer_appends_jsonl_and_persists_maps(tmp_path):
    w = TelemetryWriter("unit", root=tmp_path)
    rec = w.recorder("drill:t/x")
    w.write(run(rec, [(0, P(0)), (100, P(130, "ball")), (120, P(160, "ball"))], "death"))
    lines = [json.loads(l) for l in (tmp_path / "unit.jsonl").read_text().splitlines()]
    assert [l["section"] for l in lines] == [0, 130] and all(l["run"] == "unit" for l in lines)
    assert json.loads((tmp_path / "section_maps.json").read_text()) == {"drill:t/x": [130.0]}
    assert TelemetryWriter("unit2", root=tmp_path).maps.get("drill:t/x").boundaries == [130.0]


def test_rows_load_in_the_site_rating_model(tmp_path):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "site"))
    from rating import Section
    w = TelemetryWriter("unit", root=tmp_path)
    rec = w.recorder("drill:t/x")
    rec.begin(attempt_meta(level="drill:t/x", attempt=1, start="zero", generation=2, zero_shot=True), 0, P(0))
    rec.observe(100, P(130, "wave"))
    w.write(rec.end("death", 150, P(190, "wave")))
    for line in (tmp_path / "unit.jsonl").read_text().splitlines():
        Section.from_row(json.loads(line))


def test_parallel_writers_keep_disjoint_boundaries_and_agree_on_shared_transition(tmp_path):
    barrier = Barrier(2)

    def write(run_id, position, later):
        writer = TelemetryWriter(run_id, root=tmp_path)
        recorder = writer.recorder("drill:t/x")
        barrier.wait(timeout=5)
        rows = run(recorder, [(0, P(0)), (100, P(position, "wave")),
                              (200, P(later, "ship")), (220, P(later + 10, "ship"))], "death")
        writer.write(rows)
        return rows[1]["section"], rows[2]["section"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(write, "a", 130, 450)
        b = pool.submit(write, "b", 140, 650)
        shared_a, later_a = a.result()
        shared_b, later_b = b.result()

    assert shared_a == shared_b and shared_a in (130, 140)
    assert (later_a, later_b) == (450, 650)
    assert TelemetryWriter("observer", root=tmp_path).maps.get("drill:t/x").boundaries == [shared_a, 450, 650]
