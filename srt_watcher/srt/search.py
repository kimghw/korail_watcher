from __future__ import annotations

import logging
import re
import time
from datetime import time as Time
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Union

from playwright.sync_api import Page, Frame, Locator, TimeoutError as PlaywrightTimeoutError
from playwright._impl._errors import Error as PlaywrightError

from ..config import SRTConfig
from ..utils import detect_suspicious, timestamped_path, is_candidate
from . import CaptchaDetected, SiteLayoutChanged
from .client import SRTClient, dump_artifacts, safe_click, safe_goto, _attach_popup_guard
from . import selectors

LOGGER = logging.getLogger("srt_watcher.srt.search")

# 직접 접근 URL (pageId 포함 → dynaPath 라우팅과 일치)
SEARCH_URL = "https://etk.srail.kr/hpg/hra/01/selectScheduleList.do?pageId=TK0101010000"
# dynaPath 리다이렉트 수신 URL (SRT 보안 강화 이후)
SEARCH_PAGE_ID = "TK0101010000"

# 메인 페이지 (dynaPath 세션 토큰이 필요할 때 fallback 진입점)
MAIN_URL = "https://etk.srail.kr/main.do"

# 역 코드 (경주=0508 별칭 포함)
STATION_CODES = {
    "수서": "0551", "동탄": "0552", "평택지제": "0553",
    "천안아산": "0502", "오송": "0297", "대전": "0010",
    "김천(구미)": "0507", "김천구미": "0507",
    "서대구": "0506", "동대구": "0015", "신경주": "0508", "경주": "0508",
    "울산(통도사)": "0509", "부산": "0020",
    "공주": "0514", "익산": "0030", "정읍": "0033", "광주송정": "0036",
    "광명": "0501", "나주": "0037", "목포": "0041",
    "전주": "0045", "남원": "0048", "곡성": "0049", "구례구": "0050",
    "순천": "0051", "여천": "0139", "여수EXPO": "0053",
    "서울": "0001",
    "밀양": "0017", "진영": "0056", "창원중앙": "0512", "창원": "0057",
    "마산": "0059", "진주": "0063",
    "포항": "0515",
}

# 숨겨진 합계/성인수 필드 후보 (사이트 변경 대비)
HIDDEN_ADULT_CANDIDATES = ["psgInfoPerPrnb1", "psgrCnt1", "psgNum1", "adultCnt", "psgAdultCnt"]
HIDDEN_TOTAL_CANDIDATES = ["psgNum", "psgrTotCnt", "totalCnt", "totPsgCnt"]

_LABEL_RX = re.compile(r"(어른|성인).*(\d+)\s*명|^\s*(\d+)\s*명\s*$")

def _ensure_selectors() -> None:
    if not getattr(selectors, "SEARCH_BUTTON", None):
        raise SiteLayoutChanged("SEARCH_BUTTON selector not configured")
    if not getattr(selectors, "RESULT_ROWS", None):
        raise SiteLayoutChanged("RESULT_ROWS selector not configured")
    if not getattr(selectors, "COL_DEPART_TIME", None):
        raise SiteLayoutChanged("COL_DEPART_TIME selector not configured")


def _check_for_captcha(page: Page) -> None:
    try:
        html = page.content()
    except PlaywrightError as e:
        LOGGER.debug("Skipping captcha check while navigating: %s", e)
        return
    except Exception as e:
        LOGGER.debug("Skipping captcha check due to content() error: %s", e)
        return
    if detect_suspicious(html):
        raise CaptchaDetected("Captcha or automation guard detected")


def _parse_depart_time(raw: str) -> Time:
    raw = raw.strip()
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) < 4:
        raise ValueError(f"Cannot parse time from {raw!r}")
    hh = int(digits[0:2]); mm = int(digits[2:4])
    if not (0 <= hh < 24 and 0 <= mm < 60):
        raise ValueError(f"Invalid time parsed from {raw!r}")
    return Time(hour=hh, minute=mm)


