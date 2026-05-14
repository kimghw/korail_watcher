from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict


class Notifier(ABC):
    @abstractmethod
    def notify(self, message: str, **kwargs: Any) -> None:
        raise NotImplementedError

    def format_availability(self, summary: Dict[str, Any]) -> str:
        origin = summary.get("origin")
        dest = summary.get("dest")
        depart_time = summary.get("depart_time")
        status = summary.get("status", "UNKNOWN")
        seat_class = summary.get("seat_class", "")
        return f"[SRT] {origin}→{dest} {depart_time} [{seat_class}] {status}"

    def notify_summary(self, summary: Dict[str, Any]) -> None:
        self.notify(self.format_availability(summary))


__all__ = ["Notifier"]
