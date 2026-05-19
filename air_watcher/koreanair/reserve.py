"""KE 좌석 hold (예약 단계). 결제는 자동화하지 않음.

- `ensure_logged_in`: Playwright 로 KE 로그인 페이지에서 ID/PW 입력→제출.
  로그인이 끝나면 Akamai bot manager 가 인증 쿠키를 세팅해주고,
  이후 `air-bounds` 같은 API 가 200 응답을 준다 (anonymous 호출은 403).
- `warm_up_select_flight`: 홈 위젯 → trip/origin/dest/date 채우고 '항공편 검색' 클릭.
  Akamai 가 /booking/select-flight 직접 navigate 는 / 로 redirect 시키므로,
  위젯 경유가 select-flight 진입의 유일한 합법 경로.
- `attempt_reservation`: selector 라이브 매핑 필요 — 현재 NotImplementedError.
"""

from __future__ import annotations

import json
import logging
import time as _time
from datetime import date as _date_cls
from typing import Dict, Optional

from playwright.sync_api import TimeoutError as PWTimeoutError

from ..config import AirConfig
from . import LoginError
from .client import KoreanAirSPAClient

LOGGER = logging.getLogger("air_watcher.koreanair.reserve")


# Playwright evaluate 는 expression 만 받음 → 모든 JS 는 IIFE 안에서 자기-포함되게 작성.

_IS_LOGGED_IN_JS = r"""
(() => {
  function _walk(root, depth, out) {
    if (depth > 14) return;
    const all = root.querySelectorAll ? root.querySelectorAll('*') : [];
    for (const el of all) { out.push(el); if (el.shadowRoot) _walk(el.shadowRoot, depth+1, out); }
  }
  const a=[]; _walk(document, 0, a);
  for (const el of a) {
    const t = (el.innerText || '').trim();
    if (t === '로그아웃') return true;
    if (el.tagName === 'LI' && (el.getAttribute('data-toggle')||'') === 'logout') return true;
  }
  return false;
})()
"""


def _is_logged_in(page, wait_s: float = 0.0) -> bool:
    """현재 페이지 DOM 에 로그아웃 indicator 가 있는지. wait_s 초까지 polling."""
    deadline = _time.time() + max(0.0, wait_s)
    while True:
        try:
            if page.evaluate(_IS_LOGGED_IN_JS):
                return True
        except Exception as e:
            LOGGER.debug("is_logged_in eval error: %s", e)
        if _time.time() >= deadline:
            return False
        _time.sleep(0.5)


def _set_input_value(page, want_type: str, value: str) -> bool:
    js = r"""
    ((wantType, val) => {
      function _walk(root, depth, out) {
        if (depth > 14) return;
        const all = root.querySelectorAll ? root.querySelectorAll('*') : [];
        for (const el of all) { out.push(el); if (el.shadowRoot) _walk(el.shadowRoot, depth+1, out); }
      }
      const a=[]; _walk(document, 0, a);
      for (const el of a) {
        if (el.tagName !== 'INPUT') continue;
        if (el.type !== wantType) continue;
        const r = el.getBoundingClientRect();
        if (r.width <= 0 || r.height <= 0) continue;
        el.focus();
        const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
        setter.call(el, val);
        el.dispatchEvent(new Event('input', {bubbles:true}));
        el.dispatchEvent(new Event('change', {bubbles:true}));
        el.dispatchEvent(new KeyboardEvent('keyup', {bubbles:true}));
        el.blur();
        return el.value === val;
      }
      return false;
    })
    """
    return bool(page.evaluate(f"{js}({json.dumps(want_type)}, {json.dumps(value)})"))


_CLICK_LOGIN_JS = r"""
(() => {
  function _walk(root, depth, out) {
    if (depth > 14) return;
    const all = root.querySelectorAll ? root.querySelectorAll('*') : [];
    for (const el of all) { out.push(el); if (el.shadowRoot) _walk(el.shadowRoot, depth+1, out); }
  }
  const a=[]; _walk(document, 0, a);
  for (const el of a) {
    if (el.tagName !== 'BUTTON') continue;
    if ((el.innerText || '').trim() !== '로그인') continue;
    const r = el.getBoundingClientRect();
    if (r.width <= 200) continue;
    el.click();
    return true;
  }
  return false;
})()
"""


def _click_login_button(page) -> bool:
    return bool(page.evaluate(_CLICK_LOGIN_JS))


