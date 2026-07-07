from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Dict, Optional

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError
from playwright._impl._errors import Error as PlaywrightError

from ..config import SRTConfig
from ..utils import timestamped_path
from .client import SRTClient, dump_artifacts, safe_click, safe_goto, _attach_popup_guard
from .search import SEARCH_URL
from . import selectors

LOGGER = logging.getLogger("srt_watcher.srt.reserve")

LOGIN_URL = "https://etk.srail.kr/cmc/01/selectLoginForm.do?pageId=TK0701000000"

QUEUE_POLL_INTERVAL = float(os.getenv("SRT_QUEUE_POLL_SEC", "0.5"))
QUEUE_WAIT_TIMEOUT  = float(os.getenv("SRT_QUEUE_TIMEOUT_SEC", "180"))
QUEUE_REFRESH_LIMIT = int(os.getenv("SRT_QUEUE_REFRESH_LIMIT", "2"))
POST_CLICK_SETTLE   = float(os.getenv("SRT_POST_CLICK_SETTLE", "0.3"))

# 로그인 검증 캐시 — 최근 확인된 로그인 상태를 재사용
_last_login_verified: float = 0.0
_LOGIN_CACHE_TTL: float = 300.0  # 5분 이내 재확인 생략 (쿠키 체크가 1차 검증)


# ========== 강화된 JavaScript 입력 ==========

def _fill_input_with_js(page: Page, selector: str, value: str, field_type: str = "text") -> bool:
    """
    강화된 JavaScript 입력 함수
    - visible 체크 제거 (JavaScript에서 직접 처리)
    - 더 많은 이벤트 트리거
    - 상세한 에러 로깅
    """
    try:
        result = page.evaluate("""(args) => {
            const selector = args.selector;
            const value = args.value;
            const fieldType = args.fieldType;
            
            const element = document.querySelector(selector);
            
            if (!element) {
                return {
                    success: false, 
                    error: 'Element not found',
                    selector: selector
                };
            }
            
            // 요소 정보 수집
            const info = {
                tagName: element.tagName,
                type: element.type,
                id: element.id,
                name: element.name,
                disabled: element.disabled,
                readOnly: element.readOnly,
                style: element.style.display
            };
            
            // disabled 체크
            if (element.disabled) {
                return {
                    success: false,
                    error: 'Element is disabled',
                    info: info
                };
            }
            
            // 포커스
            try {
                element.focus();
            } catch(e) {
                // focus 실패해도 계속
            }
            
            // 값 클리어
            element.value = '';
            
            // 값 설정
            element.value = value;
            
            // 모든 이벤트 트리거 (순서 중요!)
            const events = [
                new Event('input', { bubbles: true, cancelable: true }),
                new Event('change', { bubbles: true, cancelable: true }),
                new KeyboardEvent('keydown', { bubbles: true, cancelable: true, key: 'Enter' }),
                new KeyboardEvent('keypress', { bubbles: true, cancelable: true, key: 'Enter' }),
                new KeyboardEvent('keyup', { bubbles: true, cancelable: true, key: 'Enter' }),
                new Event('blur', { bubbles: true, cancelable: true })
            ];
            
            events.forEach(event => {
                try {
                    element.dispatchEvent(event);
                } catch(e) {
                    // 이벤트 실패해도 계속
                }
            });
            
            // onchange, onkeyup 직접 호출
            try {
                if (element.onchange) {
                    element.onchange({ target: element, type: 'change' });
                }
            } catch(e) {}
            
            try {
                if (element.onkeyup) {
                    element.onkeyup({ target: element, type: 'keyup' });
                }
            } catch(e) {}
            
            try {
                if (element.oninput) {
                    element.oninput({ target: element, type: 'input' });
                }
            } catch(e) {}
            
            // 최종 값 확인
            const finalValue = element.value;
            
            return {
                success: true,
                finalValue: finalValue,
                expectedValue: value,
                matched: finalValue === value,
                info: info
            };
            
        }""", {"selector": selector, "value": value, "fieldType": field_type})
        
        if not result:
            LOGGER.error(f"JS evaluate returned null for {selector}")
            return False
        
        if not result.get('success'):
            error = result.get('error', 'Unknown error')
            info = result.get('info', {})
            LOGGER.error(
                f"JS input failed: {selector} - {error}\n"
                f"  Element info: {info}"
            )
            return False
        
        final_val = result.get('finalValue', '')
        expected_val = result.get('expectedValue', '')
        matched = result.get('matched', False)
        
        if field_type == 'password':
            # 비밀번호는 값 표시 안 함
            LOGGER.info(
                f"JS input success: {selector} (password) "
                f"matched={matched}"
            )
        else:
            LOGGER.info(
                f"JS input success: {selector} = '{expected_val}' "
                f"(final='{final_val}', matched={matched})"
            )
        
        return True
        
    except Exception as e:
        LOGGER.error(f"JS input exception: {selector} - {type(e).__name__}: {e}")
        import traceback
        LOGGER.debug(traceback.format_exc())
        return False


