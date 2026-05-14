from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass
class PollPolicy:
    base_min: float
    base_max: float
    backoff_cap: float
    multiplier: float
    jitter: float

    def __post_init__(self) -> None:
        if self.base_min <= 0 or self.base_max < self.base_min:
            raise ValueError("Invalid polling window")
        if self.backoff_cap <= 0:
            raise ValueError("backoff_cap must be > 0")
        if self.multiplier < 1.0:
            raise ValueError("multiplier must be >= 1")
        if not 0 <= self.jitter < 1:
            raise ValueError("jitter must be in [0,1)")
        self._failure_count = 0
        self._consecutive_success = 0
        self._current_max = self.base_max

    def mark_fail(self) -> None:
        self._failure_count += 1
        self._consecutive_success = 0
        scaled = self.base_max * (self.multiplier ** self._failure_count)
        self._current_max = min(self.backoff_cap, scaled)

    def mark_ok(self) -> None:
        if self._failure_count == 0:
            return
        self._consecutive_success += 1
        if self._consecutive_success >= 2:
            self._failure_count = 0
            self._consecutive_success = 0
            self._current_max = self.base_max

    def next_interval(self) -> float:
        if self._failure_count == 0:
            window_min = self.base_min
        else:
            scaled_min = self.base_min * (self.multiplier ** self._failure_count)
            window_min = min(self._current_max, max(self.base_min, scaled_min))
        base_interval = random.uniform(window_min, self._current_max)
        if self.jitter == 0:
            return base_interval
        delta = random.uniform(-self.jitter, self.jitter)
        jittered = base_interval * (1 + delta)
        return max(self.base_min * 0.5, min(self.backoff_cap, jittered))


__all__ = ["PollPolicy"]