_DISMISS_PW_ADVISORY_JS = r"""
(() => {
  // 비밀번호 변경 안내 모달 — '90일 후에 변경' 또는 '닫기' 클릭.
  const dialogs = Array.from(document.querySelectorAll('[role=dialog], .dialog.-active'));
  for (const d of dialogs) {
    const txt = (d.innerText || '');
    if (!txt.includes('비밀번호 변경 안내')) continue;
    const btns = Array.from(d.querySelectorAll('button'));
    for (const b of btns) {
      const t = (b.innerText || '').trim();
      if (t === '90일 후에 변경' || t === '닫기') {
        b.click();
        return t;
      }
    }
  }
  return null;
})()
"""


def _dismiss_password_advisory(page) -> bool:
    try:
        return bool(page.evaluate(_DISMISS_PW_ADVISORY_JS))
    except Exception as e:
        LOGGER.debug("dismiss advisory eval error: %s", e)
        return False


_ERR_MSGS_JS = r"""
(() => {
  function _walk(root, depth, out) {
    if (depth > 14) return;
    const all = root.querySelectorAll ? root.querySelectorAll('*') : [];
    for (const el of all) { out.push(el); if (el.shadowRoot) _walk(el.shadowRoot, depth+1, out); }
  }
  const a=[]; _walk(document, 0, a);
  const out=[];
  for (const el of a) {
    const t = (el.innerText||'').trim();
    if (!t || t.length > 200) continue;
    if (/실패|오류|일치|확인.*비밀|잠금|차단|invalid|incorrect|error/i.test(t)) {
      out.push(t.slice(0, 160));
      if (out.length >= 5) break;
    }
  }
  return out;
})()
"""


def ensure_logged_in(client: KoreanAirSPAClient, cfg: AirConfig) -> None:
    """Playwright 로 KE 로그인 → 쿠키/세션 확보. 이미 로그인 상태면 skip."""
    page = client.page

    if "koreanair.com" not in (page.url or ""):
        try:
            page.goto("https://www.koreanair.com/",
                      wait_until="domcontentloaded", timeout=30_000)
        except PWTimeoutError:
            LOGGER.warning("home goto timeout — 그대로 진행")

    # 헤더 hydration 늦으면 indicator 늦게 뜸 — 8초까지 polling.
    if _is_logged_in(page, wait_s=8.0):
        LOGGER.info("이미 로그인 상태")
        return

    if not cfg.air_user or not cfg.air_pass:
        raise LoginError("AIR_USER / AIR_PASS 비어 있음 — .env 확인")

    LOGGER.info("로그인 페이지 진입")
    try:
        page.goto("https://www.koreanair.com/login?returnUrl=%2F",
                  wait_until="domcontentloaded", timeout=30_000)
    except PWTimeoutError:
        LOGGER.warning("login goto timeout — 그대로 진행")

    # form hydration 대기
    try:
        page.wait_for_selector("input[type=password]", timeout=20_000, state="visible")
    except PWTimeoutError as e:
        raise LoginError(f"로그인 폼 hydration 실패: {e}") from e
    _time.sleep(1.0)

    if not _set_input_value(page, "text", cfg.air_user):
        raise LoginError("ID 필드 입력 실패")
    _time.sleep(0.3)
    if not _set_input_value(page, "password", cfg.air_pass):
        raise LoginError("PW 필드 입력 실패")
    _time.sleep(0.3)

    LOGGER.info("로그인 버튼 클릭")
    if not _click_login_button(page):
        raise LoginError("로그인 버튼 못 찾음")

    deadline = _time.time() + 25.0
    while _time.time() < deadline:
        if _dismiss_password_advisory(page):
            LOGGER.info("비밀번호 변경 안내 모달 dismiss (90일 후에 변경)")
            _time.sleep(1.5)
        if _is_logged_in(page):
            LOGGER.info("로그인 성공")
            return
        if "/login" not in (page.url or ""):
            # URL 이 바뀌었으면 로그인 처리 끝 — indicator 한 번 더 확인
            _time.sleep(1.5)
            if _is_logged_in(page):
                LOGGER.info("로그인 성공 (redirect 후)")
                return
        _time.sleep(1.0)

    try:
        errs = page.evaluate(_ERR_MSGS_JS) or []
    except Exception:
        errs = []
    raise LoginError("로그인 timeout (25s) — 로그아웃 indicator 안 보임. "
                     f"page errs={errs} url={page.url!r}")