# ========== NetFunnel 처리 ==========

def _wait_for_netfunnel_key(page: Page, timeout_sec: float = 30.0) -> Optional[str]:
    """NetFunnel key 대기"""
    LOGGER.info("Waiting for NetFunnel key...")
    
    end_time = time.time() + timeout_sec
    while time.time() < end_time:
        try:
            key = page.evaluate("""() => {
                try {
                    const keyInput = document.querySelector('input[name="key"]');
                    if (keyInput && keyInput.value) {
                        return keyInput.value;
                    }
                    
                    if (window.netfunnelKey) {
                        return window.netfunnelKey;
                    }
                    
                    return null;
                } catch(e) {
                    return null;
                }
            }""")
            
            if key:
                LOGGER.info("✓ NetFunnel key obtained: %s", key[:20] + "..." if len(key) > 20 else key)
                return key
                
        except Exception as e:
            LOGGER.debug("Error checking NetFunnel key: %s", e)
        
        time.sleep(0.5)
    
    LOGGER.warning("NetFunnel key not obtained within %s seconds", timeout_sec)
    return None


def _inject_netfunnel_handler(page: Page) -> None:
    """NetFunnel 이벤트 핸들러 주입"""
    try:
        page.evaluate("""() => {
            if (typeof NetFunnel_Action !== 'undefined' && !window._nf_wrapped) {
                const original = NetFunnel_Action;
                window.NetFunnel_Action = function(action, handlers) {
                    console.log('[NetFunnel] Action called:', action);
                    
                    if (handlers && handlers.success) {
                        const originalSuccess = handlers.success;
                        handlers.success = function(ev, ret) {
                            console.log('[NetFunnel] Success callback:', ret);
                            if (ret && ret.data && ret.data.key) {
                                window.netfunnelKey = ret.data.key;
                                console.log('[NetFunnel] Key stored:', ret.data.key);
                            }
                            return originalSuccess(ev, ret);
                        };
                    }
                    
                    return original(action, handlers);
                };
                window._nf_wrapped = true;
                console.log('[NetFunnel] Handler wrapper installed');
            }
        }""")
        LOGGER.debug("NetFunnel handler injected")
    except Exception as e:
        LOGGER.debug("Failed to inject NetFunnel handler: %s", e)


# ========== 로그인 상태 확인 ==========

