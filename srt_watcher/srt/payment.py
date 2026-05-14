from __future__ import annotations

import logging
import os
from typing import Optional

from playwright.sync_api import Page, TimeoutError as PWTimeoutError

LOGGER = logging.getLogger("srt_watcher.srt.payment")

# Dialog 중복 처리 방지용 (모듈 레벨)
_handled_dialogs = set()

def _safe_dialog_handler(dialog):
    """
    Dialog를 안전하게 처리하는 핸들러
    - 같은 dialog를 여러 번 accept하려는 시도 방지
    - 'already handled' 에러 무시
    - 다른 에러는 로깅
    """
    dialog_id = id(dialog)
    
    # 이미 처리한 dialog면 스킵
    if dialog_id in _handled_dialogs:
        LOGGER.debug(f"Dialog {dialog_id} already handled, skipping")
        return
    
    # 처리 목록에 추가
    _handled_dialogs.add(dialog_id)
    
    try:
        msg = dialog.message
        LOGGER.debug(f"Accepting dialog: '{msg}'")
        dialog.accept()
    except Exception as e:
        error_msg = str(e).lower()
        if "already handled" in error_msg or "already dismissed" in error_msg:
            # 예상된 에러 (다른 리스너가 이미 처리함)
            LOGGER.debug(f"Dialog already handled by another listener: {e}")
        else:
            # 예상치 못한 에러는 경고
            LOGGER.warning(f"Unexpected dialog error: {e}")

# ---------- config helpers ----------

def _get(name: str, default: Optional[str] = None) -> Optional[str]:
    v = os.getenv(name, default)
    return None if v is None else str(v).strip()

def payment_enabled(cfg=None) -> bool:
    raw = (getattr(cfg, "pay_enabled", None) if cfg and hasattr(cfg, "pay_enabled") else None)
    if raw is None:
        raw = _get("PAYMENT_MODE", "false")
    return str(raw).lower() in ("1", "true", "yes", "y", "on")

def _digits_only(s: str) -> str:
    return "".join(ch for ch in (s or "") if ch.isdigit())

def _parse_inputs(cfg):
    # 카드번호: "1234-1234-1234-1234" 권장
    raw = (getattr(cfg, "pay_card_num", None) if cfg and hasattr(cfg, "pay_card_num") else None) or _get("PAY_CARD_NUM", "")
    raw = (raw or "").replace(" ", "")
    c1 = c2 = c3 = c4 = ""
    if raw:
        parts = [p for p in raw.split("-") if p]
        if len(parts) == 4 and all(len(p) == 4 and p.isdigit() for p in parts):
            c1, c2, c3, c4 = parts
        else:
            digits = _digits_only(raw)
            if len(digits) == 16:
                c1, c2, c3, c4 = digits[0:4], digits[4:8], digits[8:12], digits[12:16]
    if not c1:
        c1 = _digits_only(_get("PAY_CARD_1", ""))
        c2 = _digits_only(_get("PAY_CARD_2", ""))
        c3 = _digits_only(_get("PAY_CARD_3", ""))
        c4 = _digits_only(_get("PAY_CARD_4", ""))

    mm = _digits_only((getattr(cfg, "pay_card_mm", None) if cfg and hasattr(cfg, "pay_card_mm") else None) or _get("PAY_CARD_MM", ""))
    yyyy = _digits_only((getattr(cfg, "pay_card_yy", None) if cfg and hasattr(cfg, "pay_card_yy") else None) or _get("PAY_CARD_YY", ""))
    pw2 = _digits_only((getattr(cfg, "pay_card_pw2", None) if cfg and hasattr(cfg, "pay_card_pw2") else None) or _get("PAY_CARD_PW2", ""))
    id6 = _digits_only((getattr(cfg, "pay_id6", None) if cfg and hasattr(cfg, "pay_id6") else None) or _get("PAY_ID6", ""))

    errs = []
    for idx, seg in enumerate([c1, c2, c3, c4], 1):
        if len(seg) != 4 or not seg.isdigit():
            errs.append(f"card segment {idx} must be 4 digits")
    try:
        mi = int(mm)
        if not (1 <= mi <= 12): errs.append("PAY_CARD_MM must be 01..12")
    except Exception:
        errs.append("PAY_CARD_MM must be 01..12")
    mm = f"{int(mm):02d}" if mm else mm

    if not (len(yyyy) == 4 and yyyy.isdigit() and 2025 <= int(yyyy) <= 2037):
        errs.append("PAY_CARD_YY must be 2025..2037 (4 digits)")

    if not (len(pw2) == 2 and pw2.isdigit()):
        errs.append("PAY_CARD_PW2 must be 2 digits")
    if not (len(id6) == 6 and id6.isdigit()):
        errs.append("PAY_ID6 must be 6 digits (YYMMDD)")

    if errs:
        raise ValueError("Invalid payment config: " + ", ".join(errs))

    # NOTE: 연도 select 의 option value 가 "30" 형태(=2030)이므로 2자리로 변환
    yy2 = yyyy[-2:]

    return {
        "c1": c1, "c2": c2, "c3": c3, "c4": c4,
        "mm": mm, "yyyy": yyyy, "yy2": yy2,
        "pw2": pw2, "id6": id6,
    }

