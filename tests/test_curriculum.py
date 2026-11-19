from gdbot.curriculum import DeathHotspots, Decision, timing_candidates


def test_hotspots_use_frequency_and_expand_a_verified_end_window_backwards():
    trace = tuple(Decision(x, None, 0) for x in range(0, 1500, 5))
    hotspots = DeathHotspots()
    earlier = hotspots.record(570, trace)
    later = hotspots.record(1497, trace)
    assert earlier != later
    hotspots.record(1499, trace)
    bucket, decisions, window = hotspots.window(1750, earlier)
    assert bucket == later and decisions == trace
    assert window.finish_required and decisions[window.anchor].x == 1340
    hotspots.end_witnesses[bucket] += 1
    _, _, expanded = hotspots.window(1750, later)
    assert decisions[expanded.anchor].x == 1240
    assert expanded.target_x == window.target_x


def test_timing_search_is_bounded_and_can_insert_presses_in_an_empty_trace():
    no_press = (0,) * 45
    inserted = list(timing_candidates(no_press, 5))
    assert len(inserted) == len(set(inserted)) == 5
    assert all(len(candidate) == len(no_press) and sum(candidate) == 2 for candidate in inserted)
    one_press = (0,) * 30 + (1, 1) + (0,) * 11
    shifted = list(timing_candidates(one_press, 8))
    assert len(shifted) == len(set(shifted)) == 8
    assert tuple(one_press) not in shifted
    assert (0,) * 29 + (1, 1, 1) + (0,) * 11 in shifted