def _is_logged_in(page: Page) -> bool:
    """로그인 상태 확인.

    0) 최근 캐시 — 60초 이내 검증 통과했으면 재확인 생략
    1) JSESSIONID 쿠키 존재 확인 (필수 조건)
    2) 로그인 페이지 감지 (회원번호 + 비밀번호 폼) → 즉시 False
    3) cfg.isLogin === true (JS 변수)
    4) 검색 결과 페이지 마커 (reservationAfterMsg)
    5) 서버 검증 (XHR)
    """
    global _last_login_verified

    # 0. 캐시 확인
    if time.monotonic() - _last_login_verified < _LOGIN_CACHE_TTL:
        LOGGER.debug("Login verified via cache (%.0fs ago)",
                      time.monotonic() - _last_login_verified)
        return True

    # 1. JSESSIONID_ETK 쿠키 확인 — 없으면 절대 로그인 상태가 아님
    try:
        cookies = page.context.cookies("https://etk.srail.kr")
        jsid = [c for c in cookies if c["name"] == "JSESSIONID_ETK"]
        if not jsid:
            LOGGER.info("Not logged in: no JSESSIONID_ETK cookie")
            return False
        LOGGER.debug("JSESSIONID_ETK present: %s...", jsid[0]["value"][:20])
    except Exception as e:
        LOGGER.debug("Cookie check failed: %s", e)

    try:
        html = page.content()
    except Exception as e:
        LOGGER.debug("Error getting page content: %s", e)
        return False

    # 2. 로그인 페이지 감지 — 반드시 HTML 마커 검사보다 먼저!
    #    로그인 페이지도 글로벌 템플릿에 "MY SRT"/"로그아웃" 등이 포함되어 있으므로
    #    로그인 폼 감지를 우선 수행해야 false positive 방지
    cur_url = page.url
    if "selectLoginForm" in cur_url or "TK0701000000" in cur_url:
        LOGGER.info("Not logged in: on login page URL")
        return False
    if "회원번호" in html and "비밀번호" in html:
        if 'id="srchDvCd"' in html or 'name="srchDvCd"' in html:
            LOGGER.info("Not logged in: login form detected (srchDvCd)")
            return False

    # 3. cfg.isLogin JS 변수
    try:
        is_login_js = page.evaluate("""() => {
            try {
                return window.cfg && window.cfg.isLogin === true;
            } catch(e) {
                return null;
            }
        }""")
        if is_login_js is True:
            LOGGER.debug("Login verified via cfg.isLogin=true")
            _last_login_verified = time.monotonic()
            return True
    except Exception:
        pass

    # 4. 검색 결과 페이지 (dynaPath) — 예약 관련 JS가 있으면 로그인 상태
    is_dynapath = "dynaPath" in cur_url or "pageId=TK0101011000" in cur_url
    if is_dynapath:
        if "reservationAfterMsg" in html:
            LOGGER.info("Login verified via reservationAfterMsg in results page")
            _last_login_verified = time.monotonic()
            return True
        LOGGER.warning("On dynaPath but no reservation markers")
        return False

    # 5. 서버 검증 (XHR) — etk.srail.kr 페이지에서만 동작
    if "etk.srail.kr" in cur_url:
        try:
            result = page.evaluate("""() => {
                try {
                    const xhr = new XMLHttpRequest();
                    xhr.open('GET', 'https://etk.srail.kr/cmc/01/selectMyInfo.do?pageId=TK0501000000', false);
                    xhr.send();
                    const resp = xhr.responseText || '';
                    if (resp.indexOf('selectLoginForm') !== -1) return 'login_page';
                    if (resp.indexOf('회원번호') !== -1 && resp.indexOf('비밀번호') !== -1) return 'login_page';
                    if (resp.indexOf('회원정보') !== -1 || resp.indexOf('마이페이지') !== -1) return 'logged_in';
                    if (resp.indexOf('MY SRT') !== -1 || resp.indexOf('로그아웃') !== -1) return 'logged_in';
                    return 'unknown:' + resp.substring(0, 200);
                } catch(e) {
                    return 'error:' + e.message;
                }
            }""")
            LOGGER.info("Server login check result: %s", str(result)[:200])
            if result == 'logged_in':
                _last_login_verified = time.monotonic()
                return True
            if result == 'login_page':
                return False
        except Exception as e:
            LOGGER.debug("Server login check failed: %s", e)

    LOGGER.info("Login status uncertain → not logged in")
    return False


def _get_credentials(config: SRTConfig) -> tuple[str, str]:
    """계정 정보 가져오기"""
    user = (
        os.getenv("SRT_USER")
        or getattr(config, "SRT_USER", None)
        or getattr(config, "srt_user", None)
        or getattr(config, "user", None)
    )
    pw = (
        os.getenv("SRT_PASS")
        or getattr(config, "SRT_PASS", None)
        or getattr(config, "srt_pass", None)
        or getattr(config, "password", None)
    )
    if not user or not pw:
        raise RuntimeError("SRT_USER / SRT_PASS is not configured")
    return str(user), str(pw)


