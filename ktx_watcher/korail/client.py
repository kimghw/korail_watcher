"""KorailSPAClient — CDP-only.

이 클래스는 ``playwright.chromium.connect_over_cdp(cdp_url)`` 만 한다.
자체 launch 경로는 없다.

부가 책임:
  - 매크로 안내 팝업(window.open) 자동 dismiss (page.on('popup'))
  - 일반 광고/공지 팝업 자동 close
  - 사람-유사 click/pause/mouse 헬퍼
"""

from __future__ import annotations

import logging
import os
import random
import time
from contextlib import AbstractContextManager
from typing import Optional

# NOTE: chrome_launcher import 가 socket.getaddrinfo 를 IPv4-only 로 patch 한다.
# playwright import 보다 *먼저* 해야 효과 있음.
from .. import chrome_launcher as _cl  # noqa: F401  (side-effect import)

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    TimeoutError as PWTimeoutError,
    sync_playwright,
)

from . import selectors as S

LOGGER = logging.getLogger("ktx_watcher_spa.korail.client")

# KTXA_HUMANIZE 는 .env.ktx 에서도 읽어야 함 — import 시점 평가라 env 파일 선로드 필요
from ..config import _load_env_files as _hload

_hload()
HUMANIZE = os.getenv("KTXA_HUMANIZE", "true").lower() not in ("false", "0", "no")


# ─────────────────── humanization helpers ───────────────────

def human_pause(min_s: float = 0.5, max_s: float = 1.2) -> None:
    if HUMANIZE:
        # 사용자 지시(2026-05-14): 0.5s 최소 + 랜덤 텀
        lo = max(min_s, 0.5)
        hi = max(max_s, lo + 0.5)
        time.sleep(random.uniform(lo, hi))


def human_mouse(page: Page, moves: int = 3, viewport=(1440, 900)) -> None:
    if not HUMANIZE:
        return
    w, h = viewport
    for _ in range(moves):
        try:
            page.mouse.move(
                random.randint(80, w - 80),
                random.randint(80, h - 80),
                steps=random.randint(8, 16),
            )
            time.sleep(random.uniform(0.08, 0.22))
        except Exception:
            return


def human_click(loc, hover_first: bool = True) -> None:
    """hover → pause → click → pause. bot 검사 통과 확률을 높이는 패턴."""
    if HUMANIZE and hover_first:
        try:
            loc.hover()
            time.sleep(random.uniform(0.35, 0.85))
        except Exception:
            pass
    loc.click()
    if HUMANIZE:
        time.sleep(0.5 + random.uniform(0.0, 1.0))


def human_type(loc, text: str, min_delay: int = 80, max_delay: int = 170) -> None:
    """한 글자씩 typing delay 줘서 입력. fill() 보다 자연스러움."""
    if not HUMANIZE:
        loc.fill(text)
        return
    loc.click()
    time.sleep(random.uniform(0.2, 0.5))
    loc.press_sequentially(text, delay=random.randint(min_delay, max_delay))
    time.sleep(random.uniform(0.25, 0.5))


# ─────────────────── popup guard ───────────────────

def _is_macro_notice_popup(popup: Page) -> bool:
    """popup body 에 -8002/-8003 등 매크로 키워드가 있으면 True."""
    try:
        popup.wait_for_load_state("domcontentloaded", timeout=3000)
        body_txt = popup.locator("body").inner_text(timeout=2000)
    except Exception:
        return False
    return any(kw in body_txt for kw in S.MACRO_NOTICE_KEYWORDS)


