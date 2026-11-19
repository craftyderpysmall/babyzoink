from gdbot.attempts import from_result, read, row, summarize, write


def test_from_result_counts_normal_and_practice_and_first_clear():
    res = {"attempts": [{"terminal": "death", "peak_progress": 0.3}, {"terminal": "complete", "peak_progress": 1.0}],
           "practice": [{"resets": 4}, {"resets": 3, "section_completed_level": True}]}
    r = from_result("run1", "official:1", res, name="Stereo Madness", t=1.0)
    assert (r["normal_attempts"], r["practice_attempts"], r["normal_clears"]) == (2, 7, 1)
    assert r["first_clear_attempt"] == 2 and r["practice_clear"] and r["best_progress"] == 1.0


def test_summarize_totals_across_runs_and_orders_groups(tmp_path):
    write("a", [row("a", "drill:x/y", normal_attempts=3, t=1), row("a", "official:2", normal_attempts=1, t=1)], tmp_path)
    write("b", [row("b", "official:2", normal_attempts=2, practice_attempts=50, normal_clears=1,
                    best_progress=1.0, first_clear_attempt=2, t=2),
                row("b", "online:5", practice_attempts=9, t=2)], tmp_path)
    write("a", [row("a", "drill:x/y", normal_attempts=3, t=1), row("a", "official:2", normal_attempts=1, t=1)], tmp_path)  # rewrite, not append
    s = summarize(read(tmp_path))
    assert [x["level"] for x in s] == ["official:2", "online:5", "drill:x/y"]
    off = s[0]
    assert (off["normal_attempts"], off["practice_attempts"], off["normal_clears"], off["runs"]) == (3, 50, 1, 2)
    assert off["first_cleared_by"] == {"run": "b", "attempt": 2, "t": 2}
