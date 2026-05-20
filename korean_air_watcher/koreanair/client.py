"""KoreanAirSPAClient — CDP attach only (ktx_watcher.korail.client 패턴)."""

from __future__ import annotations

import logging
import os
import random
import time
from contextlib import AbstractContextManager
from typing import Optional

# socket.getaddrinfo IPv4 patch (ktx_watcher 쪽과 동일 사이드이펙트)
from ktx_watcher import chrome_launcher as _cl  # noqa: F401

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    TimeoutError as PWTimeoutError,
    sync_playwright,
)

LOGGER = logging.getLogger("korean_air_watcher.koreanair.client")

HUMANIZE = os.getenv("KOREAN_AIR_HUMANIZE", "true").lower() not in ("false", "0", "no")


def human_pause(min_s: float = 0.5, max_s: float = 1.2) -> None:
    if HUMANIZE:
        lo = max(min_s, 0.5)
        hi = max(max_s, lo + 0.5)
        time.sleep(random.uniform(lo, hi))


class KoreanAirSPAClient(AbstractContextManager):
    """KE 웹페이지에 CDP attach 한 뒤 page 핸들을 제공한다.

    - 자체 launch 안 함 — 외부에서 띄운 Chrome 의 CDP URL 에 connect_over_cdp.
    - 기존 context 의 첫 페이지를 재사용 (없으면 새로 연다).
    """

    BASE_URL = "https://www.koreanair.com"

    def __init__(self, cdp_url: str) -> None:
        self.cdp_url = cdp_url
        self._pw: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._ctx: Optional[BrowserContext] = None
        self._page: Optional[Page] = None

    def __enter__(self) -> "KoreanAirSPAClient":
        self._pw = sync_playwright().start()
        LOGGER.info("CDP connect: %s", self.cdp_url)
        self._browser = self._pw.chromium.connect_over_cdp(self.cdp_url)
        if not self._browser.contexts:
            self._ctx = self._browser.new_context()
        else:
            self._ctx = self._browser.contexts[0]
        if self._ctx.pages:
            self._page = self._ctx.pages[0]
        else:
            self._page = self._ctx.new_page()
        return self

    def __exit__(self, *exc) -> None:
        # CDP attach 만 했으므로 Chrome 자체는 닫지 않는다.
        try:
            if self._browser:
                self._browser.close()
        except Exception:
            pass
        try:
            if self._pw:
                self._pw.stop()
        except Exception:
            pass

    @property
    def page(self) -> Page:
        if not self._page:
            raise RuntimeError("client not entered")
        return self._page

    def goto(self, url: str, *, wait_until: str = "domcontentloaded", timeout: float = 30_000) -> None:
        LOGGER.debug("goto: %s", url)
        self.page.goto(url, wait_until=wait_until, timeout=timeout)
        human_pause()


__all__ = ["KoreanAirSPAClient", "human_pause"]