def _fill_login_form(page: Page, user: str, pw: str) -> None:
    """
    로그인 폼 입력 (강화된 JavaScript 방식)
    - visible 체크 제거
    - 모든 후보 셀렉터 시도
    - 상세한 로깅
    """
    LOGGER.info("Starting login form fill...")
    
    # 페이지 안정화 대기
    time.sleep(0.5)
    
    # 회원번호 라디오 버튼 클릭 (기본 선택되어 있지만 확실하게)
    try:
        page.evaluate("""() => {
            const radio = document.querySelector('input#srchDvCd1');
            if (radio && !radio.checked) {
                radio.checked = true;
                radio.click();
            }
        }""")
        time.sleep(0.3)
    except Exception as e:
        LOGGER.debug(f"Failed to click member number radio: {e}")
    
    # ID 입력 필드 셀렉터들
    id_selectors = [
        "input#srchDvNm01",
        "input[name='srchDvNm']#srchDvNm01",
        "input[type='text'][name='srchDvNm']:not([disabled])",
        "#srchDvNm01",
    ]
    
    pw_selectors = [
        "input#hmpgPwdCphd01",
        "input[name='hmpgPwdCphd']#hmpgPwdCphd01",
        "input[type='password'][name='hmpgPwdCphd']:not([disabled])",
        "#hmpgPwdCphd01",
    ]

    # ID 입력 시도
    id_success = False
    for sel in id_selectors:
        LOGGER.info(f"Trying ID selector: {sel}")
        if _fill_input_with_js(page, sel, user, "text"):
            id_success = True
            LOGGER.info(f"✓ ID input successful with: {sel}")
            
            # 입력 검증
            time.sleep(0.3)
            try:
                actual_value = page.evaluate("""(selector) => {
                    const el = document.querySelector(selector);
                    return el ? el.value : null;
                }""", sel)
                LOGGER.info(f"ID verification: expected='{user}', actual='{actual_value}'")
            except Exception as e:
                LOGGER.debug(f"ID verification failed: {e}")
            
            break
    
    if not id_success:
        LOGGER.error("❌ Failed to fill ID field with any selector")

    # PW 입력 시도
    time.sleep(0.3)
    pw_success = False
    for sel in pw_selectors:
        LOGGER.info(f"Trying PW selector: {sel}")
        if _fill_input_with_js(page, sel, pw, "password"):
            pw_success = True
            LOGGER.info(f"✓ PW input successful with: {sel}")
            break
    
    if not pw_success:
        LOGGER.error("❌ Failed to fill PW field with any selector")

    if not id_success or not pw_success:
        # 디버그 정보 수집
        try:
            debug_info = page.evaluate("""() => {
                const idField = document.querySelector('input#srchDvNm01');
                const pwField = document.querySelector('input#hmpgPwdCphd01');
                
                return {
                    idField: idField ? {
                        exists: true,
                        value: idField.value,
                        disabled: idField.disabled,
                        readOnly: idField.readOnly,
                        display: idField.style.display,
                        visibility: idField.style.visibility
                    } : { exists: false },
                    pwField: pwField ? {
                        exists: true,
                        disabled: pwField.disabled,
                        readOnly: pwField.readOnly,
                        display: pwField.style.display,
                        visibility: pwField.style.visibility
                    } : { exists: false }
                };
            }""")
            LOGGER.error(f"Debug info: {debug_info}")
        except Exception as e:
            LOGGER.error(f"Failed to collect debug info: {e}")
        
        raise RuntimeError(f"Failed to fill login form (ID:{id_success}, PW:{pw_success})")
    
    LOGGER.info("✓ Login form filled successfully")


def _wait_for_dynapath_init(page: Page, timeout_sec: float = 5.0) -> None:
    """dynaPath.do 스크립트 초기화 대기.

    /dynaPath.do 스크립트는 페이지 로드 후 form action 과 링크 href 를
    세션 토큰이 포함된 dynaPath URL 로 재작성한다.
    form submit 전에 이 변환이 완료되어야 POST 가 올바른 엔드포인트로 전송된다.
    """
    end = time.time() + timeout_sec
    while time.time() < end:
        try:
            ready = page.evaluate("""() => {
                // 신호 1: window.dynaPath 객체 초기화 완료
                if (window.dynaPath && window.dynaPath.initialized) return true;
                // 신호 2: form action 이 이미 dynaPath URL 로 변환된 경우
                const form = document.querySelector('form[action]');
                if (form && form.action && form.action.includes('dynaPath')) return true;
                return false;
            }""")
            if ready:
                LOGGER.debug("dynaPath initialized (form action transformed)")
                return
        except Exception:
            pass
        time.sleep(0.2)
    # 타임아웃 시 경고만 하고 계속 진행
    LOGGER.debug("dynaPath init wait timed out; proceeding anyway")


