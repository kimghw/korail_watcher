from __future__ import annotations

import logging

from rich.console import Console

from .base import Notifier


class DesktopNotifier(Notifier):
    def __init__(self) -> None:
        self._console = Console()
        self._logger = logging.getLogger("ktx_watcher_spa.notifier.desktop")

    def notify(self, message: str, **kwargs) -> None:
        try:
            self._console.print(f":bell: {message}")
        except Exception:  # pragma: no cover
            self._logger.warning("Desktop notifier failed", exc_info=True)


__all__ = ["DesktopNotifier"]