# ─── warm-up: 홈 위젯 → '항공편 검색' 클릭으로 select-flight 진입 ─────────────
# runs/cdp_book_final.py 의 raw CDP 로직을 Playwright 로 포팅 + 일반화.
# Akamai 는 /booking/select-flight 로 직접 goto 하면 / 로 redirect 시키므로
# 위젯 경유가 유일한 합법 진입 경로다.

_JS_WALK = r"""
function _walk(root, d, o) {
  if (d > 14) return;
  const all = root.querySelectorAll ? root.querySelectorAll('*') : [];
  for (const el of all) { o.push(el); if (el.shadowRoot) _walk(el.shadowRoot, d+1, o); }
}
"""


def _set_viewport(page) -> None:
    try:
        page.set_viewport_size({"width": 1920, "height": 1080})
    except Exception as e:
        LOGGER.debug("viewport set failed: %s", e)


def _ensure_home(page) -> None:
    # 로그인 직후의 redirect 중간 상태에서 chip click handler 가 wire-up 전이면
    # 클릭이 먹히지 않는다 → fresh navigate 로 깨끗하게 다시 로드.
    LOGGER.info("warm-up: home fresh navigate (url=%s)", page.url)
    try:
        page.goto("https://www.koreanair.com/",
                  wait_until="domcontentloaded", timeout=30_000)
    except PWTimeoutError:
        LOGGER.warning("warm-up: home goto timeout — 계속 진행")
    deadline = _time.time() + 15.0
    while _time.time() < deadline:
        try:
            if page.evaluate("!!document.querySelector(\"input[id='chip-2']\")"):
                # chip-2 가 DOM 에는 있어도 click handler 가 hydration 전일 수 있어
                # 추가 1 초 대기.
                _time.sleep(1.0)
                return
        except Exception:
            pass
        _time.sleep(0.3)
    raise LoginError("warm-up: home widget hydration 실패 (chip-2 못 찾음)")


def _trip_chip_id(trip_type: str) -> str:
    # 홈 위젯 라디오: chip-1=왕복, chip-2=편도 (관찰 기반)
    return "chip-2" if trip_type == "oneway" else "chip-1"


def _is_trip_active(page, chip_id: str) -> bool:
    try:
        return bool(page.evaluate(
            "(id) => (document.querySelector(`input[id='${id}']`) || {}).checked === true",
            chip_id,
        ))
    except Exception:
        return False


def _click_trip_chip(page, chip_id: str) -> str:
    """chip-X 라디오 클릭. label[for]→parent wrapper→input 직접 순서로 시도."""
    return page.evaluate(
        "(id) => {"
        r"""
          const inp = document.querySelector(`input[id='${id}']`);
          if (!inp) return 'no-input';
          const lbl = document.querySelector(`label[for='${id}']`);
          if (lbl) {
            const r = lbl.getBoundingClientRect();
            if (r.width > 0 && r.height > 0) { lbl.click(); return 'label'; }
          }
          if (inp.parentElement) {
            const p = inp.parentElement;
            const r = p.getBoundingClientRect();
            if (r.width > 0 && r.height > 0) { p.click(); return 'parent'; }
          }
          inp.click();
          return 'input';
        """
        " }",
        chip_id,
    )


def _ensure_trip_type(page, trip_type: str) -> None:
    chip_id = _trip_chip_id(trip_type)
    for attempt in range(6):
        if _is_trip_active(page, chip_id):
            if attempt > 0:
                LOGGER.info("warm-up: chip=%s 활성화 (attempt %d)", chip_id, attempt)
            return
        try:
            via = _click_trip_chip(page, chip_id)
            LOGGER.info("warm-up: chip=%s click attempt %d via=%s", chip_id, attempt, via)
        except Exception as e:
            LOGGER.debug("trip chip click err: %s", e)
        _time.sleep(1.0)
    # 실패 시 진단 정보 + 스크린샷
    try:
        diag = page.evaluate(
            "(id) => {"
            r"""
              const inp = document.querySelector(`input[id='${id}']`);
              const lbl = document.querySelector(`label[for='${id}']`);
              return {
                inp_found: !!inp,
                inp_checked: inp ? inp.checked : null,
                inp_type: inp ? inp.type : null,
                inp_disabled: inp ? inp.disabled : null,
                lbl_found: !!lbl,
                lbl_text: lbl ? (lbl.innerText||'').slice(0, 50) : null,
                url: location.href,
              };
            """
            " }",
            chip_id,
        )
    except Exception:
        diag = {"eval_err": True}
    try:
        page.screenshot(path="runs/warmup_chip_fail.png", full_page=False)
    except Exception:
        pass
    raise LoginError(
        f"warm-up: trip_type={trip_type} chip 활성화 실패 — diag={diag}, "
        f"스크린샷=runs/warmup_chip_fail.png"
    )