def _select_time_slot(page_or_frame: Union[Page, Frame], selector: str, preferred_times: List[Time]) -> None:
    if not preferred_times:
        return
    target = preferred_times[0]
    target_minutes = target.hour * 60 + target.minute

    options = page_or_frame.eval_on_selector_all(
        selector,
        """sels => {
            if (!sels.length) return [];
            const sel = sels[0];
            return Array.from(sel.options).map(o => ({
                value: o.value || "",
                text: (o.textContent || "").trim()
            }));
        }""",
    )
    if not options:
        return

    def parse_minutes(opt):
        s = opt["value"] or opt["text"]
        digits = "".join(ch for ch in s if ch.isdigit())
        if len(digits) >= 2:
            hh = int(digits[:2])
            if 0 <= hh < 24:
                return hh * 60
        return None

    candidates = []
    for o in options:
        m = parse_minutes(o)
        if m is not None and m <= target_minutes:
            candidates.append((m, o["value"]))

    if candidates:
        best_value = max(candidates, key=lambda x: x[0])[1]
    else:
        best_value = options[0]["value"]

    if best_value:
        page_or_frame.select_option(selector, best_value)


# ----------------------------- Passenger selection -----------------------------

def _score_passenger_select(select: Locator) -> int:
    try:
        opts = select.locator("option")
        texts = opts.all_text_contents()
    except Exception:
        return 0

    score = 0
    hits = 0
    for t in texts:
        t = (t or "").strip()
        m = _LABEL_RX.search(t)
        if not m:
            continue
        n = int(m.group(2) or m.group(3))
        if 1 <= n <= 9:
            hits += 1
    score += hits
    if 3 <= len(texts) <= 12:
        score += 2
    return score


def _find_passenger_select(page: Page) -> Tuple[Union[Page, Frame], Locator]:
    """
    1) 우선순위: #psgInfoPerPrnb1 (너가 준 실제 id)
    2) 없으면 모든 frame/page의 <select> 스캔해서 'N명' 패턴 가장 잘 맞는 셀렉트를 반환
    """
    # 1) 먼저 id로
    try:
        sel = page.locator("#psgInfoPerPrnb1")
        if sel.count() > 0:
            return page, sel.first
    except Exception:
        pass
    for fr in page.frames:
        try:
            sel = fr.locator("#psgInfoPerPrnb1")
            if sel.count() > 0:
                return fr, sel.first
        except Exception:
            pass

    # 2) 동적 스캔
    contexts: List[Union[Page, Frame]] = [page] + [fr for fr in page.frames]
    best_ctx: Optional[Union[Page, Frame]] = None
    best_sel: Optional[Locator] = None
    best_score = 0
    for ctx in contexts:
        try:
            selects = ctx.locator("select")
            total = selects.count()
            for i in range(total):
                sel = selects.nth(i)
                s = _score_passenger_select(sel)
                if s > best_score:
                    best_score = s
                    best_ctx = ctx
                    best_sel = sel
        except Exception:
            continue
    if best_sel and best_score >= 2:
        return best_ctx, best_sel
    raise SiteLayoutChanged("Cannot find adult passenger <select> (id or pattern)")


def _sync_hidden_inputs(ctx: Union[Page, Frame], base: Locator, adult_count: int) -> None:
    # base는 select
    container = base.locator("xpath=ancestor-or-self::*[1]")
    for key in HIDDEN_ADULT_CANDIDATES:
        try:
            hid = container.locator(f"xpath=.//input[@type='hidden' and (@name='{key}' or @id='{key}')]")
            if hid.count() == 0:
                hid = ctx.locator(f"input[type='hidden'][name='{key}'], input[type='hidden']#{key}")
            if hid.count() > 0:
                ctx.evaluate(
                    "(el, v) => { el.value = String(v); "
                    "el.dispatchEvent(new Event('input', {bubbles:true})); "
                    "el.dispatchEvent(new Event('change', {bubbles:true})); }",
                    hid.first,
                    adult_count,
                )
        except Exception:
            pass
    for key in HIDDEN_TOTAL_CANDIDATES:
        try:
            hid = container.locator(f"xpath=.//input[@type='hidden' and (@name='{key}' or @id='{key}')]")
            if hid.count() == 0:
                hid = ctx.locator(f"input[type='hidden'][name='{key}'], input[type='hidden']#{key}")
            if hid.count() > 0:
                ctx.evaluate(
                    "(el, v) => { el.value = String(v); "
                    "el.dispatchEvent(new Event('input', {bubbles:true})); "
                    "el.dispatchEvent(new Event('change', {bubbles:true})); }",
                    hid.first,
                    adult_count,
                )
        except Exception:
            pass


