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

from ..config import KoreanAirConfig
from . import LoginError
from .client import KoreanAirSPAClient

LOGGER = logging.getLogger("korean_air_watcher.koreanair.reserve")


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


def ensure_logged_in(client: KoreanAirSPAClient, cfg: KoreanAirConfig) -> None:
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

    if not cfg.korean_air_user or not cfg.korean_air_pass:
        raise LoginError("KOREAN_AIR_USER / KOREAN_AIR_PASS 비어 있음 — .env 확인")

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

    if not _set_input_value(page, "text", cfg.korean_air_user):
        raise LoginError("ID 필드 입력 실패")
    _time.sleep(0.3)
    if not _set_input_value(page, "password", cfg.korean_air_pass):
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
    # SPA 가 home goto 를 가로채는 경우(대기예약 등 다른 경로에 갇힘) about:blank 로
    # 컨텍스트 깨고 cache-bust 쿼리로 다시 들어간다.
    try:
        cur = page.evaluate("location.href")
    except Exception:
        cur = page.url
    LOGGER.info("warm-up: home fresh navigate (url=%s)", cur)
    try:
        page.goto("about:blank", wait_until="domcontentloaded", timeout=8_000)
    except Exception as e:
        LOGGER.debug("warm-up: about:blank 실패: %s", e)
    try:
        page.goto(f"https://www.koreanair.com/?_t={int(_time.time())}",
                  wait_until="domcontentloaded", timeout=30_000)
    except PWTimeoutError:
        LOGGER.warning("warm-up: home goto timeout — 계속 진행")
    deadline = _time.time() + 15.0
    while _time.time() < deadline:
        try:
            if page.evaluate("!!document.querySelector(\"input[id='chip-2']\")"):
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
    """DOM 에 cell 만 있어도 0×0 면 닫힌 것 → 적어도 하나가 visible 한지 확인."""
    try:
        return bool(page.evaluate("(() => { " + _JS_WALK + r"""
          const a=[]; _walk(document, 0, a);
          for (const el of a) {
            if (el.tagName !== 'SPAN') continue;
            if (!(el.className||'').toString().includes('ui-datepicker__td-date')) continue;
            const r = el.getBoundingClientRect();
            if (r.width > 0 && r.height > 0) return true;
          }
          return false;
        })()"""))
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
    # KE 위젯은 "05월 29일 (금)" / "5월 29일" / "05.29" 등 표기가 다양 — 정규식으로
    # month·day 숫자만 추출해서 비교.
    import re as _re
    m = _re.search(r"(\d{1,2})\s*월\s*(\d{1,2})\s*일", t)
    if m:
        return int(m.group(1)) == target.month and int(m.group(2)) == target.day
    m = _re.search(r"(\d{1,2})[.\-/](\d{1,2})", t)
    if m:
        return int(m.group(1)) == target.month and int(m.group(2)) == target.day
    m = _re.search(r"(\d{4})-(\d{2})-(\d{2})", t)
    if m:
        return (int(m.group(1)) == target.year
                and int(m.group(2)) == target.month
                and int(m.group(3)) == target.day)
    return False


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