# ---------- main entry ----------

def perform_payment(page: Page, cfg=None) -> None:
    if not payment_enabled(cfg):
        LOGGER.info("Payment mode disabled; skipping payment step.")
        return

    data = _parse_inputs(cfg)
    LOGGER.info("Proceeding to payment (fast ids): ****-****-****-%s  MM/YYYY=%s/%s",
                data["c4"], data["mm"], data["yyyy"])

    # 0) 예약확정 화면에서 '결제하기' 진입
    pay_btn_candidates = [
        "text=결제하기",
        "role=button[name='결제하기']",
        "role=link[name='결제하기']",
        "css=a:has-text('결제하기')",
        "css=button:has-text('결제하기')",
        "css=input[type='button'][value='결제하기']",
    ]
    clicked = False
    for sel in pay_btn_candidates:
        try:
            with page.expect_navigation(wait_until="domcontentloaded", timeout=30000):
                page.locator(sel).click(timeout=3000)
            LOGGER.info("Clicked pay button via %s", sel)
            clicked = True
            break
        except Exception:
            continue
    if not clicked:
        raise PWTimeoutError("Could not navigate to payment page (결제하기 not found).")

    # 1) 체크박스 2개 해제 (네가 준 정확한 id 사용)
    try:
        page.locator("#Tk_stlCrCrdNo14_checkbox").set_checked(False, timeout=3000)
        LOGGER.info("Unchecked card-number security checkbox")
    except Exception:
        pass
    try:
        page.locator("#Tk_vanPwd1_checkbox").set_checked(False, timeout=3000)
        LOGGER.info("Unchecked PW2 security checkbox")
    except Exception:
        pass

    # 2) 카드번호 4칸 (정확 id)
    page.locator("#stlCrCrdNo11").fill(data["c1"], timeout=3000)
    page.locator("#stlCrCrdNo12").fill(data["c2"], timeout=3000)
    page.locator("#stlCrCrdNo13").fill(data["c3"], timeout=3000)
    page.locator("#stlCrCrdNo14").fill(data["c4"], timeout=3000)

    # 3) 유효기간 (월/년) select
    #   월: id=crdVlidTrm1M  (values '01'..'12')
    #   년: id=crdVlidTrm1Y  (values '25'..'37', label '2025'..'2037')
    try:
        page.select_option("#crdVlidTrm1M", value=data["mm"])
    except Exception:
        page.select_option("#crdVlidTrm1M", label=str(int(data["mm"])))
    try:
        page.select_option("#crdVlidTrm1Y", value=data["yy2"])
    except Exception:
        page.select_option("#crdVlidTrm1Y", label=data["yyyy"])

    # 4) 비밀번호 앞 2자리 & 인증번호(YYMMDD)
    page.locator("#vanPwd1").fill(data["pw2"], timeout=3000)
    page.locator("#athnVal1").fill(data["id6"], timeout=3000)

    # 5) 스마트폰 발권 탭 클릭
    page.on("dialog", _safe_dialog_handler)
    page.locator("a[href='javascript:changeIseTpCd(1);']").first.click(timeout=10000)
    LOGGER.info("Clicked smartphone issuance tab and auto-accepted popup")
    page.wait_for_timeout(10000)

    # 6) 결제 및 발권
    try:
        page.locator("#requestIssue1").click(timeout=5000)
    except Exception:
        # fallback: 텍스트 기반
        page.locator("text=결제 및 발권").click(timeout=5000)

    # 7) 성공 문구 확인
    try:
        page.wait_for_load_state("networkidle", timeout=20000)
    except Exception:
        pass

    success_texts = ["결제 완료", "발권 완료", "결제/발권이 완료", "승차권", "발급이", "완료", "발권내역조회"]
    for t in success_texts:
        try:
            if page.locator(f"text={t}").first.is_visible(timeout=30000):
                LOGGER.info("Payment success detected via text: %s", t)
                return
        except Exception:
            continue

    raise RuntimeError("Payment step did not confirm success text; please check page state.")