def set_adult_passengers(page: Page, count: int, timeout_ms: int = 5000) -> None:
    """
    주 셀렉터: #psgInfoPerPrnb1
    실패 시: 동적 스캔으로 대체
    선택 순서: value -> label("N명") -> regex("어른/성인 ... N명") -> index(0-based) -> JS 강제
    + hidden total fields 동기화
    """
    original = count
    count = max(1, min(9, int(count or 1)))

    ctx, sel = _find_passenger_select(page)
    sel.wait_for(state="visible", timeout=timeout_ms)

    # 옵션 정보 수집 (디버깅 가독성용)
    try:
        opts = sel.locator("option")
        texts = opts.all_text_contents()
        values = [opts.nth(i).evaluate("o => o.value") for i in range(len(texts))]
    except Exception:
        texts, values = [], []

    ok = False
    # 1) value
    try:
        if str(count) in values:
            sel.select_option(value=str(count), timeout=timeout_ms)
            ok = True
    except Exception:
        ok = False
    # 2) "N명"
    if not ok:
        try:
            sel.select_option(label=f"{count}명", timeout=timeout_ms)
            ok = True
        except Exception:
            ok = False
    # 3) 정규식
    if not ok:
        try:
            sel.select_option(label=re.compile(rf"(어른|성인).*?\b{count}\s*명"), timeout=timeout_ms)
            ok = True
        except Exception:
            ok = False
    # 4) index (0-based: 1명=1, 2명=2 ...)
    if not ok:
        try:
            sel.select_option(index=str(count), timeout=timeout_ms)
            ok = True
        except Exception:
            ok = False
    # 5) JS 강제
    if not ok:
        try:
            ctx.evaluate(
                "(el, v) => { el.value = String(v); "
                "el.dispatchEvent(new Event('input', {bubbles:true})); "
                "el.dispatchEvent(new Event('change', {bubbles:true})); }",
                sel,
                count,
            )
            ok = True
        except Exception:
            ok = False

    # hidden 동기화
    _sync_hidden_inputs(ctx, sel, count)

    # 최종 검증
    try:
        selected_val = sel.input_value()
    except Exception:
        selected_val = ""
    try:
        txt = sel.evaluate("el => el.selectedOptions && el.selectedOptions[0] ? el.selectedOptions[0].textContent : ''") or ""
    except Exception:
        txt = ""

    if not ((selected_val == str(count)) or (f"{count}명" in txt)):
        raise RuntimeError(
            f"성인 인원 {count}명 선택 실패: value={selected_val}, text='{txt.strip()}', "
            f"values={values}, texts={texts}"
        )
    if original != count:
        LOGGER.info("성인 인원 입력값 %s → %s명으로 보정되어 선택됨.", original, count)


# ----------------------------- Form & Search flow -----------------------------

def _set_station(page: Page, name_selector: str, code_id: str, name: str, code: str) -> None:
    """역 이름/코드 입력.

    dptRsStnCdNm의 onkeyup 핸들러가 keyup 발생 시 dptRsStnCd.value를 ''으로 초기화한다.
    → page.fill() 대신 JS로 직접 value를 쓰고 이벤트를 최소화한다.
    → 코드를 마지막에 설정해서 onkeyup에 의한 wipe를 방지한다.
    """
    try:
        page.evaluate(
            """([nameSelector, codeId, nameVal, codeVal]) => {
                // 1) 이름 필드: value만 직접 설정 (keyup 트리거 없이)
                const nameEl = document.querySelector(nameSelector);
                if (nameEl) {
                    nameEl.value = nameVal;
                    nameEl.dispatchEvent(new Event('change', {bubbles: true}));
                }
                // 2) 코드 필드: 반드시 마지막에 설정 (onkeyup wipe 방지)
                const codeEl = document.getElementById(codeId);
                if (codeEl) {
                    codeEl.value = codeVal;
                }
            }""",
            [name_selector, code_id, name, code],
        )
        LOGGER.info("역 설정 완료: %s=%r, %s=%r", name_selector, name, code_id, code)
    except Exception as e:
        LOGGER.warning("역 설정 실패 (%s): %s", name, e)