def _ensure_fare_type(page, fare_type: str) -> None:
    """홈 위젯의 cash/miles 탭 전환. chip-X 에 fare-type 가 없으므로 텍스트 매칭 button/link
    을 찾아 클릭한다 — '일반 예매' (cash) / '마일리지 예매' (miles).

    fare_type='both' 면 별도 처리 안 함.
    """
    if fare_type not in ("cash", "miles"):
        return
    # 홈 위젯 fare 탭 = KDS-SWITCH (`label-start='예매'`, `label-end='마일리지 예매'`).
    # 검증된 매핑 (URL 결과 기준): is-checked='true' → "예매"(cash) / 'false' → "마일리지 예매"(miles).
    want_checked = "true" if fare_type == "cash" else "false"
    for attempt in range(4):
        info = page.evaluate(
            "(() => { " + _JS_WALK + r"""
              const a=[]; _walk(document, 0, a);
              for (const el of a) {
                if (el.tagName !== 'KDS-SWITCH') continue;
                if ((el.getAttribute('label-start') || '') !== '예매') continue;
                const r = el.getBoundingClientRect();
                if (r.width < 50) continue;
                // 내부 KDS-SWITCH_1 (실제 toggle host) 에서 is-checked 읽기
                let host = null;
                for (const c of el.querySelectorAll('*')) {
                  if (c.tagName === 'KDS-SWITCH_1') { host = c; break; }
                }
                const checked = host ? host.getAttribute('is-checked') : null;
                // start/end SPAN 좌표
                let startX = r.x + r.width * 0.25;
                let endX   = r.x + r.width * 0.75;
                for (const c of el.querySelectorAll('span')) {
                  const t = (c.innerText || '').trim();
                  const cr = c.getBoundingClientRect();
                  if (t === '예매') startX = cr.x + cr.width / 2;
                  if (t === '마일리지 예매') endX = cr.x + cr.width / 2;
                }
                return {checked, startX, endX, y: r.y + r.height / 2, w: r.width};
              }
              return null;
            })()"""
        )
        LOGGER.info("warm-up: fare switch info = %s", info)
        if not info:
            _time.sleep(0.6); continue
        if info.get("checked") == want_checked:
            # 토글 직후 KE 가 navigation/페이지 갱신을 트리거할 수 있어 안정화 대기.
            try:
                page.wait_for_load_state("domcontentloaded", timeout=8_000)
            except Exception:
                pass
            _time.sleep(2.0)
            return
        target_x = info["startX"] if fare_type == "cash" else info["endX"]
        try:
            page.mouse.click(target_x, info["y"])
        except Exception as e:
            LOGGER.debug("fare switch click err: %s", e)
        _time.sleep(1.0)
    LOGGER.warning(
        "warm-up: fare switch 토글 실패 (현재 = %s, 원함 is-checked=%s) — 기본값으로 진행",
        info if info else "?", want_checked,
    )
    return  # 이하 레거시 경로는 사용 안 함
    # 두 키워드의 우선 순위 — 'cash' 면 '일반' 포함하되 '마일리지' 포함 안 함, 반대 동일.
    want_kw = "예매" if fare_type == "cash" else "마일리지"
    avoid_kw = "마일리지" if fare_type == "cash" else ""
    for attempt in range(3):
        info = page.evaluate(
            "([want, avoid]) => { " + _JS_WALK + r"""
              const a=[]; _walk(document, 0, a);
              // 후보: button / a / [role=tab] 중 텍스트 매칭
              const cands = [];
              for (const el of a) {
                const tag = el.tagName;
                const role = el.getAttribute ? (el.getAttribute('role') || '') : '';
                if (tag !== 'BUTTON' && tag !== 'A' && role !== 'tab') continue;
                const t = (el.innerText||'').replace(/\s+/g,' ').trim();
                if (!t || t.length > 30) continue;
                if (!t.includes(want)) continue;
                if (avoid && t.includes(avoid)) continue;
                const r = el.getBoundingClientRect();
                if (r.width <= 0 || r.height <= 0) continue;
                // 페이지 상단(헤더 nav 위) 의 것 — '예매' 키워드 들어가야
                cands.push({el, t, x: r.x + r.width/2, y: r.y + r.height/2,
                            ariaSel: el.getAttribute ? el.getAttribute('aria-selected') : null,
                            cls: (el.className||'').toString().slice(0, 50)});
              }
              if (!cands.length) return null;
              // 가장 윗쪽 (y 최소) 것이 fare-type 탭일 가능성 큼
              cands.sort((a, b) => a.y - b.y);
              const c = cands[0];
              return {t: c.t, x: c.x, y: c.y, ariaSel: c.ariaSel, cls: c.cls};
            }""",
            [want_kw, avoid_kw],
        )
        LOGGER.info("warm-up: fare tab info = %s", info)
        if not info:
            _time.sleep(0.8); continue
        # 이미 선택돼 있으면(aria-selected=true) skip
        if info.get("ariaSel") == "true":
            return
        page.mouse.click(info["x"], info["y"])
        _time.sleep(1.5)
        # 페이지 reload 됐을 수도 있어 chip-2 가 다시 나타날 때까지 대기
        deadline = _time.time() + 8.0
        while _time.time() < deadline:
            try:
                if page.evaluate("!!document.querySelector(\"input[id='chip-2']\")"):
                    break
            except Exception:
                pass
            _time.sleep(0.3)
        return
    # 탭 못 찾으면 — 홈 페이지에 visible 한 fare-type 탭이 없는 경우. 검색 결과 페이지에서
    # 확인. 기본값(보통 cash) 으로 진행.
    LOGGER.warning("warm-up: fare_type=%s 탭 못 찾음 — 기본값으로 진행", fare_type)


