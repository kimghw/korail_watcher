import random

from srt_watcher.scheduler import PollPolicy


def test_poll_policy_backoff_and_recovery():
    random.seed(0)
    policy = PollPolicy(base_min=3, base_max=5, backoff_cap=60, multiplier=2, jitter=0.0)

    interval_initial = policy.next_interval()
    assert 3 <= interval_initial <= 5

    policy.mark_fail()
    interval_fail = policy.next_interval()
    assert interval_fail >= 5

    policy.mark_ok()
    policy.mark_ok()
    interval_recovered = policy.next_interval()
    assert 3 <= interval_recovered <= 5


def test_poll_policy_jitter_bounds():
    random.seed(1)
    policy = PollPolicy(base_min=3, base_max=5, backoff_cap=10, multiplier=2, jitter=0.2)
    policy.mark_fail()
    value = policy.next_interval()
    assert value >= 3 * 0.5
    assert value <= 10