def _select_date_closest(page: Page, date_selector: str, ymd: str) -> None:
    """날짜 select에서 ymd를 선택하거나, 없으면 가장 가까운 미래 날짜 선택."""
    try:
        # 옵션 목록 수집
        options = page.eval_on_selector_all(
            date_selector,
            "sels => Array.from(sels[0]?.options || []).map(o => o.value)",
        )
        if not options:
            LOGGER.warning("날짜 옵션 없음 (selector=%s)", date_selector)
            return

        if ymd in options:
            page.select_option(date_selector, ymd)
            LOGGER.info("날짜 선택: %s", ymd)
        else:
            # 원하는 날짜가 없으면 가장 마지막(최신) 날짜 선택하고 경고
            latest = max(options)
            page.select_option(date_selector, latest)
            LOGGER.warning(
                "⚠ 날짜 %s가 선택 가능 범위에 없음 (최대: %s). "
                "SRT는 보통 1개월 전부터 예약 가능 — 아직 오픈 전일 수 있습니다. "
                "최근 날짜 %s로 임시 선택.",
                ymd, latest, latest,
            )
    except Exception as e:
        LOGGER.warning("날짜 선택 실패: %s", e)


def fill_search_form(page: Page, config: SRTConfig) -> None:
    form = getattr(selectors, "SEARCH_FORM", None)
    if not form:
        return

    # 출발역 — select 드롭다운으로 코드 직접 선택
    if getattr(config, "srt_origin", None) and form.get("origin"):
        origin_code = STATION_CODES.get(config.srt_origin, "")
        if origin_code:
            try:
                page.select_option(form["origin"], origin_code)
                LOGGER.info("출발역 선택: %s (%s)", config.srt_origin, origin_code)
            except Exception:
                # fallback: JS로 직접 값 설정 (구버전 텍스트 입력 호환)
                _set_station(page, form["origin"], "dptRsStnCd", config.srt_origin, origin_code)

    # 도착역 — select 드롭다운
    if getattr(config, "srt_dest", None) and form.get("dest"):
        dest_code = STATION_CODES.get(config.srt_dest, "")
        if dest_code:
            try:
                page.select_option(form["dest"], dest_code)
                LOGGER.info("도착역 선택: %s (%s)", config.srt_dest, dest_code)
            except Exception:
                _set_station(page, form["dest"], "arvRsStnCd", config.srt_dest, dest_code)

    # 날짜 — input#cal (readonly, 형식 "2026.04.03") 또는 구버전 select
    if getattr(config, "srt_date", None) and form.get("date"):
        ymd_dot = config.srt_date.strftime("%Y.%m.%d")   # 2026.04.03
        ymd_plain = config.srt_date.strftime("%Y%m%d")    # 20260403
        try:
            page.evaluate(
                """([dotFmt, plainFmt]) => {
                    // 신규: input#cal (readonly text input)
                    const cal = document.getElementById('cal');
                    if (cal) {
                        cal.removeAttribute('readonly');
                        cal.value = dotFmt;
                        cal.setAttribute('readonly', '');
                        cal.dispatchEvent(new Event('change', {bubbles: true}));
                    }
                    // hidden 필드도 동기화 (form submit 시 사용)
                    const hidden = document.querySelector('input[name="dptDt"][type="hidden"]');
                    if (hidden) { hidden.value = plainFmt; }
                    // 구버전: select[name=dptDt]
                    const sel = document.querySelector('select[name="dptDt"]');
                    if (sel) {
                        for (const opt of sel.options) {
                            if (opt.value === plainFmt) { sel.value = plainFmt; break; }
                        }
                    }
                }""",
                [ymd_dot, ymd_plain],
            )
            LOGGER.info("날짜 설정: %s", ymd_dot)
        except Exception as e:
            LOGGER.warning("날짜 설정 실패: %s", e)

    # 성인 인원 — 리뉴얼: psgInfoPerPrnbzTxt + data-value / 구버전: select
    try:
        pax = int(getattr(config, "srt_passengers", 1) or 1)
        # 리뉴얼 방식: span.psgInfoPerPrnbzTxt1 의 data-value + hidden input
        set_ok = page.evaluate(
            """(count) => {
                // 모든 psgInfoPerPrnbzTxt1 span 요소 업데이트 (여러 개 존재)
                const spans = document.querySelectorAll('.psgInfoPerPrnbzTxt1');
                spans.forEach(span => {
                    span.textContent = String(count);
                    span.setAttribute('data-value', String(count));
                });
                const hidden1 = document.querySelector('input[name="psgInfoPerPrnb1"]');
                if (hidden1) { hidden1.value = String(count); }
                const psgNum = document.querySelector('input[name="psgNum"]');
                if (psgNum) {
                    const child = document.querySelector('.psgInfoPerPrnbzTxt5');
                    const childCnt = child ? parseInt(child.getAttribute('data-value') || '0') : 0;
                    psgNum.value = String(count + childCnt);
                }
                return spans.length > 0;
            }""",
            pax,
        )
        if set_ok:
            LOGGER.info("인원 설정 (리뉴얼): 어른 %d명", pax)
        else:
            # 구버전 fallback: select#psgInfoPerPrnb1
            set_adult_passengers(page, pax)
    except Exception as e:
        LOGGER.debug("Adult passengers selection skipped/failed: %s", e)

    # 시간 슬롯
    time_sel = form.get("time")
    if time_sel:
        preferred = (
            list(getattr(config, "preferred_times", []) or [])
            or list(getattr(config, "srt_times", []) or [])
        )
        if preferred:
            _select_time_slot(page, time_sel, preferred)

    # 폼 입력 후 역 코드 최종 검증 로그
    try:
        codes = page.evaluate("""() => ({
            dpt: document.getElementById('dptRsStnCd')?.value,
            arv: document.getElementById('arvRsStnCd')?.value,
            date: (document.getElementById('cal') || document.getElementById('dptDt') || {}).value,
        })""")
        LOGGER.info("폼 입력 검증: dptRsStnCd=%r arvRsStnCd=%r dptDt=%r", 
                    codes.get('dpt'), codes.get('arv'), codes.get('date'))
        if not codes.get('dpt') or not codes.get('arv'):
            LOGGER.warning("⚠ 역 코드가 비어있음 → submit 차단될 수 있음!")
    except Exception as e:
        LOGGER.debug("폼 검증 실패: %s", e)