def _widget_button(page, side: str) -> Optional[Dict]:
    """홈 위젯에서 origin/dest/date/pax/cabin 버튼의 center 좌표 + 텍스트."""
    body = _JS_WALK + r"""
      const a=[]; _walk(document, 0, a);
      let sw=null;
      for (const el of a) {
        if (el.tagName !== 'BUTTON') continue;
        if ((el.innerText||'').includes('출발지와 도착지 바꾸기')) {
          const r = el.getBoundingClientRect();
          sw = {x:r.x, y:r.y, w:r.width, h:r.height}; break;
        }
      }
      if (!sw) return null;
      const row = [];
      for (const el of a) {
        if (el.tagName !== 'BUTTON') continue;
        const r = el.getBoundingClientRect();
        if (r.width <= 0 || r.height <= 0) continue;
        if (Math.abs(r.y - sw.y) > 30) continue;
        if ((el.innerText||'').includes('출발지와 도착지 바꾸기')) continue;
        row.push({x:r.x, y:r.y, w:r.width, h:r.height,
                  t:(el.innerText||'').replace(/\s+/g,' ').trim()});
      }
      row.sort((a,b)=>a.x - b.x);
      const ll = row.filter(b => b.x + b.w <= sw.x + sw.w);
      const rr = row.filter(b => b.x >= sw.x);
      const map = {origin: ll[ll.length-1], dest: rr[0], date: rr[1], pax: rr[2], cabin: rr[3]};
      const want = map[side];
      if (!want) return null;
      return {x: want.x + want.w/2, y: want.y + want.h/2, t: (want.t||'').slice(0,120)};
    """
    return page.evaluate("(side) => { " + body + " }", side)


def _airport_matches(info: Optional[Dict], iata: str) -> bool:
    if not info:
        return False
    return iata.upper() in (info.get("t") or "").upper()


_AIRPORT_PICKER_OPEN_JS = r"""
(() => {
  // KE airport picker 는 role=dialog 가 아님 → 'city 검색' input 존재로 판정.
  // shadow DOM piercing 필수.
  function _walk(root, d, o) {
    if (d > 14) return;
    const all = root.querySelectorAll ? root.querySelectorAll('*') : [];
    for (const el of all) { o.push(el); if (el.shadowRoot) _walk(el.shadowRoot, d+1, o); }
  }
  const a = []; _walk(document, 0, a);
  for (const el of a) {
    if (el.tagName !== 'INPUT') continue;
    if (el.type !== 'text' && el.type !== 'search') continue;
    const ph = (el.placeholder || '') + (el.getAttribute('aria-label') || '');
    if (!/도시|공항|city|airport/i.test(ph)) continue;
    const r = el.getBoundingClientRect();
    if (r.width > 0 && r.height > 0) return true;
  }
  return false;
})()
"""


def _airport_picker_open(page) -> bool:
    try:
        return bool(page.evaluate(_AIRPORT_PICKER_OPEN_JS))
    except Exception:
        return False