def _ensure_oneway_in_picker(page) -> None:
    """picker 안의 '편도' ui-switch 탭이 -selected 가 아니면 클릭해서 oneway 모드로 전환.

    picker 의 ui-switch 가 진짜 trip-type 컨트롤. chip-X 는 hidden radio 라 click 해도
    시각/세션 상태엔 반영 안 됨. picker 가 열려야만 ui-switch 가 보임.
    """
    for attempt in range(3):
        info = page.evaluate("(() => { " + _JS_WALK + r"""
          const a=[]; _walk(document, 0, a);
          // 'ui-switch' 클래스를 가진 button 들을 위치 순으로 수집 (왕복=0번, 편도=1번)
          const switches = [];
          for (const el of a) {
            if (el.tagName !== 'BUTTON') continue;
            const cls = (el.className||'').toString();
            if (!/(^|\s)ui-switch(\s|$|-)/.test(cls)) continue;
            const r = el.getBoundingClientRect();
            if (r.width <= 0 || r.height <= 0) continue;
            switches.push({el, x: r.x, y: r.y, w: r.width, h: r.height,
                           selected: cls.includes('-selected')});
          }
          switches.sort((a, b) => a.x - b.x);
          // 편도 = 두 번째 ui-switch (왕복이 첫 번째). 가독성을 위해 picker-row 의 ui-switch 만.
          if (switches.length < 2) return {found: false, count: switches.length};
          const oneway = switches[1];
          if (oneway.selected) return {found: true, already: true};
          return {found: true, already: false,
                  x: oneway.x + oneway.w/2, y: oneway.y + oneway.h/2};
        })()""")
        LOGGER.info("warm-up: picker oneway switch info = %s", info)
        if not info or not info.get("found"):
            _time.sleep(1.0); continue
        if info.get("already"):
            return
        page.mouse.click(info["x"], info["y"])
        _time.sleep(1.2)
        # picker 가 재렌더 / 닫힐 수도 있음. 닫혔으면 다시 열기.
        if not _is_date_picker_open(page):
            _open_date_picker(page)
            _time.sleep(1.0)
    raise LoginError("warm-up: picker 안 '편도' 탭 활성화 실패")