def _time_to_minutes(t: Time) -> int:
    return t.hour * 60 + t.minute


def _candidate_score(depart: Time, preferred: List[Time]) -> int:
    if not preferred:
        return 0
    d = _time_to_minutes(depart)
    return min(abs(d - _time_to_minutes(p)) for p in preferred)


def _navigate_to_search(page: Page) -> None:
    """검색 페이지 진입 (리뉴얼 후 메인 페이지에 검색 폼 통합).

    1차: 메인 페이지 접속 → 검색 폼 존재 확인
    2차: 직접 SEARCH_URL 시도
    3차: 메뉴 클릭 fallback
    """
    detect_sel = getattr(selectors, "SEARCH_FORM_DETECT", "select#dptRsStnCd, form#search-form, #dptRsStnCdNm")

    # 이미 메인 페이지에 있으면 재탐색 생략
    try:
        cur = page.url or ""
        if "main.do" in cur and page.locator(detect_sel).count() > 0:
            LOGGER.info("검색 폼 이미 존재 (재사용): %s", cur)
            return
    except Exception:
        pass

    # 1차: 메인 페이지 (리뉴얼 후 검색 폼이 여기에 있음)
    LOGGER.debug("Navigating to main page for search form")
    try:
        safe_goto(page, MAIN_URL)
        try:
            page.wait_for_load_state("domcontentloaded", timeout=5_000)
        except PlaywrightTimeoutError:
            pass

        if page.locator(detect_sel).count() > 0:
            LOGGER.info("검색 폼 발견 (메인 페이지): %s", page.url)
            return
    except SiteLayoutChanged as e:
        LOGGER.warning("Main page navigation failed: %s", e)

    # 2차: 직접 SEARCH_URL 시도 (구버전 호환)
    LOGGER.debug("Trying direct SEARCH_URL")
    try:
        safe_goto(page, SEARCH_URL)
        try:
            page.wait_for_load_state("domcontentloaded", timeout=5_000)
        except PlaywrightTimeoutError:
            pass

        if page.locator(detect_sel).count() > 0:
            LOGGER.info("검색 폼 발견 (직접 URL): %s", page.url)
            return
    except SiteLayoutChanged as e:
        LOGGER.warning("Direct SEARCH_URL failed: %s", e)

    # 3차: 메뉴 클릭 fallback
    _navigate_via_main(page)