def _attach_popup_guard(page: Page) -> None:
    """광고/공지 팝업은 자동 close, 매크로 안내 팝업은 '확인' 클릭."""
    if getattr(page, "_popup_guard_attached", False):
        return

    def _on_popup(popup: Page) -> None:
        popup_url = popup.url or "about:blank"

        # popup 본문 확인 (load 대기)
        body_txt = ""
        try:
            popup.wait_for_load_state("domcontentloaded", timeout=3000)
            body_txt = popup.locator("body").inner_text(timeout=2000)
        except Exception:
            pass

        is_macro = any(kw in body_txt for kw in S.MACRO_NOTICE_KEYWORDS)
        # korail.com popup 이고 '확인' 버튼이 있는 안내성 모달이면 모두 dismiss
        # (예: 이용안내, 본인인증 안내, 약관 등). 광고/외부 URL 만 close.
        is_korail_info = ("korail" in popup_url) or any(
            kw in body_txt for kw in ("안내", "이용안내", "확인하시고", "선택하신", "예매")
        )

        def _click_confirm() -> bool:
            try:
                time.sleep(random.uniform(0.5, 1.0))
                btn = popup.locator(S.MODAL_CONFIRM_BUTTON).first
                if btn.count() > 0:
                    btn.click(timeout=3000)
                    return True
            except Exception as e:
                LOGGER.debug("popup confirm click 실패: %s", e)
            return False

        if is_macro:
            LOGGER.info("매크로 안내 popup → '확인' 클릭: %s", popup_url)
            if not _click_confirm():
                try:
                    popup.close()
                except Exception:
                    pass
            return

        if is_korail_info:
            LOGGER.info("정보 안내 popup → '확인' 클릭: %s body=%r", popup_url, body_txt[:80])
            if _click_confirm():
                return
            # 확인 클릭 실패 → close
        LOGGER.info("일반/광고 popup 자동 닫기: %s", popup_url)
        try:
            if not popup.is_closed():
                popup.close()
        except Exception:
            pass

    page.on("popup", _on_popup)
    page._popup_guard_attached = True  # type: ignore[attr-defined]


# ─────────────────── client ───────────────────

class KorailSPAClient(AbstractContextManager["KorailSPAClient"]):
    """CDP-only Korail driver.

    Args:
        cdp_url: ``http://localhost:9222`` 등. ChromeLauncher 가 만든 URL.
    """

    def __init__(self, cdp_url: str) -> None:
        if not cdp_url:
            raise ValueError("cdp_url is required (CDP-only variant)")
        self.cdp_url = cdp_url
        self._pw: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None

    def __enter__(self) -> "KorailSPAClient":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.stop()

    def start(self) -> None:
        self._pw = sync_playwright().start()
        ws_url = self._resolve_ws_url()
        LOGGER.info("CDP 연결: %s (via ws=%s)", self.cdp_url, ws_url)
        self._browser = self._pw.chromium.connect_over_cdp(ws_url or self.cdp_url)
        contexts = self._browser.contexts
        if contexts:
            self._context = contexts[0]
        else:
            self._context = self._browser.new_context()
        LOGGER.info(
            "CDP 연결 OK (contexts=%d pages=%d)",
            len(self._browser.contexts),
            len(self._context.pages),
        )
        # context-level popup guard 부착 — 어디서 popup 이 생기든 자동 확인 클릭
        attach_context_popup_guard(self._context)

    def _resolve_ws_url(self) -> Optional[str]:
        """Chrome 의 /json/version 에서 webSocketDebuggerUrl 을 직접 받는다."""
        import json
        import urllib.request
        try:
            # NOTE: Chrome 은 Host=127.0.0.1 거부 → URL 호스트는 'localhost' 로
            base = self.cdp_url.rstrip("/")
            if base.startswith("http://127.0.0.1"):
                base = base.replace("http://127.0.0.1", "http://localhost")
            with urllib.request.urlopen(f"{base}/json/version", timeout=5.0) as resp:
                data = json.loads(resp.read())
            ws = data.get("webSocketDebuggerUrl")
            if ws:
                # ws 도 호스트 표기 정리 (Chrome 이 ::1 listen 못할 수 있음 → 127.0.0.1)
                ws = ws.replace("ws://localhost:", "ws://127.0.0.1:")
                return ws
        except Exception as e:
            LOGGER.warning("webSocketDebuggerUrl 해석 실패, cdp_url 그대로 사용: %s", e)
        return None

    def stop(self) -> None:
        # CDP 모드에선 context/browser 를 close 하지 않는다 (사용자 Chrome 그대로 유지).
        try:
            if self._browser:
                # disconnect 만 (close 는 사용자 Chrome 까지 죽임)
                pass
        finally:
            self._browser = None
            self._context = None
        if self._pw:
            self._pw.stop()
            self._pw = None

    @property
    def context(self) -> BrowserContext:
        if not self._context:
            raise RuntimeError("Client not started")
        return self._context

    def main_page(self) -> Page:
        """사용할 메인 page. 없으면 새로 만든다. popup guard 자동 부착."""
        ctx = self.context
        page: Optional[Page] = None
        # 가장 적합한 page = korail.com 또는 about:blank
        for p in ctx.pages:
            try:
                url = p.url or ""
            except Exception:
                continue
            if "korail.com" in url or url.startswith("about:") or url == "":
                page = p
                break
        if page is None:
            page = ctx.new_page()
        _attach_popup_guard(page)
        return page