def _open_airport_picker(page, side: str) -> None:
    last_info = None
    for attempt in range(4):
        if _airport_picker_open(page):
            return
        info = _widget_button(page, side)
        last_info = info
        LOGGER.info("warm-up: open %s picker attempt %d, btn=%s", side, attempt, info)
        if not info:
            _time.sleep(0.8); continue
        # 1) Playwright mouse click (실제 마우스 이벤트 dispatch)
        page.mouse.click(info["x"], info["y"])
        _time.sleep(1.5)
        if _airport_picker_open(page):
            return
        # 2) JS .click() (handler 가 isTrusted 검사 안 하면 먹힘)
        try:
            page.evaluate(
                "(side) => { " + _JS_WALK + r"""
                  const a=[]; _walk(document, 0, a);
                  let sw=null;
                  for (const el of a) {
                    if (el.tagName !== 'BUTTON') continue;
                    if ((el.innerText||'').includes('출발지와 도착지 바꾸기')) {
                      const r = el.getBoundingClientRect();
                      sw = {x:r.x, y:r.y, w:r.width, h:r.height}; break;
                    }
                  }
                  if (!sw) return false;
                  const row = [];
                  for (const el of a) {
                    if (el.tagName !== 'BUTTON') continue;
                    const r = el.getBoundingClientRect();
                    if (r.width <= 0 || r.height <= 0) continue;
                    if (Math.abs(r.y - sw.y) > 30) continue;
                    if ((el.innerText||'').includes('출발지와 도착지 바꾸기')) continue;
                    row.push({el, x:r.x, y:r.y, w:r.width, h:r.height});
                  }
                  row.sort((a,b)=>a.x - b.x);
                  const ll = row.filter(b => b.x + b.w <= sw.x + sw.w);
                  const rr = row.filter(b => b.x >= sw.x);
                  const map = {origin: ll[ll.length-1], dest: rr[0], date: rr[1], pax: rr[2], cabin: rr[3]};
                  const want = map[side];
                  if (want) { want.el.click(); return true; }
                  return false;
                } """,
                side,
            )
        except Exception as e:
            LOGGER.debug("js click err: %s", e)
        _time.sleep(1.2)
    try:
        page.screenshot(path=f"runs/warmup_{side}_picker_fail.png", full_page=False)
    except Exception:
        pass
    raise LoginError(
        f"warm-up: {side} picker 못 열음 (last_btn={last_info}, "
        f"스크린샷=runs/warmup_{side}_picker_fail.png)"
    )


def _type_in_airport_input(page, code: str) -> bool:
    return bool(page.evaluate(
        "(code) => { " + _JS_WALK + r"""
          const a=[]; _walk(document, 0, a);
          for (const el of a) {
            if (el.tagName !== 'INPUT') continue;
            if (el.type !== 'text' && el.type !== 'search') continue;
            const ph = (el.placeholder||'') + (el.getAttribute('aria-label')||'');
            if (!/도시|공항|city|airport/i.test(ph)) continue;
            const r = el.getBoundingClientRect();
            if (r.width <= 0) continue;
            el.focus();
            const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
            setter.call(el, '');
            el.dispatchEvent(new Event('input', {bubbles:true}));
            setter.call(el, code);
            el.dispatchEvent(new Event('input', {bubbles:true}));
            el.dispatchEvent(new Event('change', {bubbles:true}));
            return true;
          }
          return false;
        }""",
        code,
    ))


def _click_airport_result(page, code: str) -> bool:
    return bool(page.evaluate(
        "(code) => { " + _JS_WALK + r"""
          const a=[]; _walk(document, 0, a);
          let best=null, ba=1e12;
          for (const el of a) {
            const t = (el.innerText||'').trim();
            if (!t.includes(code) || t.length > 140) continue;
            const r = el.getBoundingClientRect();
            if (r.width <= 0 || r.height <= 0) continue;
            const ar = r.width * r.height;
            if (ar < ba) { best = el; ba = ar; }
          }
          if (!best) return false;
          let n = best;
          for (let i=0; i<6; i++) {
            if (!n) break;
            const role = n.getAttribute && n.getAttribute('role');
            if (n.tagName === 'LI' || n.tagName === 'BUTTON' || role === 'option') {
              n.click(); return true;
            }
            n = n.parentElement;
          }
          best.click(); return true;
        }""",
        code,
    ))


# 주요 국내선 IATA → 한국어 도시명 (KE 픽커가 IATA 검색 안 받을 때 fallback)
_IATA_TO_KOR = {
    "GMP": "김포", "ICN": "인천", "CJU": "제주", "PUS": "부산",
    "TAE": "대구", "CJJ": "청주", "KWJ": "광주", "USN": "울산",
    "RSU": "여수", "YNY": "양양", "KPO": "포항", "HIN": "사천",
}


def _set_airport(page, side: str, iata: str) -> None:
    iata = iata.upper()
    if _airport_matches(_widget_button(page, side), iata):
        return
    _open_airport_picker(page, side)
    # IATA → 한글 도시명 순서로 시도. 결과 클릭은 항상 IATA 포함 텍스트로 필터링.
    queries = [iata]
    kor = _IATA_TO_KOR.get(iata)
    if kor:
        queries.append(kor)
    for q in queries:
        if not _type_in_airport_input(page, q):
            LOGGER.debug("warm-up: airport input 못 찾음 (query=%s)", q)
            continue
        _time.sleep(1.0)
        for _ in range(3):
            _click_airport_result(page, iata)
            _time.sleep(1.2)
            if _airport_matches(_widget_button(page, side), iata):
                return
    cur = (_widget_button(page, side) or {}).get("t")
    raise LoginError(f"warm-up: {side}={iata} 선택 실패 (현재='{cur}')")