def _close_picker_via_close_button(page) -> None:
    """picker overlay 의 X close 버튼을 찾아 클릭. 못 찾으면 viewport 우상단 안전지대 click.

    Escape 는 selection 을 discard 시키므로 절대 호출하지 않는다.
    """
    if not _is_date_picker_open(page):
        return
    closed = False
    try:
        info = page.evaluate("(() => { " + _JS_WALK + r"""
          const a=[]; _walk(document, 0, a);
          // .ui-datepicker 가 들어있는 popover 컨테이너 → 그 안의 close 류 button 찾기
          let host = null;
          for (const el of a) {
            const cls = (el.className||'').toString();
            if (cls.includes('ui-datepicker') && el.parentElement) {
              // popover 컨테이너로 거슬러 올라가기 (보통 2~5 레벨)
              let p = el;
              for (let i=0; i<6; i++) {
                if (!p) break;
                const pcls = (p.className||'').toString();
                if (pcls.match(/popover|modal|dialog|layer|overlay/i)) { host = p; break; }
                p = p.parentElement;
              }
              if (host) break;
            }
          }
          // host 못 찾으면 .ui-datepicker 자체 element
          if (!host) {
            for (const el of a) {
              if ((el.className||'').toString().match(/ui-datepicker(?!__)/)) { host = el; break; }
            }
          }
          if (!host) return null;
          // host 안에서 'close' 류 button 찾기
          const btns = host.querySelectorAll('button');
          for (const b of btns) {
            const t = (b.innerText||'').trim();
            const aria = (b.getAttribute('aria-label') || '').trim();
            const cls = (b.className||'').toString();
            if (/닫기|close/i.test(aria + ' ' + cls) || t === 'X' || t === '×') {
              const r = b.getBoundingClientRect();
              if (r.width > 0 && r.height > 0) {
                return {x: r.x + r.width/2, y: r.y + r.height/2,
                        aria, t, cls: cls.slice(0, 60)};
              }
            }
          }
          return null;
        })()""")
        if info:
            LOGGER.debug("warm-up: picker close btn=%s", info)
            page.mouse.click(info["x"], info["y"])
            _time.sleep(1.0)
            closed = not _is_date_picker_open(page)
    except Exception as e:
        LOGGER.debug("close button find err: %s", e)
    if not closed and _is_date_picker_open(page):
        # X 못 찾았으면 viewport 우상단 안전지대 click (header navigation 회피)
        try:
            page.mouse.click(1900, 50)
        except Exception:
            try:
                page.mouse.click(20, 20)
            except Exception:
                pass
        _time.sleep(1.0)


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
    """date picker 를 열고 oneway 탭 + day cell 선택. picker 는 '항공편 검색' 클릭 시점에
    commit 되므로 widget button 텍스트로 검증하지 않고 cell 의 -start 클래스로만 확인."""
    _open_date_picker(page)
    _time.sleep(1.5)  # picker hydration
    _ensure_oneway_in_picker(page)
    for attempt in range(4):
        r = _pick_day_in_month(page, target.year, target.month, target.day)
        LOGGER.info("warm-up: date click attempt %d -> %s", attempt, r)
        _time.sleep(1.2)
        if isinstance(r, dict) and "-start" in (r.get("cls") or ""):
            LOGGER.info("warm-up: date cell %s 선택 (picker 내부 state) — 검색 클릭 시 commit",
                        target.isoformat())
            return
        if not _is_date_picker_open(page):
            _open_date_picker(page)
            _ensure_oneway_in_picker(page)
    try:
        page.screenshot(path="runs/warmup_date_fail.png", full_page=False)
    except Exception:
        pass
    raise LoginError(
        f"warm-up: 출발일 {target.isoformat()} cell 선택 실패 (-start 클래스 미반영, "
        f"스크린샷=runs/warmup_date_fail.png)"
    )


def _find_search_button(page) -> Optional[Dict]:
    """'항공편 검색' button 위치. picker 가 열려 있으면 CTA 가 innerText 비어있을 수 있어
    aria-label / class 로 fallback."""
    return page.evaluate("(() => { " + _JS_WALK + r"""
      const a=[]; _walk(document, 0, a);
      // 1. text === '항공편 검색'
      for (const el of a) {
        if (el.tagName !== 'BUTTON') continue;
        if ((el.innerText||'').trim() !== '항공편 검색') continue;
        const r = el.getBoundingClientRect();
        if (r.width <= 0 || r.height <= 0) continue;
        return {via: 'text', x: r.x + r.width/2, y: r.y + r.height/2,
                disabled: !!el.disabled, w: r.width};
      }
      // 2. aria-label 에 '항공편 검색'
      for (const el of a) {
        if (el.tagName !== 'BUTTON') continue;
        const aria = el.getAttribute('aria-label') || '';
        if (!aria.includes('항공편 검색')) continue;
        const r = el.getBoundingClientRect();
        if (r.width <= 0 || r.height <= 0) continue;
        return {via: 'aria', x: r.x + r.width/2, y: r.y + r.height/2,
                disabled: !!el.disabled, w: r.width};
      }
      // 3. picker 영역의 CTA: ui-button -basic -cta 클래스. picker booking-tool row 와
      // 같은 y(±30) 의 button 중 cta 클래스.
      let toolY = null;
      for (const el of a) {
        if (el.tagName !== 'BUTTON') continue;
        const cls = (el.className||'').toString();
        if (!cls.includes('ui-booking-tool__button')) continue;
        const r = el.getBoundingClientRect();
        if (r.width > 0 && r.height > 0) { toolY = r.y; break; }
      }
      if (toolY === null) return null;
      for (const el of a) {
        if (el.tagName !== 'BUTTON') continue;
        const cls = (el.className||'').toString();
        if (!cls.includes('ui-button') || !cls.includes('-cta')) continue;
        const r = el.getBoundingClientRect();
        if (r.width <= 0 || r.height <= 0) continue;
        if (Math.abs(r.y - toolY) > 30) continue;
        return {via: 'cta', x: r.x + r.width/2, y: r.y + r.height/2,
                disabled: !!el.disabled, w: r.width};
      }
      return null;
    })()""")


