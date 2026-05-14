from datetime import time

from srt_watcher import utils


def test_is_candidate_exact_match():
    preferred = [time(8, 0)]
    assert utils.is_candidate(time(8, 0), preferred, tolerance_min=0, time_window=None)
    assert not utils.is_candidate(time(8, 5), preferred, tolerance_min=0, time_window=None)


def test_is_candidate_with_tolerance():
    preferred = [time(8, 0)]
    assert utils.is_candidate(time(8, 4), preferred, tolerance_min=5, time_window=None)
    assert not utils.is_candidate(time(8, 6), preferred, tolerance_min=5, time_window=None)


def test_is_candidate_with_time_window():
    preferred = [time(8, 0)]
    window = (time(7, 50), time(8, 10))
    assert utils.is_candidate(time(7, 55), preferred, tolerance_min=0, time_window=window)
    assert not utils.is_candidate(time(8, 30), preferred, tolerance_min=0, time_window=window)