def _submit_login(page: Page) -> None:
    """로그인 제출"""
    LOGGER.info("Submitting login...")

    # SRT dynaPath: form action 변환 완료 대기
    _wait_for_dynapath_init(page, timeout_sec=5.0)

    # Dialog 리스너 먼저 설정
    def handle_dialog(dialog):
        msg = dialog.message
        LOGGER.info(f"Dialog: {msg}")
        dialog.accept()

    page.on("dialog", handle_dialog)

    # 셀렉터 우선순위:
    #   1) input.loginSubmit  ← 2025-12 SRT 실제 DOM 클래스명
    #   2) input[type='submit'][value='로그인']  ← 값 기반 fallback
    #   3) 구버전 클래스들 (이전 코드 호환 유지)
    submit_selectors = [
        "input.loginSubmit:not([disabled])",
        "input[type='submit'][value='로그인']:not([disabled])",
        "a.btn_login",
        "button.btn_login",
        "input.btn_login",
        "a[onclick*='login']",
        "button[onclick*='login']",
    ]

    for sel in submit_selectors:
        # Playwright 네이티브 클릭 우선 (이벤트 전파가 더 자연스러움)
        try:
            locator = page.locator(sel).first
            if locator.count() > 0:
                locator.click(timeout=5_000)
                LOGGER.info(f"✓ Clicked login button (playwright): {sel}")
                return
        except Exception as e:
            LOGGER.debug(f"Playwright click failed for {sel}: {e}")

        # JavaScript 클릭 fallback
        try:
            result = page.evaluate("""(selector) => {
                const elements = document.querySelectorAll(selector);
                for (let elem of elements) {
                    if (!elem.disabled) {
                        elem.click();
                        return { success: true, selector: selector, text: elem.textContent || elem.value };
                    }
                }
                return { success: false, selector: selector };
            }""", sel)

            if result and result.get('success'):
                LOGGER.info(f"✓ Clicked login button (JS): {sel} ('{result.get('text', '')}')")
                return

        except Exception as e:
            LOGGER.debug(f"JS click failed for {sel}: {e}")

    # Fallback: Enter 키
    LOGGER.info("Submitting via Enter key")
    try:
        page.keyboard.press("Enter")
    except Exception as e:
        LOGGER.error(f"Enter key failed: {e}")


def _handle_dialogs(page: Page) -> None:
    """대화상자 처리"""
    try:
        with page.expect_event("dialog", timeout=2000) as d_info:
            dialog = d_info.value
            LOGGER.info("Dialog: %s", dialog.message)
            dialog.accept()
    except PlaywrightTimeoutError:
        return


def _click_inline_confirm(page: Page) -> None:
    """인라인 확인 버튼 + SweetAlert2 모달"""
    # SweetAlert2 모달 먼저 체크
    if _dismiss_swal2(page, timeout_sec=2.0):
        return
    for sel in [
        "button:has-text('확인')",
        "input[type='button'][value='확인']",
        "input[type='submit'][value='확인']",
    ]:
        try:
            page.click(sel, timeout=1500)
            LOGGER.info("Clicked inline confirm: %s", sel)
            return
        except Exception:
            continue


# ========== 팝업 처리 ==========

def _close_extra_pages(page: Page) -> None:
    """현재 페이지를 제외한 같은 컨텍스트의 다른 페이지(팝업 등)를 모두 닫는다."""
    try:
        ctx = page.context
        for p in ctx.pages:
            if p is not page and not p.is_closed():
                LOGGER.info("기존 팝업/탭 정리: %s", p.url or "about:blank")
                try:
                    p.close()
                except Exception:
                    pass
    except Exception as e:
        LOGGER.debug("팝업 정리 실패: %s", e)


# ========== 예약 관련 ==========

def _ensure_selectors() -> None:
    if not getattr(selectors, "BUTTON_RESERVE", None):
        LOGGER.debug("BUTTON_RESERVE not defined")


def _on_queue_page(page: Page) -> bool:
    """풀페이지 대기열 감지"""
    try:
        href = (page.url or "").lower()
        if any(s in href for s in ("netfunnel", "queue", "wait")):
            return True

        html = (page.content() or "").lower()
        if any(k in html for k in ("netfunnel", "대기열", "잠시만")):
            body_child_cnt = page.evaluate(
                "() => document.body && document.body.children ? document.body.children.length : 0"
            )
            if body_child_cnt <= 3:
                return True
    except Exception:
        pass
    return False


def _dismiss_swal2(page: Page, timeout_sec: float = 5.0) -> bool:
    """SweetAlert2 모달이 떠 있으면 확인 버튼 클릭.

    reservationAfterMsg() 가 Swal.fire() 로 '이용안내' 모달을 띄우며,
    결과의 isConfirmed 가 true 일 때만 requestReservationInfo() 를 호출한다.
    DOM 기반 모달이므로 Playwright dialog 핸들러로는 잡히지 않는다.
    """
    swal_confirm_selectors = [
        "button.swal2-confirm",
        ".swal2-actions button.swal2-styled.swal2-default-outline",
        ".swal2-popup button:has-text('확인')",
    ]
    end = time.time() + timeout_sec
    while time.time() < end:
        for sel in swal_confirm_selectors:
            try:
                loc = page.locator(sel)
                if loc.count() > 0 and loc.first.is_visible():
                    loc.first.click(timeout=2000)
                    LOGGER.info("SweetAlert2 확인 버튼 클릭: %s", sel)
                    time.sleep(0.5)
                    return True
            except Exception:
                continue
        time.sleep(0.3)
    return False


