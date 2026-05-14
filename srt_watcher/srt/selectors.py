# srt/selectors.py
"""
Selectors for the live SRT site (etk.srail.kr).
2026-04 리뉴얼 이후 DOM 구조에 맞춘 버전.
검색 폼이 메인 페이지(main.do)에 통합됨.
"""

# --- Search form ---
# 역: select 드롭다운으로 코드 직접 선택 (구: 텍스트 입력 + 히든 코드)
# 날짜: input#cal (readonly, 형식 "2026.04.03") (구: select[name=dptDt])
# 시간: select#dptTm (그대로)
SEARCH_FORM = {
    "origin": "select#dptRsStnCd",
    "dest":   "select#arvRsStnCd",
    "date":   "input#cal, input[name='dptDt']",
    "time":   "#dptTm, select#dptTm",
}

# 조회 버튼 (리뉴얼 후: button + 구버전 fallback)
SEARCH_BUTTON = (
    "button[onclick*='selectScheduleList'], "
    "button.krds-btn:has-text('조회'), "
    "#search_top_tag input.inquery_btn, "
    "#search_top_tag input[type='submit'][value='조회하기']"
)

# 검색 폼 존재 확인 — 네비게이션 성공 판별용
SEARCH_FORM_DETECT = (
    "select#dptRsStnCd, "
    "form#search-form, "
    "#dptRsStnCdNm, input#dptRsStnCdNm, "
    "#search_top_tag"
)

# --- Result table ---
RESULT_ROWS = "table > tbody > tr"

# 컬럼 인덱스 (thead 기준):
# 1: 구분
# 2: 열차종류
# 3: 열차번호
# 4: 출발역(출발시각 포함, 예: '수서 08:00')
# 5: 도착역
# 6: 특실
# 7: 일반실
COL_DEPART_TIME = "td:nth-child(4)"
COL_FIRST       = "td:nth-child(6)"
COL_GENERAL     = "td:nth-child(7)"

# 일반실 '예약하기' / '좌석선택' 버튼
BUTTON_GENERAL = (
    "td:nth-child(7) a:has-text('예약하기'), "
    "td:nth-child(7) button:has-text('예약하기'), "
    "td:nth-child(7) input[type='button'][value*='예약하기'], "
    "td:nth-child(7) input[type='submit'][value*='예약하기'], "
    "td:nth-child(7) a:has-text('좌석선택'), "
    "td:nth-child(7) button:has-text('좌석선택'), "
    "td:nth-child(7) input[type='button'][value*='좌석선택'], "
    "td:nth-child(7) input[type='submit'][value*='좌석선택']"
)

# 특실 '예약하기' / '좌석선택' 버튼
BUTTON_FIRST = (
    "td:nth-child(6) a:has-text('예약하기'), "
    "td:nth-child(6) button:has-text('예약하기'), "
    "td:nth-child(6) input[type='button'][value*='예약하기'], "
    "td:nth-child(6) input[type='submit'][value*='예약하기'], "
    "td:nth-child(6) a:has-text('좌석선택'), "
    "td:nth-child(6) button:has-text('좌석선택'), "
    "td:nth-child(6) input[type='button'][value*='좌석선택'], "
    "td:nth-child(6) input[type='submit'][value*='좌석선택']"
)

# fallback: 혹시 전역에서 예약 버튼 찾을 때
BUTTON_RESERVE = (
    "a:has-text('예약하기'), "
    "button:has-text('예약하기'), "
    "input[type='button'][value*='예약하기'], "
    "input[type='submit'][value*='예약하기']"
)

# --- Queue / Guard (NetFunnel 등) 감지 신호 ---
# 1) 명시적 ID/클래스(가능한 한 많이 포괄)
QUEUE_MODAL = (
    "#NetFunnel_Loading_Popup, #NetFunnel_Skin_Loading, #netfunnel_layer, "
    "#queueModal, .modal-wait, .layer.wait, "
    "div[role='dialog'][aria-modal='true'], .modal-backdrop.show"
)

# 2) 닫기 버튼 후보(모달형 방어용; 풀페이지 큐에선 사용 안 됨)
QUEUE_CLOSE = (
    ".modal-wait .btn-close, #queueModal .btn-close, "
    "button.close, .modal [data-dismiss='modal'], .modal .btn:has-text('닫기')"
)

# 3) 인라인 확인 버튼
INLINE_CONFIRM = (
    "input[type='submit'][value='확인'], "
    "input[type='button'][value='확인'], "
    "button:has-text('확인'), a:has-text('확인')"
)

# 4) 텍스트 키워드(마지막 수단)
QUEUE_KEYWORDS = [
    "대기열", "잠시만", "순서가", "안내", "혼잡",
    "NetFunnel", "netfunnel", "자동으로",
]