def _wait_select_flight(page, cfg: KoreanAirConfig, timeout_s: float = 25.0) -> None:
    """cash → /booking/select-flight, miles → /booking/select-award-flight 진입 대기.

    page.url 외에도 JS `location.href` 와 context 의 다른 page 도 확인 — KE 가 새 탭/iframe
    으로 결과를 띄울 가능성 대비.
    """
    want_paths = ["/booking/select-flight", "/booking/select-award-flight"]
    primary = ("/booking/select-award-flight" if cfg.korean_air_fare_type == "miles"
               else "/booking/select-flight")
    ctx = page.context
    deadline = _time.time() + timeout_s
    while _time.time() < deadline:
        try:
            js_url = page.evaluate("location.href")
        except Exception:
            js_url = None
        page_url = page.url or ""
        all_urls = [p.url for p in (ctx.pages if ctx else [])]
        if any(p in (js_url or "") for p in want_paths) \
                or any(p in page_url for p in want_paths) \
                or any(any(p in u for p in want_paths) for u in all_urls):
            actual = js_url or page_url
            if primary not in actual and primary not in ",".join(all_urls):
                LOGGER.warning("warm-up: 의도된 fare_type=%s(%s) 가 아닌 페이지 진입 — actual=%s, ctx_pages=%s",
                               cfg.korean_air_fare_type, primary, actual, all_urls)
            # flight-list DOM 잠깐 대기
            for _ in range(20):
                try:
                    if page.evaluate(
                        "!!document.querySelector('[class*=flight-list], "
                        "[class*=FlightList], [data-testid*=flight], [class*=flight-card]')"
                    ):
                        return
                except Exception:
                    pass
                _time.sleep(0.5)
            return
        _time.sleep(0.5)
    raise LoginError(
        f"warm-up: select-flight 진입 실패 "
        f"(page.url={page_url!r}, js_url={js_url!r}, ctx_pages={all_urls})"
    )