def _is_date_picker_open(page) -> bool:
    try:
        return bool(page.evaluate(
            "document.querySelectorAll('.ui-datepicker__td-date').length > 0"))
    except Exception:
        return False


def _open_date_picker(page) -> None:
    for _ in range(3):
        if _is_date_picker_open(page):
            return
        info = _widget_button(page, "date")
        if not info:
            _time.sleep(1.0); continue
        page.mouse.click(info["x"], info["y"])
        _time.sleep(2.0)
    raise LoginError("warm-up: date picker 못 열음")


def _depart_date_matches(page, target: _date_cls) -> bool:
    info = _widget_button(page, "date")
    if not info:
        return False
    t = info.get("t") or ""
    # KE 버튼 텍스트 패턴 후보 — 어느 하나라도 들어 있으면 매치로 판정
    needles = [
        f"{target.month}월 {target.day}일",
        f"{target.month:02d}.{target.day:02d}",
        f"{target.month:02d}-{target.day:02d}",
        f"{target.year}-{target.month:02d}-{target.day:02d}",
    ]
    return any(p in t for p in needles)


def _locate_day_cell(page, year: int, month: int, day: int) -> Optional[Dict]:
    """캘린더 grid 에서 (year, month) 칼럼의 day TD center 좌표 반환."""
    return page.evaluate(
        "([y, m, d]) => { " + _JS_WALK + r"""
          const a=[]; _walk(document, 0, a);
          const re = new RegExp('^' + y + '년?\\s*' + m + '월$');
          let jx = null;
          for (const el of a) {
            const t = (el.innerText||'').replace(/\s+/g,' ').trim();
            if (re.test(t)) {
              const r = el.getBoundingClientRect();
              if (r.width > 50) { jx = [r.x - 30, r.x + r.width + 200]; break; }
            }
          }
          let td = null;
          for (const el of a) {
            if (el.tagName !== 'SPAN') continue;
            if (!(el.className||'').toString().includes('ui-datepicker__td-date')) continue;
            if ((el.innerText||'').trim() !== String(d)) continue;
            const r = el.getBoundingClientRect();
            if (jx && (r.x < jx[0] || r.x > jx[1])) continue;
            let n = el.parentElement;
            while (n) {
              if (n.tagName === 'TD' || n.tagName === 'BUTTON'
                  || (n.getAttribute && n.getAttribute('role') === 'gridcell')) {
                td = n; break;
              }
              n = n.parentElement;
            }
            if (!td) td = el;
            break;
          }
          if (!td) return null;
          const r = td.getBoundingClientRect();
          if (r.width <= 0 || r.height <= 0) return null;
          return {x: r.x + r.width/2, y: r.y + r.height/2,
                  cls: (td.className||'').toString()};
        }""",
        [year, month, day],
    )


def _pick_day_in_month(page, year: int, month: int, day: int) -> Dict:
    """trusted 마우스 이벤트로 day cell 클릭 — Angular state 반영 보장."""
    cell = _locate_day_cell(page, year, month, day)
    if not cell:
        return {"ok": False, "why": "no td"}
    page.mouse.click(cell["x"], cell["y"])
    return {"ok": True, "cls": cell.get("cls", "")}


def _date_dialog_buttons(page):
    """date picker 안의 모든 button 텍스트/aria/위치 dump (진단용)."""
    try:
        return page.evaluate("(() => { " + _JS_WALK + r"""
          const a=[]; _walk(document, 0, a);
          // .ui-datepicker 컨테이너 안에 있는 button 들 수집 — role=dialog 와 무관.
          let host = null;
          for (const el of a) {
            const cls = (el.className||'').toString();
            if (cls.includes('ui-datepicker') && el.querySelector && el.querySelector('button')) {
              host = el; break;
            }
          }
          if (!host) {
            // role=dialog 도 시도
            for (const el of a) {
              if (el.getAttribute && el.getAttribute('role') === 'dialog' && el.querySelector && el.querySelector('button')) {
                host = el; break;
              }
            }
          }
          if (!host) return null;
          const out = [];
          for (const b of host.querySelectorAll('button')) {
            const r = b.getBoundingClientRect();
            if (r.width <= 0) continue;
            out.push({
              t: (b.innerText||'').replace(/\s+/g,' ').trim().slice(0, 40),
              aria: (b.getAttribute('aria-label') || '').slice(0, 40),
              cls: (b.className||'').toString().slice(0, 60),
              x: Math.round(r.x), y: Math.round(r.y),
              w: Math.round(r.width), h: Math.round(r.height),
              disabled: !!b.disabled,
            });
          }
          return out;
        })()""")
    except Exception as e:
        LOGGER.debug("date buttons dump err: %s", e)
        return None