def _wait_until_clickable(page: Page, selector: str, timeout_sec: float = 15.0) -> bool:
    """버튼 클릭 가능 대기"""
    end = time.time() + timeout_sec
    loc = page.locator(selector)
    while time.time() < end:
        try:
            if loc.count() == 0:
                time.sleep(0.2)
                continue
            if not loc.first.is_disabled():
                return True
        except PlaywrightError:
            pass
        time.sleep(0.2)
    return False


def _click_with_netfunnel_support(page: Page, selector: str, artifact_root: Path, label: str = "reserve") -> None:
    """NetFunnel 지원 클릭 + SweetAlert2 모달 자동 확인"""
    _inject_netfunnel_handler(page)
    
    if not _wait_until_clickable(page, selector, timeout_sec=15.0):
        raise RuntimeError("Button did not become clickable")

    LOGGER.info("Clicking %s button (NetFunnel expected)", label)
    LOGGER.info("Pre-click URL: %s", page.url)

    # 클릭 전 결과 페이지 저장 (디버깅용)
    pre_click_dir = timestamped_path(artifact_root, "pre-click-debug")
    dump_artifacts(page, pre_click_dir, "before_click")
    LOGGER.info("Pre-click artifacts: %s", pre_click_dir)

    page.on("dialog", lambda dialog: dialog.accept())
    
    try:
        page.locator(selector).first.click(timeout=5000)
    except Exception as e:
        LOGGER.warning("Click exception: %s", e)
    
    LOGGER.info("Post-click URL: %s", page.url)
    time.sleep(POST_CLICK_SETTLE)
    LOGGER.info("Post-settle URL: %s", page.url)

    # 클릭 후 로그인 페이지로 리다이렉트 감지
    if "selectLoginForm" in page.url or "TK0701000000" in page.url:
        LOGGER.warning("⚠ 예약 클릭 후 로그인 페이지로 리다이렉트됨 → 세션 만료")
        global _last_login_verified
        _last_login_verified = 0.0  # 캐시 무효화
        raise RuntimeError("Session expired during reservation click")

    # SweetAlert2 모달 자동 확인 (reservationAfterMsg → Swal.fire → 확인)
    dismissed = _dismiss_swal2(page)
    LOGGER.info("SweetAlert2 dismiss result: %s, URL: %s", dismissed, page.url)
    
    # 첫 번째 성공 체크 (즉시)
    try:
        if _is_reservation_success(page):
            LOGGER.info("✓ Reservation success")
            return
    except Exception:
        pass
    
    # 대기열 또는 추가 처리 필요 시
    start_time = time.time()
    while time.time() - start_time < QUEUE_WAIT_TIMEOUT:
        # 로그인 페이지 감지 → 즉시 중단
        cur = page.url
        if "selectLoginForm" in cur or "TK0701000000" in cur:
            LOGGER.warning("Redirected to login during queue wait")
            _last_login_verified = 0.0
            raise RuntimeError("Session expired during reservation")

        # 대기열 감지
        if _on_queue_page(page):
            LOGGER.debug("In queue, waiting...")
            time.sleep(QUEUE_POLL_INTERVAL)
            continue

        # SweetAlert2 모달이 떠있으면 확인 (추가 안내 등)
        _dismiss_swal2(page, timeout_sec=0.5)
        
        # 성공 체크
        try:
            if _is_reservation_success(page):
                LOGGER.info("✓ Reservation success")
                return
        except Exception:
            pass
        
        time.sleep(QUEUE_POLL_INTERVAL)
    
    artifact_dir = timestamped_path(artifact_root, "reserve-timeout")
    dump_artifacts(page, artifact_dir, "timeout")
    raise RuntimeError("Reservation timeout")


def _is_reservation_success(page: Page) -> bool:
    """예약 성공 확인"""
    try:
        html = page.content()
        markers = [
            "10분 내에 결제",
            "결제하지 않으면 예약이 취소",
            "승차권 예매가 완료",
            "예매가 완료",
        ]
        if any(m in html for m in markers):
            return True
        
        pay_button = page.query_selector(
            "input[type='submit'][value*='결제'], button:has-text('결제')"
        )
        if pay_button:
            return True
    except Exception:
        pass
    return False