# ─────────────────── safe navigation helpers ───────────────────

def safe_goto(page: Page, url: str, timeout_ms: int = 30_000) -> None:
    try:
        page.goto(url, wait_until="load", timeout=timeout_ms)
    except PWTimeoutError as e:
        from . import SiteLayoutChanged
        raise SiteLayoutChanged(f"goto timeout: {url}") from e


def dismiss_macro_notice(page: Page) -> bool:
    """메인 페이지의 -8002/-8003 ReactModal '확인' 클릭 dismiss."""
    try:
        body_txt = page.locator("body").inner_text(timeout=1500)
    except Exception:
        return False
    if not any(kw in body_txt for kw in S.MACRO_NOTICE_KEYWORDS):
        return False
    # visible 한 '확인' 버튼 클릭
    btns = page.locator(S.MODAL_CONFIRM_BUTTON)
    n = btns.count()
    for i in range(n):
        b = btns.nth(i)
        try:
            if b.is_visible():
                b.click(timeout=2000)
                LOGGER.info("매크로 안내 모달 '확인' 클릭 dismiss")
                time.sleep(random.uniform(0.8, 1.4))
                return True
        except Exception:
            continue
    return False


def dismiss_notice_modal(page: Page) -> bool:
    try:
        body_txt = page.locator("body").inner_text(timeout=1500)
    except Exception:
        return False
    if not any(kw in body_txt for kw in S.NOTICE_MODAL_KEYWORDS):
        return False
    # 1) "N일간 그만보기" 체크박스 있으면 먼저 체크 — 닫으면 cookie 로 24시간 안 뜸.
    try:
        chks = page.locator(S.NOTICE_MODAL_HIDE_TODAY_CHECKBOX)
        for i in range(chks.count()):
            c = chks.nth(i)
            try:
                if c.is_visible():
                    c.click(timeout=1500)
                    LOGGER.info("공지 모달 '그만보기' 체크")
                    time.sleep(0.2)
                    break
            except Exception:
                continue
    except Exception:
        pass
    # 2) 닫기 버튼 클릭
    btns = page.locator(S.NOTICE_MODAL_DISMISS_BUTTON)
    try:
        n = btns.count()
    except Exception:
        return False
    for i in range(n):
        b = btns.nth(i)
        try:
            if b.is_visible():
                b.click(timeout=2000)
                LOGGER.info("공지 모달 '창닫기' 클릭 dismiss")
                time.sleep(random.uniform(0.6, 1.0))
                return True
        except Exception:
            continue
    return False


def dismiss_any_modal(page: Page) -> bool:
    """일반적인 안내 모달의 visible '확인' 버튼 클릭. 매크로 키워드 검사 없음."""
    btns = page.locator(S.MODAL_CONFIRM_BUTTON)
    n = btns.count()
    for i in range(n):
        b = btns.nth(i)
        try:
            if b.is_visible():
                b.click(timeout=2000)
                LOGGER.info("안내 모달 '확인' 클릭 dismiss")
                time.sleep(random.uniform(0.6, 1.2))
                return True
        except Exception:
            continue
    return False