def _close_date_dialog(page) -> None:
    """date picker 의 확인/적용/완료/선택 류 버튼 클릭 → 안 닫히면 Escape → 외부 click.

    KE 의 date picker 는 role=dialog 가 있을 수도, 없을 수도(.ui-datepicker 컨테이너만 있음).
    그래서 'role=dialog 안' 조건 대신, button 텍스트만으로 매칭한다.
    """
    try:
        clicked = page.evaluate("(() => { " + _JS_WALK + r"""
          const a=[]; _walk(document, 0, a);
          for (const el of a) {
            if (el.tagName !== 'BUTTON') continue;
            const r = el.getBoundingClientRect();
            if (r.width <= 0 || r.height <= 0) continue;
            if (el.disabled) continue;
            const t = (el.innerText||'').replace(/\s+/g,' ').trim();
            const aria = (el.getAttribute('aria-label') || '').trim();
            // 위젯 본체 버튼 제외 (항공편 검색 등)
            if (t === '항공편 검색') continue;
            if (['확인','적용','완료','선택','선택 완료','출발일 선택','저장'].includes(t)
                || /^선택 완료$/.test(aria) || /적용$/.test(aria) || /^확인$/.test(aria)) {
              el.click();
              return {t, aria};
            }
          }
          return null;
        })()""")
        LOGGER.info("warm-up: date apply click -> %s", clicked)
    except Exception as e:
        LOGGER.debug("date apply click err: %s", e)
    _time.sleep(1.0)
    if _is_date_picker_open(page):
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        _time.sleep(0.5)
    if _is_date_picker_open(page):
        try:
            page.mouse.click(20, 20)
        except Exception:
            pass
        _time.sleep(0.6)


def _set_depart_date(page, target: _date_cls) -> None:
    if _depart_date_matches(page, target):
        return
    _open_date_picker(page)
    _time.sleep(1.5)  # picker hydration 추가 대기
    # picker 열린 직후 상태 진단 — TD/SPAN 카운트와 첫 td 의 bounding rect
    try:
        diag = page.evaluate("(() => { " + _JS_WALK + r"""
          const a=[]; _walk(document, 0, a);
          const spans = a.filter(e => e.tagName === 'SPAN'
              && (e.className||'').toString().includes('ui-datepicker__td-date'));
          let first = null;
          if (spans.length) {
            const s = spans[0];
            const r = s.getBoundingClientRect();
            first = {text: (s.innerText||'').trim(), x: r.x, y: r.y, w: r.width, h: r.height};
          }
          return {span_count: spans.length, first_span: first, url: location.href};
        })()""")
        LOGGER.info("warm-up: date picker DOM diag = %s", diag)
    except Exception as e:
        LOGGER.debug("date picker diag err: %s", e)
    try:
        page.screenshot(path="runs/warmup_date_picker_state.png", full_page=False)
    except Exception:
        pass
    for attempt in range(4):
        r = _pick_day_in_month(page, target.year, target.month, target.day)
        LOGGER.info("warm-up: date click attempt %d -> %s", attempt, r)
        _time.sleep(1.5)
        # 첫 -start 잡힌 시점에 스크린샷 + 버튼 dump (진단용)
        if isinstance(r, dict) and "-start" in (r.get("cls") or ""):
            if attempt <= 1:
                try:
                    page.screenshot(path=f"runs/warmup_date_open_a{attempt}.png", full_page=False)
                except Exception:
                    pass
                btns = _date_dialog_buttons(page)
                LOGGER.info("warm-up: date dialog buttons (open) = %s", btns)
            _close_date_dialog(page)
        if _depart_date_matches(page, target):
            return
        if not _is_date_picker_open(page):
            _open_date_picker(page)
    try:
        page.screenshot(path="runs/warmup_date_fail.png", full_page=False)
    except Exception:
        pass
    cur = (_widget_button(page, "date") or {}).get("t")
    raise LoginError(
        f"warm-up: 출발일 {target.isoformat()} 선택 실패 (현재='{cur}', "
        f"스크린샷=runs/warmup_date_fail.png)"
    )


