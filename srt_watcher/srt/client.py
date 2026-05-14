from __future__ import annotations

import logging
import os
import platform
import shutil
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Optional

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, TimeoutError, sync_playwright

from .. import utils
from . import SiteLayoutChanged

LOGGER = logging.getLogger("srt_watcher.srt.client")

BASE_LAUNCH_ARGS = [
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--disable-background-timer-throttling",
    "--disable-renderer-backgrounding",
    "--disable-backgrounding-occluded-windows",
    "--disable-blink-features=AutomationControlled",
    "--exclude-switches=enable-automation",
    "--disable-infobars",
]


def _find_system_chromium() -> str | None:
    """ARM64 Linux에서 시스템 Chromium 경로를 반환. 없으면 None."""
    if platform.machine() not in ("aarch64", "arm64"):
        return None
    # 환경변수로 직접 지정 가능
    explicit = os.getenv("CHROMIUM_EXECUTABLE_PATH", "").strip()
    if explicit and os.path.isfile(explicit):
        return explicit
    for name in ("chromium", "chromium-browser"):
        path = shutil.which(name)
        if path:
            return path
    return None


def _parse_viewport_env() -> tuple[int, int]:
    raw = (os.getenv("SRT_VIEWPORT") or "").lower().strip()
    try:
        if "x" in raw:
            w, h = raw.split("x", 1)
            width, height = int(w), int(h)
            if width >= 800 and height >= 600:
                return width, height
    except Exception:
        pass
    return 1920, 1080


def _get_chrome_version(executable_path: str) -> str:
    """실행파일에서 Chrome 버전을 읽어 반환. 실패 시 최신 안정 버전으로 fallback."""
    fallback = "135.0.7049.84"
    try:
        import subprocess
        result = subprocess.run(
            [executable_path, "--version"],
            capture_output=True, text=True, timeout=5,
        )
        # "Google Chrome 135.0.7049.84" 또는 "Chromium 141.0.7390.37"
        output = (result.stdout or result.stderr or "").strip()
        import re
        match = re.search(r"(\d+\.\d+\.\d+\.\d+)", output)
        if match:
            version = match.group(1)
            LOGGER.debug("감지된 Chrome 버전: %s (from: %s)", version, output)
            return version
    except Exception as e:
        LOGGER.debug("Chrome 버전 감지 실패: %s → fallback %s 사용", e, fallback)
    return fallback


def _build_user_agent(version: str) -> str:
    major = version.split(".")[0]
    return (
        f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        f"AppleWebKit/537.36 (KHTML, like Gecko) "
        f"Chrome/{version} Safari/537.36"
    )



def _apply_stealth(context: BrowserContext) -> None:
    try:
        from playwright_stealth import Stealth
        Stealth(
            navigator_webdriver=True,
            navigator_languages=True,
            navigator_platform=True,
            navigator_plugins=True,
            chrome_runtime=True,
            navigator_languages_override=("ko-KR", "ko", "en-US", "en"),
            navigator_platform_override="Win32",
        ).apply_stealth_sync(context)
        LOGGER.debug("Stealth applied")
    except ImportError:
        LOGGER.warning("playwright-stealth 미설치 — stealth 비활성")
    except Exception as e:
        LOGGER.warning("Stealth 적용 실패: %s", e)


def _attach_popup_guard(page: Page) -> None:
    """페이지에 팝업 자동 닫기 핸들러를 부착한다.

    SRT 사이트가 예약/검색 시 광고·공지 팝업을 window.open 으로 띄우면
    Playwright 가 새 창에서 셀렉터를 찾으려 하여 실패하는 문제를 방지한다.
    """
    if getattr(page, "_popup_guard_attached", False):
        return

    def _on_popup(popup: Page) -> None:
        popup_url = ""
        try:
            popup.wait_for_load_state("commit", timeout=3000)
            popup_url = popup.url or ""
        except Exception:
            popup_url = popup.url or "about:blank"
        LOGGER.info("팝업 감지 → 자동 닫기: %s", popup_url)
        try:
            if not popup.is_closed():
                popup.close()
        except Exception as e:
            LOGGER.debug("팝업 닫기 실패: %s", e)

    page.on("popup", _on_popup)
    page._popup_guard_attached = True  # type: ignore[attr-defined]
    LOGGER.debug("팝업 가드 부착 완료")