# ========== 공개 함수 ==========

def ensure_logged_in(client: SRTClient, config: SRTConfig, artifact_root: Path) -> None:
    """로그인 보장 (강화된 JavaScript 입력 + NetFunnel)"""
    user, pw = _get_credentials(config)
    
    LOGGER.info(f"Login credentials: user='{user[:3]}***' (length={len(user)})")

    page = getattr(client, "last_page", None)
    if page is None or page.is_closed():
        page = client.new_page()
        client.last_page = page

    # 팝업 가드 부착
    _attach_popup_guard(page)

    try:
        page.wait_for_load_state("domcontentloaded", timeout=5000)
    except PlaywrightTimeoutError:
        pass

    if _is_logged_in(page):
        LOGGER.info("✓ Already logged in")
        return

    LOGGER.info("⚠ Not logged in. Attempting login...")
    
    try:
        _inject_netfunnel_handler(page)
        safe_goto(page, LOGIN_URL)
        
        try:
            page.wait_for_load_state("domcontentloaded", timeout=10000)
        except PlaywrightTimeoutError:
            pass
        
        time.sleep(0.5)  # 페이지 안정화

        # 로그인 URL로 이동했지만 이미 로그인된 상태면 리다이렉트됨
        if _is_logged_in(page):
            LOGGER.info("✓ Already logged in (detected after redirect)")
            client.last_page = page
            return

        # JavaScript 방식으로 입력
        _fill_login_form(page, user, pw)
        time.sleep(0.3)  # 입력 안정화
        
        _submit_login(page)
        _handle_dialogs(page)

        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except PlaywrightTimeoutError:
            pass

        time.sleep(0.5)

        # 로그인 검증 (2단계)
        if not _is_logged_in(page):
            time.sleep(1)
            try:
                page.reload(wait_until="domcontentloaded", timeout=8000)
            except:
                pass
            
            if not _is_logged_in(page):
                artifact_dir = timestamped_path(artifact_root, "login-error")
                dump_artifacts(page, artifact_dir, "login_failed")
                raise RuntimeError(f"Login failed. Artifacts: {artifact_dir}")

        LOGGER.info("✓ Login completed!")
        client.last_page = page

    except Exception as e:
        artifact_dir = timestamped_path(artifact_root, "login-error")
        dump_artifacts(page, artifact_dir, "login_exception")
        LOGGER.error("❌ Login failed. Artifacts: %s", artifact_dir)
        raise RuntimeError(f"Login failed: {e}") from e