def _find_search_button(page) -> Optional[Dict]:
    return page.evaluate("(() => { " + _JS_WALK + r"""
      const a=[]; _walk(document, 0, a);
      for (const el of a) {
        if (el.tagName !== 'BUTTON') continue;
        if ((el.innerText||'').trim() !== '항공편 검색') continue;
        const r = el.getBoundingClientRect();
        return {x: r.x + r.width/2, y: r.y + r.height/2,
                disabled: !!el.disabled, w: r.width};
      }
      return null;
    })()""")


def _wait_select_flight(page, timeout_s: float = 25.0) -> None:
    deadline = _time.time() + timeout_s
    while _time.time() < deadline:
        url = page.url or ""
        if "/booking/select-flight" in url:
            # 추가로 flight-list DOM hydration 잠깐 대기 (안 잡혀도 진행)
            for _ in range(20):
                try:
                    if page.evaluate(
                        "!!document.querySelector('[class*=flight-list], "
                        "[class*=FlightList], [data-testid*=flight]')"
                    ):
                        return
                except Exception:
                    pass
                _time.sleep(0.5)
            return
        _time.sleep(0.5)
    raise LoginError(f"warm-up: select-flight 진입 실패 (url={page.url!r})")


def warm_up_select_flight(client: KoreanAirSPAClient, cfg: AirConfig) -> None:
    """위젯 클릭 경로로 select-flight 페이지에 진입해 Akamai 세션 확보.

    Akamai 는 /booking/select-flight 직접 navigate 를 / 로 redirect 한다.
    홈 위젯에서 trip/origin/dest/date 채우고 '항공편 검색' 버튼을 클릭해야만
    정상 세션이 잡히고, 이후 air-bounds XHR 가 200 을 반환한다.

    Idempotent — 이미 select-flight 페이지에 있고 origin/dest/date 가 cfg 와
    일치하면 즉시 return.
    """
    if cfg.air_trip_type != "oneway":
        # TODO: roundtrip warm-up — date picker 에서 시작일 클릭 후 종료일도 클릭.
        raise NotImplementedError(
            "warm-up: roundtrip 미구현 — AIR_TRIP_TYPE=oneway 로 운영하거나, "
            "수동으로 select-flight 까지 진입한 뒤 워처 기동"
        )

    page = client.page
    _set_viewport(page)

    url = page.url or ""
    depart_str = cfg.air_depart_date.strftime("%Y%m%d")
    if ("/booking/select-flight" in url
            and f"origin={cfg.air_origin}" in url
            and f"destination={cfg.air_dest}" in url
            and f"departureDate={depart_str}" in url):
        LOGGER.info("warm-up: 이미 select-flight 페이지 (%s)", url)
        return

    LOGGER.info("warm-up: 홈 위젯 진입")
    _ensure_home(page)

    LOGGER.info("warm-up: trip_type=%s", cfg.air_trip_type)
    _ensure_trip_type(page, cfg.air_trip_type)

    LOGGER.info("warm-up: origin=%s", cfg.air_origin)
    _set_airport(page, "origin", cfg.air_origin)

    LOGGER.info("warm-up: dest=%s", cfg.air_dest)
    _set_airport(page, "dest", cfg.air_dest)

    LOGGER.info("warm-up: depart_date=%s", cfg.air_depart_date.isoformat())
    _set_depart_date(page, cfg.air_depart_date)

    LOGGER.info("warm-up: '항공편 검색' 클릭")
    sb = _find_search_button(page)
    if not sb:
        raise LoginError("warm-up: '항공편 검색' button 못 찾음")
    if sb.get("disabled"):
        LOGGER.warning("warm-up: 검색 버튼 disabled — 그대로 클릭 시도")
    page.mouse.click(sb["x"], sb["y"])

    _wait_select_flight(page)
    LOGGER.info("warm-up: select-flight 진입 완료 (%s)", page.url)


def attempt_reservation(client: KoreanAirSPAClient, cfg: AirConfig, candidate: Dict) -> None:
    raise NotImplementedError(
        "KE 예약 단계 자동화 미구현 — search 모드로만 모니터링 가능."
    )


__all__ = ["ensure_logged_in", "warm_up_select_flight", "attempt_reservation"]