def _navigate_via_main(page: Page) -> None:
    """메인 페이지 경유 진입 (dynaPath 토큰 포함된 URL 자동 획득)."""
    LOGGER.info("Navigating to search via main page (dynaPath fallback)")
    safe_goto(page, MAIN_URL)
    try:
        page.wait_for_load_state("networkidle", timeout=10_000)
    except PlaywrightTimeoutError:
        pass

    # 메뉴에서 "일반승차권 조회" 링크 클릭
    nav_candidates = [
        f"a[href*='pageId={SEARCH_PAGE_ID}']",
        "a[href*='selectScheduleList']",
        "a:has-text('일반승차권')",
        "a:has-text('승차권 예약')",
    ]
    for nav_sel in nav_candidates:
        try:
            loc = page.locator(nav_sel).first
            if loc.count() > 0:
                loc.click(timeout=5_000)
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=10_000)
                except PlaywrightTimeoutError:
                    pass
                LOGGER.info(
                    "Navigated via main page [%s] → %s", nav_sel, page.url
                )
                return
        except Exception as e:
            LOGGER.debug("Main-page nav selector %s failed: %s", nav_sel, e)

    raise SiteLayoutChanged(
        "Cannot navigate to search page via main menu — site structure may have changed"
    )


def _is_on_result_page(page: Page) -> bool:
    """이미 검색 결과 페이지에 있는지 확인 (dynaPath 또는 selectScheduleList)."""
    try:
        url = page.url or ""
        if "dynaPath" not in url and "selectScheduleList" not in url and "pageId=TK0101011000" not in url:
            return False
        # 결과 행이 존재하는지 빠르게 체크
        return page.locator(selectors.RESULT_ROWS).count() > 0
    except Exception:
        return False