_INFO_KEYWORDS = S.MACRO_NOTICE_KEYWORDS + (
    "안내",
    "이용안내",
    "확인하시고",
    "선택하신",
    "예매",
    "본인인증",
    "약관",
)


def dismiss_all_popups(context) -> int:
    """**공통 popup 핸들러** — 현재 떠 있는 모든 page/popup 의 안내 모달 '확인' 클릭.

    page-level on('popup') 만 의지하면 timing race condition 으로 놓치는 경우가
    있어 매 action 후 명시적으로 호출. context.pages 를 snapshot 해서 순회.
    """
    count = 0
    try:
        pages = list(context.pages)
    except Exception:
        return 0
    for pg in pages:
        try:
            if pg.is_closed():
                continue
        except Exception:
            continue

        # popup body 텍스트 확인
        try:
            body = pg.locator("body").inner_text(timeout=1000)
        except Exception:
            continue

        is_info = any(kw in body for kw in _INFO_KEYWORDS)
        if not is_info:
            continue

        # dismiss 전에 모달 자체 텍스트 확보 — 예매 불발 원인 진단용 (body 는 페이지 머리글이라 무의미)
        modal_txt = ""
        for _sel in (".ReactModal__Content", "[role=dialog]"):
            try:
                _m = pg.locator(_sel).first
                if _m.count() > 0 and _m.is_visible():
                    modal_txt = _m.inner_text(timeout=500)
                    break
            except Exception:
                continue

        # in-page ReactModal 인지 popup window 인지 무관 — visible 한 '확인' 버튼만 찾아 클릭
        try:
            btns = pg.locator(S.MODAL_CONFIRM_BUTTON)
            n = btns.count()
        except Exception:
            continue
        for i in range(n):
            b = btns.nth(i)
            try:
                if b.is_visible():
                    b.click(timeout=2000)
                    LOGGER.info(
                        "popup/모달 '확인' dismiss (url=%s, modal=%r)",
                        pg.url, (modal_txt or body)[:200],
                    )
                    count += 1
                    time.sleep(random.uniform(0.5, 0.9))
                    break
            except Exception:
                continue
    return count


def attach_context_popup_guard(context) -> None:
    """context.on('page') 로 모든 새 page (popup 포함) 자동 dismiss.

    page-level on('popup') 보다 광범위. 어디서 popup 이 생기든 잡음.
    """
    if getattr(context, "_popup_guard_attached", False):
        return

    def _on_page(new_page: Page) -> None:
        try:
            new_page.wait_for_load_state("domcontentloaded", timeout=3000)
        except Exception:
            pass
        try:
            body = new_page.locator("body").inner_text(timeout=2000)
        except Exception:
            body = ""
        if not any(kw in body for kw in _INFO_KEYWORDS):
            # 광고/외부 popup — close
            try:
                if "korail" not in (new_page.url or "") and not new_page.is_closed():
                    LOGGER.info("외부/광고 popup close: %s", new_page.url)
                    new_page.close()
            except Exception:
                pass
            return

        # 안내성 popup → '확인' 클릭
        LOGGER.info("새 popup 감지 (안내성) → 확인 클릭: %s body=%r", new_page.url, body[:60])
        try:
            time.sleep(random.uniform(0.5, 1.0))
            btn = new_page.locator(S.MODAL_CONFIRM_BUTTON).first
            if btn.count() > 0 and btn.is_visible():
                btn.click(timeout=3000)
                LOGGER.info("popup '확인' 클릭 완료")
        except Exception as e:
            LOGGER.debug("popup 확인 클릭 실패: %s", e)

    context.on("page", _on_page)
    context._popup_guard_attached = True  # type: ignore[attr-defined]
    LOGGER.info("context popup guard 부착 (context.on('page'))")


__all__ = [
    "KorailSPAClient",
    "_attach_popup_guard",
    "safe_goto",
    "dismiss_macro_notice",
    "human_pause",
    "human_mouse",
    "human_click",
    "human_type",
    "HUMANIZE",
]