class SRTClient(AbstractContextManager["SRTClient"]):
    """Playwright 기반 SRT 브라우저 클라이언트.

    SRT_CDP_URL 환경변수가 설정되어 있으면 로컬 Chrome에 CDP로 연결한다.
    Docker 내부에서 실행할 때 로컬 IP로 요청을 보내는 데 유용하다.

    로컬 Chrome 실행 방법 (Windows):
        chrome.exe --remote-debugging-port=9222 --remote-allow-origins=*
    docker-compose.yml:
        environment:
          - SRT_CDP_URL=http://host.docker.internal:9222
    """

    def __init__(self, headless: bool = True) -> None:
        self._headless = headless
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._cdp_mode: bool = False  # CDP 연결 모드 여부

    def __enter__(self) -> "SRTClient":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.stop()

    @property
    def context(self) -> BrowserContext:
        if not self._context:
            raise RuntimeError("Browser context is not initialized")
        return self._context

    def start(self) -> None:
        import asyncio

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running() or loop.is_closed():
                asyncio.set_event_loop(asyncio.new_event_loop())
        except RuntimeError:
            asyncio.set_event_loop(asyncio.new_event_loop())

        self._playwright = sync_playwright().start()

        cdp_url = os.getenv("SRT_CDP_URL", "").strip()
        if cdp_url:
            # ── CDP 모드: 로컬 Chrome에 원격 연결 ──────────────────────────
            LOGGER.info("CDP 모드: 로컬 Chrome에 연결 중 (%s)", cdp_url)
            try:
                self._browser = self._playwright.chromium.connect_over_cdp(cdp_url)
                # 기존 컨텍스트 재사용 (로그인 세션 유지)
                contexts = self._browser.contexts
                if contexts:
                    self._context = contexts[0]
                    LOGGER.info("CDP: 기존 컨텍스트 재사용 (탭 %d개)", len(self._context.pages))
                else:
                    self._context = self._browser.new_context()
                    LOGGER.info("CDP: 새 컨텍스트 생성")
                self._cdp_mode = True
            except Exception as e:
                LOGGER.error(
                    "CDP 연결 실패 (%s): %s\n"
                    "→ 로컬 Chrome이 --remote-debugging-port=9222 로 실행 중인지 확인하세요.\n"
                    "→ 일반 모드로 fallback합니다.", cdp_url, e
                )
                self._cdp_mode = False
                self._browser = None
                self._context = None

        if not self._cdp_mode:
            # ── 일반 모드: 내장 Chromium 실행 ──────────────────────────────
            effective_headless = self._headless
            if not effective_headless and not os.getenv("DISPLAY"):
                LOGGER.warning("No DISPLAY — headless=True 강제")
                effective_headless = True

            LOGGER.debug("일반 모드 시작 (headless=%s)", effective_headless)
            width, height = _parse_viewport_env()

            system_chromium = _find_system_chromium()
            if system_chromium:
                LOGGER.info("ARM64 감지 → 시스템 Chromium 사용: %s", system_chromium)

            self._browser = self._playwright.chromium.launch(
                headless=effective_headless,
                args=BASE_LAUNCH_ARGS + [f"--window-size={width},{height}"],
                executable_path=system_chromium,
            )

            # 실제 설치된 Chrome 버전을 읽어서 User-Agent에 반영
            chrome_exe = system_chromium or self._playwright.chromium.executable_path
            chrome_version = _get_chrome_version(chrome_exe)
            user_agent = _build_user_agent(chrome_version)
            LOGGER.info("Chrome 버전: %s → User-Agent 설정", chrome_version)

            self._context = self._browser.new_context(
                timezone_id="Asia/Seoul",
                locale="ko-KR",
                viewport={"width": width, "height": height},
                device_scale_factor=1.0,
                is_mobile=False,
                user_agent=user_agent,
            )
            _apply_stealth(self._context)

    def stop(self) -> None:
        LOGGER.debug("Stopping Playwright client")
        if self._context and not self._cdp_mode:
            # CDP 모드에서는 로컬 Chrome 컨텍스트를 닫지 않음
            self._context.close()
        self._context = None
        if self._browser:
            if self._cdp_mode:
                self._browser.close()  # CDP 연결만 해제 (Chrome 프로세스는 유지)
            else:
                self._browser.close()
        self._browser = None
        if self._playwright:
            self._playwright.stop()
        self._playwright = None
        self._cdp_mode = False

    def new_page(self) -> Page:
        page = self.context.new_page()
        _attach_popup_guard(page)
        return page



def safe_goto(page: Page, url: str, timeout_ms: int = 30_000) -> None:
    LOGGER.debug("Navigating to %s", url)
    try:
        page.goto(url, wait_until="load", timeout=timeout_ms)
    except TimeoutError as exc:
        raise SiteLayoutChanged(f"Timed out navigating to {url}") from exc


def safe_click(page: Page, selector: str, timeout_ms: int = 10_000) -> None:
    if not selector:
        raise SiteLayoutChanged("Selector is empty")
    try:
        page.click(selector, timeout=timeout_ms)
    except TimeoutError as exc:
        raise SiteLayoutChanged(f"Click timed out: {selector}") from exc


def wait_text(page: Page, text: str, timeout_ms: int = 10_000) -> None:
    try:
        page.wait_for_selector(f"text={text}", timeout=timeout_ms)
    except TimeoutError as exc:
        raise SiteLayoutChanged(f"Failed to find text: {text}") from exc


def dump_artifacts(page: Page, directory: Path, name: str) -> None:
    utils.ensure_dir(directory)
    safe_name = utils.safe_filename(name)
    screenshot_path = directory / f"{safe_name}.png"
    html_path = directory / f"{safe_name}.html"
    try:
        page.screenshot(path=str(screenshot_path), full_page=True)
        html = page.content()
        html_path.write_text(html, encoding="utf-8")
        LOGGER.info("Artifacts saved: %s, %s", screenshot_path, html_path)
    except Exception as exc:  # pragma: no cover - IO errors rare
        LOGGER.warning("Failed to dump artifacts: %s", exc)


__all__ = [
    "SRTClient",
    "safe_goto",
    "safe_click",
    "wait_text",
    "dump_artifacts",
    "_attach_popup_guard",
]