def attempt_reservation(
    client: SRTClient,
    config: SRTConfig,
    target: Dict[str, str],
    artifact_root: Path,
) -> None:
    """예약 시도 — JS 직접 실행 방식 (NetFunnel 지원)"""
    _ensure_selectors()

    page = getattr(client, "last_page", None)
    if page is None or page.is_closed():
        raise RuntimeError("Search result page not available")

    # 팝업 가드 부착 (사이트 팝업이 예약 버튼 클릭을 방해하는 문제 방지)
    _attach_popup_guard(page)

    if not _is_logged_in(page):
        LOGGER.warning("⚠ 예약 직전 로그인 세션 만료 감지 → 재로그인 시도")
        ensure_logged_in(client, config, artifact_root)
        raise RuntimeError("Re-login completed; need to re-search")

    selector = target.get("reserve_selector")
    onclick_js = target.get("reserve_onclick", "")
    if not selector and not onclick_js:
        raise RuntimeError("No reserve_selector or reserve_onclick")

    LOGGER.info("Attempting reservation: %s", target.get("depart"))

    # dialog (alert/confirm) 자동 수락
    def _auto_accept_dialog(dialog):
        LOGGER.info("예약 다이얼로그 자동 수락: %s", dialog.message[:100])
        dialog.accept()
    page.on("dialog", _auto_accept_dialog)

    # 예약 버튼 클릭 전 기존 팝업 정리
    _close_extra_pages(page)

    try:
        _inject_netfunnel_handler(page)

        # 예약 전 아티팩트 저장 (디버깅 - 실패 시만)
        LOGGER.info("Pre-click URL: %s", page.url)

        # 쿠키 로그
        try:
            cookies = page.context.cookies("https://etk.srail.kr")
            jsid = [c for c in cookies if c["name"] == "JSESSIONID_ETK"]
            LOGGER.info("JSESSIONID_ETK cookie: %s", jsid[0]["value"][:20] + "..." if jsid else "NONE")
        except Exception:
            pass

        # 방법 1: onclick JS가 있으면 직접 실행 (element click 대신)
        if onclick_js:
            LOGGER.info("Executing onclick JS directly: %s", onclick_js[:100])

            # 팝업 차단: window.open을 무력화하고 SweetAlert2 자동 확인
            page.evaluate("""() => {
                // window.open 차단 (광고/공지 팝업 방지)
                window.open = function() {
                    console.log('[binjari] window.open blocked');
                    return null;
                };

                // SweetAlert2 자동 확인: 원래 Swal.fire를 래핑
                if (window.Swal && window.Swal.fire) {
                    window.Swal.fire = function(opts) {
                        return Promise.resolve({ isConfirmed: true, isDenied: false, isDismissed: false, value: true });
                    };
                }
            }""")

            # 버튼 엘리먼트 찾기 (onclick의 this 참조용)
            try:
                btn_el = page.locator(selector).first.element_handle()
            except Exception:
                btn_el = None

            # expect_navigation + JS 실행
            try:
                with page.expect_navigation(timeout=30_000, wait_until="domcontentloaded"):
                    if btn_el:
                        page.evaluate("(el) => { el.click(); }", btn_el)
                    else:
                        page.evaluate(f"() => {{ {onclick_js} }}")
                LOGGER.info("Post-navigation URL: %s", page.url)
            except PlaywrightTimeoutError:
                LOGGER.warning("Navigation timeout after onclick — checking page state")
                LOGGER.info("Current URL: %s", page.url)
        else:
            # 방법 2: 셀렉터 클릭 fallback
            LOGGER.info("Clicking reserve button via selector")
            # 팝업 차단
            page.evaluate("""() => {
                window.open = function() {
                    console.log('[binjari] window.open blocked');
                    return null;
                };
            }""")
            try:
                with page.expect_navigation(timeout=30_000, wait_until="domcontentloaded"):
                    page.locator(selector).first.click(timeout=5000)
                LOGGER.info("Post-navigation URL: %s", page.url)
            except PlaywrightTimeoutError:
                LOGGER.warning("Navigation timeout after click — checking page state")

        # 클릭/JS 실행 후 대기
        time.sleep(POST_CLICK_SETTLE)
        LOGGER.info("Post-settle URL: %s", page.url)

        # 로그인 페이지 리다이렉트 감지
        if "selectLoginForm" in page.url or "TK0701000000" in page.url:
            LOGGER.warning("⚠ 예약 후 로그인 페이지로 리다이렉트 — 세션 만료")
            global _last_login_verified
            _last_login_verified = 0.0
            raise RuntimeError("Session expired during reservation")

        # SweetAlert2 모달 체크/확인 (빠르게)
        _dismiss_swal2(page, timeout_sec=0.5)

        try:
            page.wait_for_load_state("networkidle", timeout=3000)
        except PlaywrightTimeoutError:
            pass

        # 대기열 처리
        start_time = time.time()
        while time.time() - start_time < QUEUE_WAIT_TIMEOUT:
            cur = page.url
            if "selectLoginForm" in cur or "TK0701000000" in cur:
                _last_login_verified = 0.0
                raise RuntimeError("Session expired during reservation")

            if _is_reservation_success(page):
                LOGGER.info("✓ Reservation completed!")
                return

            if _on_queue_page(page):
                LOGGER.debug("In queue, waiting...")
                time.sleep(QUEUE_POLL_INTERVAL)
                continue

            _dismiss_swal2(page, timeout_sec=0.5)

            if _is_reservation_success(page):
                LOGGER.info("✓ Reservation completed!")
                return

            # 더 이상 대기열이 아니고 성공도 아니면 탈출
            time.sleep(QUEUE_POLL_INTERVAL)
            break

        # 최종 확인
        if _is_reservation_success(page):
            LOGGER.info("✓ Reservation completed!")
            return

        artifact_dir = timestamped_path(artifact_root, "reserve-error")
        dump_artifacts(page, artifact_dir, "no_success")
        raise RuntimeError("No success markers after reservation attempt")

    except Exception as e:
        if "Session expired" not in str(e) and "No success markers" not in str(e):
            artifact_dir = timestamped_path(artifact_root, "reserve-error")
            dump_artifacts(page, artifact_dir, "exception")
            LOGGER.error("❌ Reservation failed: %s", artifact_dir)
        raise
    finally:
        try:
            page.remove_listener("dialog", _auto_accept_dialog)
        except Exception:
            pass


__all__ = ["ensure_logged_in", "attempt_reservation"]