def warm_up_select_flight(client: KoreanAirSPAClient, cfg: KoreanAirConfig, *,
                            force: bool = False) -> None:
    """위젯 클릭 경로로 select-flight 페이지에 진입해 Akamai 세션 확보.

    Akamai 는 /booking/select-flight 직접 navigate 를 / 로 redirect 한다.
    홈 위젯에서 trip/origin/dest/date 채우고 '항공편 검색' 버튼을 클릭해야만
    정상 세션이 잡히고, 이후 air-bounds XHR 가 200 을 반환한다.

    Idempotent — 이미 select-flight 페이지에 있고 origin/dest/date 가 cfg 와
    일치하면 즉시 return. `force=True` 면 그 가드를 건너뛰고 무조건 home →
    위젯 단계까지 다시 실행 (roundtrip return leg 등 origin/dest 가 바뀌었을 때).
    """
    if cfg.korean_air_trip_type != "oneway":
        # TODO: roundtrip warm-up — date picker 에서 시작일 클릭 후 종료일도 클릭.
        raise NotImplementedError(
            "warm-up: roundtrip 미구현 — KOREAN_AIR_TRIP_TYPE=oneway 로 운영하거나, "
            "수동으로 select-flight 까지 진입한 뒤 워처 기동"
        )

    page = client.page
    _set_viewport(page)

    try:
        url = page.evaluate("location.href") or ""
    except Exception:
        url = page.url or ""
    depart_str = cfg.korean_air_depart_date.strftime("%Y%m%d")
    want_path = ("/booking/select-award-flight" if cfg.korean_air_fare_type == "miles"
                 else "/booking/select-flight")
    if not force and want_path in url:
        LOGGER.info("warm-up: 이미 select-flight 페이지 (%s)", url)
        return
    if force:
        LOGGER.info("warm-up: force=True — 위젯 재셋업 (현재 url=%s)", url)
    # 보너스 대기예약 페이지(select-award-wait-flight) 도 검색 결과 컨텍스트와 동치 —
    # reload 만으로 select-award-flight 로 복귀 시도. 실패해도 home navigate 로 빠짐.
    if "/booking/select-award-wait-flight" in url or "/booking/wait-flight" in url:
        LOGGER.info("warm-up: 대기예약 페이지 (%s) — reload 로 검색 결과 복귀 시도", url)
        try:
            page.reload(wait_until="domcontentloaded", timeout=20_000)
            new_url = page.evaluate("location.href") or url
            if want_path in new_url:
                LOGGER.info("warm-up: reload 후 검색 결과 페이지 (%s)", new_url)
                return
        except Exception as e:
            LOGGER.warning("warm-up: 대기예약 reload 실패: %s", e)

    LOGGER.info("warm-up: 홈 위젯 진입")
    _ensure_home(page)

    # 홈 위젯의 chip-X 인풋들을 dump 해서 어느 게 cash/miles 인지 식별 (진단용)
    try:
        chips = page.evaluate("(() => { " + _JS_WALK + r"""
          const a=[]; _walk(document, 0, a);
          const out = [];
          for (const el of a) {
            if (el.tagName !== 'INPUT') continue;
            const id = el.id || '';
            if (!/^chip-\d+$/.test(id)) continue;
            const lbl = document.querySelector(`label[for='${id}']`);
            out.push({
              id, type: el.type, checked: el.checked,
              label: lbl ? (lbl.innerText||'').replace(/\s+/g,' ').trim().slice(0,30) : null,
            });
          }
          return out;
        })()""")
        LOGGER.info("warm-up: chip inputs = %s", chips)
    except Exception as e:
        LOGGER.debug("chip dump err: %s", e)

    # cash/miles 탭 전환 — label 텍스트로 식별
    LOGGER.info("warm-up: fare_type=%s", cfg.korean_air_fare_type)
    _ensure_fare_type(page, cfg.korean_air_fare_type)

    # 참고: chip-X 인풋은 hidden radio 라 click 해도 시각/세션 상태에 반영 안 됨.
    # 실제 trip-type 컨트롤은 date picker 가 열렸을 때 보이는 ui-switch 탭이다.
    # _set_depart_date 안에서 _ensure_oneway_in_picker 로 처리한다.

    LOGGER.info("warm-up: origin=%s", cfg.korean_air_origin)
    _set_airport(page, "origin", cfg.korean_air_origin)

    LOGGER.info("warm-up: dest=%s", cfg.korean_air_dest)
    _set_airport(page, "dest", cfg.korean_air_dest)

    LOGGER.info("warm-up: depart_date=%s", cfg.korean_air_depart_date.isoformat())
    _set_depart_date(page, cfg.korean_air_depart_date)

    LOGGER.info("warm-up: '항공편 검색' 클릭")
    sb = _find_search_button(page)
    LOGGER.info("warm-up: search btn = %s", sb)
    if not sb:
        try:
            page.screenshot(path="runs/warmup_no_search_btn.png", full_page=False)
        except Exception:
            pass
        raise LoginError("warm-up: '항공편 검색' button 못 찾음 (스크린샷=runs/warmup_no_search_btn.png)")
    if sb.get("disabled"):
        LOGGER.warning("warm-up: 검색 버튼 disabled — 그대로 클릭 시도")
    page.mouse.click(sb["x"], sb["y"])

    try:
        _wait_select_flight(page, cfg)
    except LoginError:
        try:
            page.screenshot(path="runs/warmup_no_navigate.png", full_page=False)
        except Exception:
            pass
        raise
    LOGGER.info("warm-up: select-flight 진입 완료 (%s)", page.url)


def attempt_reservation(client: KoreanAirSPAClient, cfg: KoreanAirConfig, candidate: Dict) -> None:
    raise NotImplementedError(
        "KE 예약 단계 자동화 미구현 — search 모드로만 모니터링 가능."
    )


__all__ = ["ensure_logged_in", "warm_up_select_flight", "attempt_reservation"]