def perform_search(client: SRTClient, config: SRTConfig, artifact_root: Path) -> List[Dict[str, str]]:
    _ensure_selectors()

    # 로그인된 페이지를 재활용 (새 탭을 열면 cfg.isLogin이 false로 내려와 세션이 끊긴 것처럼 보임)
    existing_page = getattr(client, "last_page", None)
    if existing_page and not existing_page.is_closed():
        page = existing_page
    else:
        page = client.new_page()

    # 팝업 가드 부착 (사이트 팝업이 검색 버튼 클릭을 방해하는 문제 방지)
    _attach_popup_guard(page)

    keep_page = False
    matched: List[Dict[str, str]] = []

    try:
        # 이미 결과 페이지에 있으면 폼이 채워져 있으므로 조회 버튼만 다시 클릭
        if _is_on_result_page(page):
            LOGGER.info("결과 페이지 재사용 → 조회 버튼만 클릭 (URL: %s)", page.url)
        else:
            _navigate_to_search(page)
            _check_for_captcha(page)
            fill_search_form(page, config)
            LOGGER.info(
                "검색 폼 입력 완료 → 버튼 클릭 (URL: %s)", page.url
            )

        # selectScheduleList() 의 JS 유효성 검사가 alert() 를 호출할 수 있음
        _dialog_messages: list = []
        def _on_dialog(dialog):
            _dialog_messages.append(dialog.message)
            LOGGER.warning("검색 폼 다이얼로그: %s", dialog.message)
            dialog.accept()
        page.on("dialog", _on_dialog)

        # 팝업 차단 (검색 시 광고/공지 팝업 방지)
        try:
            page.evaluate("""() => {
                window.open = function() {
                    console.log('[SRT-Watcher] window.open blocked');
                    return null;
                };
            }""")
        except Exception:
            pass

        # 검색 버튼 클릭 + 페이지 네비게이션(form POST) 대기
        try:
            with page.expect_navigation(timeout=15_000, wait_until="domcontentloaded"):
                safe_click(page, selectors.SEARCH_BUTTON)
            LOGGER.info("검색 버튼 클릭 → 페이지 네비게이션 완료")
        except PlaywrightTimeoutError:
            LOGGER.warning("검색 버튼 클릭 후 네비게이션 타임아웃 — 현재 페이지에서 계속 진행")
        except PlaywrightError:
            # AJAX 방식일 경우 네비게이션 없이 결과가 삽입될 수 있음
            LOGGER.debug("No navigation detected after search click — may be AJAX based")

        page.remove_listener("dialog", _on_dialog)
        if _dialog_messages:
            LOGGER.warning("검색 폼 유효성 검사 실패: %s", _dialog_messages)

        _check_for_captcha(page)

        try:
            page.wait_for_load_state("networkidle", timeout=5_000)
        except PlaywrightTimeoutError:
            LOGGER.debug("networkidle wait timed out; continuing")

        # 실제 열차 데이터가 있는 행만 대기 (출발시각 컴럼이 있는 tr)
        result_row_with_data = f"{selectors.RESULT_ROWS}:has({selectors.COL_DEPART_TIME})"
        try:
            page.wait_for_selector(result_row_with_data, timeout=5_000)
        except PlaywrightTimeoutError:
            LOGGER.debug("Result rows with depart column not found in time; maybe empty or guard page")

        rows = page.query_selector_all(selectors.RESULT_ROWS)
        LOGGER.info("검색 결과: %d개 행 발견 (URL: %s)", len(rows), page.url)

        # 행이 0개면 페이지 HTML을 직접 저장 (screenshot timeout 우회)
        if len(rows) == 0:
            try:
                page_title = page.title()
                alt_rows_1 = len(page.query_selector_all("tbody > tr"))
                alt_rows_2 = len(page.query_selector_all("tr"))
                has_search_form = page.query_selector("#search_top_tag") is not None
                LOGGER.info(
                    "페이지 진단: title=%r | tbody>tr=%d | tr=%d | 검색폼=%s",
                    page_title, alt_rows_1, alt_rows_2, has_search_form,
                )
            except Exception as diag_e:
                LOGGER.info("페이지 진단 실패: %s", diag_e)

            # HTML 직접 저장 (screenshot 없이)
            try:
                from ..utils import ensure_dir
                artifact_dir = timestamped_path(artifact_root, "search-empty")
                ensure_dir(artifact_dir)
                html_content = page.content()
                html_path = artifact_dir / "search_empty.html"
                html_path.write_text(html_content, encoding="utf-8")
                LOGGER.info("아티팩트 HTML 저장 완료: %s (%d bytes)", html_path, len(html_content))
            except Exception as e:
                LOGGER.warning("아티팩트 저장 실패: %s", e)

        seat_class = (config.srt_seat_class or "").strip()
        preferred_times = list(config.srt_times)
        tolerance_min = config.srt_tolerance_min
        time_window = config.srt_time_window

        for idx, row in enumerate(rows, start=1):
            depart_el = row.query_selector(selectors.COL_DEPART_TIME)
            if not depart_el:
                LOGGER.info("  Row %d: 출발시각 컬럼 없음 (skip)", idx)
                continue
            depart_raw = depart_el.inner_text().strip()
            try:
                depart_time = _parse_depart_time(depart_raw)
            except ValueError:
                LOGGER.info("  Row %d: 시각 파싱 실패 raw=%r (skip)", idx, depart_raw)
                continue

            if not is_candidate(
                candidate_time=depart_time,
                preferred_times=preferred_times,
                tolerance_min=tolerance_min,
                time_window=time_window,
            ):
                LOGGER.info(
                    "  Row %d: %s → 시간 필터 제외 (preferred=%s tolerance=%d window=%s)",
                    idx,
                    depart_time.strftime("%H:%M"),
                    [t.strftime("%H:%M") for t in preferred_times],
                    tolerance_min,
                    time_window,
                )
                continue

            reserve_btn = None
            button_selector = ""

            if seat_class in ("일반실", "일반"):
                btn_sel = getattr(selectors, "BUTTON_GENERAL", None)
                if btn_sel:
                    reserve_btn = row.query_selector(btn_sel)
                    button_selector = btn_sel
            elif seat_class in ("특실", "우등"):
                btn_sel = getattr(selectors, "BUTTON_FIRST", None)
                if btn_sel:
                    reserve_btn = row.query_selector(btn_sel)
                    button_selector = btn_sel
            else:
                for name in ("BUTTON_GENERAL", "BUTTON_FIRST", "BUTTON_RESERVE"):
                    btn_sel = getattr(selectors, name, None)
                    if not btn_sel:
                        continue
                    reserve_btn = row.query_selector(btn_sel)
                    if reserve_btn:
                        button_selector = btn_sel
                        break

            if not reserve_btn or not button_selector:
                LOGGER.info(
                    "  Row %d: %s → 예약버튼 없음/매진 (seat_class=%s, skip)",
                    idx, depart_time.strftime("%H:%M"), seat_class or "ANY",
                )
                continue

            row_selector = f"{selectors.RESULT_ROWS}:nth-of-type({idx})"
            parts = [p.strip() for p in button_selector.split(",") if p.strip()]
            scoped = ", ".join(f"{row_selector} {p}" for p in parts) if parts else f"{row_selector} {button_selector}"
            full_selector = scoped

            score = _candidate_score(depart_time, preferred_times)

            LOGGER.info(
                "Found candidate: depart=%s seat_class=%s score=%d selector=%s",
                depart_time.strftime("%H:%M"),
                seat_class or "ANY",
                score,
                full_selector,
            )

            matched.append(
                {
                    "origin": config.srt_origin,
                    "dest": config.srt_dest,
                    "date": config.srt_date.strftime("%Y-%m-%d"),
                    "depart": depart_time.strftime("%H:%M"),
                    "seat_class": seat_class or "일반실",
                    "status": "AVAILABLE",
                    "reserve_selector": full_selector,
                    "reserve_onclick": reserve_btn.get_attribute("onclick") if reserve_btn else "",
                    "score": score,
                }
            )

        matched.sort(key=lambda c: c.get("score", 0))
        if not matched:
            LOGGER.debug("No seats available this cycle.")
            # 페이지를 유지해서 다음 주기에 조회 버튼만 다시 클릭
            keep_page = _is_on_result_page(page)
            if keep_page:
                client.last_page = page
                LOGGER.debug("Keeping result page for re-query next cycle")
            if LOGGER.isEnabledFor(logging.DEBUG) and not keep_page:
                try:
                    artifact_dir = timestamped_path(artifact_root, "search-debug")
                    dump_artifacts(page, artifact_dir, "search_empty")
                    LOGGER.info("Dumped debug artifacts for empty result into %s", artifact_dir)
                except Exception as e:
                    LOGGER.debug("Failed to dump debug artifacts: %s", e)
        else:
            keep_page = True
            client.last_page = page
            LOGGER.debug("Keeping result page open; %d candidates", len(matched))

        for c in matched:
            c.pop("score", None)

        return matched

    except Exception:
        artifact_dir = timestamped_path(artifact_root, "search-error")
        dump_artifacts(page, artifact_dir, "search_failure")
        if not page.is_closed():
            page.close()
        if getattr(client, "last_page", None) is page:
            client.last_page = None
        raise

    finally:
        if not keep_page and not page.is_closed():
            page.close()
            if getattr(client, "last_page", None) is page:
                client.last_page = None
                