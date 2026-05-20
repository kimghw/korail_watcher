# 트러블슈팅 기록 — 2026-05-20

5/29 KTX 121 예약대기 신청 / 6/1 좌석 예약 작업 중 발견된 워처 동작 실패와 처리 내역.

각 항목 형식: **증상 → 원인 → 처리**.

---

## 1. 공지 모달 (운영기간 알림) 이 클릭을 가로챔

### 증상
- 워처가 `a.btn_pop.btn_d-day` (date picker d-day 버튼) 클릭에서 30초 타임아웃.
- 매 iteration 같은 위치에서 실패.
- Playwright call log: `<div class="ReactModalPortal">…</div> subtree intercepts pointer events`.
- 가로채는 이미지: `/file/cubedata/COMMON/gallery/f20260520w5CL.jpg` alt="광명 → 천안아산 일부 구간 KTX 서행 알림 / 운행 기간: 5.20.~5.26."

### 원인
워처의 `dismiss_all_popups` 는 안내 키워드 (`안내`, `CODE`, `이용안내`, `약관` 등) + "확인" 버튼만 잡음. 이 공지 모달은:
- body 키워드: `창닫기`, `1일간 그만보기` — 매칭 안 됨
- 닫기 버튼: `button.btn_pop-close` (텍스트 "창닫기") — "확인" 매칭 안 됨

또 진입 직후 1회만 dismiss 시도 — 모달이 React 비동기 mount 라 호출 시점에는 아직 안 떠 있어서 silently False.

### 처리
- [selectors.py](../../../../ktx_watcher/korail/selectors.py): `NOTICE_MODAL_KEYWORDS = ("창닫기", "그만보기")`, `NOTICE_MODAL_DISMISS_BUTTON`, `NOTICE_MODAL_HIDE_TODAY_CHECKBOX` 추가.
- [client.py](../../../../ktx_watcher/korail/client.py): `dismiss_notice_modal()` 신규.
  1. "N일간 그만보기" 체크박스 클릭 (cookie 로 24시간 안 뜸)
  2. "창닫기" 버튼 클릭
- [search.py](../../../../ktx_watcher/korail/search.py): `navigate_to_search` 끝에 4초 polling, `_set_date` 시작에 단발 dismiss.

검증: `19:33:56 | 공지 모달 '창닫기' 클릭 dismiss` → 이후 검색 정상.

---

## 2. 검색 결과 row priceBox 식별 — sold_out / wait class 추가

### 증상
- 검색 결과 row 10건 잡혔는데 **후보 0건**.
- 후보 추출에서 `general_status=""` (빈 값) → continue.

### 원인
사이트가 priceBox 의 class 체계를 변경:

| 상태 | class | 텍스트 |
|---|---|---|
| 예약 가능 (일반실) | `price_box fl-l  gen` | `일반실XX,XXX원5%적립` |
| 매진임박 (예약 가능) | `price_box gen sold_out_soon` | 가격 포함 |
| 예약대기 가능 | `price_box fl-l  wait` | `예약대기` |
| 매진 + 대기조차 불가 | `price_box fl-l  sold_out_wait` | `매진` |
| 단순 매진 | `price_box fl-l  sold_out` | `매진` |

워처 코드는 일반실 priceBox 를 `.price_box.gen` 으로만 찾음. 매진/wait row 는 `gen` class 가 빠지므로 일반실 박스 자체를 못 잡음 → `r["gen"]=None` → `general_status=""` → 후보 추출 skip.

### 처리
[search.py:_parse_result_rows](../../../../ktx_watcher/korail/search.py) — priceBox 식별을 **위치 기반** + class fallback 으로:

```js
const allBoxes = Array.from(el.querySelectorAll('.price_box'));
let genBox = allBoxes.find(b => b.classList.contains('gen')) || allBoxes[0] || null;
let specBox = null;
for (const b of allBoxes) { if (b !== genBox) { specBox = b; break; } }
```

검증: `19:37:50 | 후보 1건 (전체 row 10건)` — 매진+예약대기 row 가 정상 후보로 잡힘.

---

## 3. 예약대기 / 입석+좌석 흐름 미구현

### 증상
- 매진 row 가 후보에서 무조건 제외.
- 코레일의 "예약대기 신청" 기능 호출 코드 0건. SRT 의 `QUEUE_WAIT_TIMEOUT` 은 사이트 혼잡 대기열일 뿐 별개.
- 사용자 요구: status 가 `예약대기` / `입석 + 좌석` 인 row 도 처리.

### 원인
- 후보 필터가 `if "매진" in status: continue` + `if not any(ok in status for ok in ("원","예약하기","예매","입석")): continue` — 예약대기 row 는 "예약대기" 단어만 있고 가격/예약 키워드 없어서 skip.
- 후보 dict 에 상태 종류 정보 없음 → 예매 흐름이 항상 `button.reservbtn` 만 클릭.
- 코레일 실제 사이트의 row 선택 후 활성화되는 액션 버튼:
  - 예약 가능 row → "예매" (`button.reservbtn`)
  - 예약대기 row → **"예약대기신청"** (파란 활성 버튼, 매진 시)
  - 입석+좌석 row → **"입석+좌석 예매"**

### 처리

**(a) 후보 필터에 `status_kind` 분류** [search.py:478](../../../../ktx_watcher/korail/search.py)
```python
has_price = "원" in s or "예약하기" in s or "좌석선택" in s or "예매" in s
has_waitlist = "예약대기" in s
has_standing = "입석" in s
has_soldout = "매진" in s.replace("매진임박", "")
if has_price and not has_soldout: kind = "reserve"
elif has_waitlist:                 kind = "waitlist"
elif has_standing:                 kind = "standing"
else:                              continue
```
우선순위: 가격(예약 가능) > 예약대기 > 입석.

**(b) row anchor 선택 분기** [reserve.py:152](../../../../ktx_watcher/korail/reserve.py)
- reserve: `a + has_text("일반실"/"특실") + has_text("원") + not "매진"`
- waitlist: `a + has_text("예약대기")` — 매진 row 의 priceBox text 가 짧아 "일반실" 단어 없음. seat_key filter 제거 필수.
- standing: `a + has_text("입석")`

**(c) 액션 버튼 분기** [reserve.py:196](../../../../ktx_watcher/korail/reserve.py)
- reserve → `button.reservbtn`
- waitlist → `button:has-text('예약대기신청')`
- standing → `button:has-text('입석+좌석 예매')`

**(d) 결제 단계 강제 skip** [main.py:114](../../../../ktx_watcher/main.py)
- `kind == "waitlist"` 면 `KTXA_PAYMENT_MODE` 무관하게 결제 호출 skip + 알림 "예약대기 신청 완료".

검증 (5/29 KTX 121):
```
19:39:49 | 후보 발견: 서울→부산 2026-05-29 08:12 [일반실] 예약대기 (kind=waitlist)
19:39:49 | status_kind=waitlist
19:39:49 | 예약 row 선택: KTX 121 ... 예약대기
19:39:54 | '예약대기신청' 버튼 클릭
19:40:02 | ✅ 예약대기 신청 단계 도달
```

---

## 4. datepicker 다중 월 / 점 구분 형식

### 증상
- 5/29 작업은 OK (이미 5월 picker 가 default 표시).
- 6/1 로 날짜 바꾸자 `Site layout changed: date picker 1일 셀 미발견`.
- 매 iteration 같은 곳에서 실패.

### 원인 (DOM dump 로 확인)
- picker 가 slick carousel 안에 3개 datepicker (5월/6월/7월) 동시 mount.
- carousel 의 `slick-track` 이 `translate3d(-1124px,...)` — **7월 슬라이드 위치로 이동된 상태**. NEXT 버튼 `slick-disabled`.
- 모든 비활성 카드의 td 가 `class="disabled  "` + `a aria-disabled="true"`. 즉 visible 카드만 클릭 가능.
- `_read_current_ym` 의 regex `/(20\d{2})\s*년\s*(\d{1,2})\s*월/` 가 사이트 헤더 형식 `"2026. 06."` (점 구분) 와 매칭 실패 → None 반환 → 월 정렬 break → 7월 위치 그대로.
- `_click_day` 도 `.datepicker` 하나만 봐서 6월 카드 자체를 못 찾음.

### 처리

**(a) `_read_current_ym` regex 확장 + slick-active 우선** [search.py:102](../../../../ktx_watcher/korail/search.py)
```js
const re = /(20\d{2})\s*[.년]\s*(\d{1,2})/;  // 점 또는 "년" 둘 다
// .slick-active 안의 .datepicker .date 우선, 없으면 모든 .datepicker .date
```

**(b) `_click_day` 다중 카드 + month 헤더 매칭** [search.py:121](../../../../ktx_watcher/korail/search.py)
- year/month 인자 추가
- `.slick-slide` / `.datepk_wrap` 카드 순회
- 각 카드의 `.datepicker .date` 텍스트에서 ym 매칭, target 과 일치하는 카드 안에서만 day 검색
- 비활성 카드는 모든 td disabled 라 자연 skip

**(c) day 미발견 시 DOM dump (디버그 유지)** [search.py:193](../../../../ktx_watcher/korail/search.py)
- 진단 비용 낮음 (한 번만 실행) — 향후 사이트 변경 시 즉시 원인 파악 가능.

검증: `20:27:42 | 출발일 적용 OK: 2026-06-01(월) 08:00`.

---

## 5. 로컬 환경 — CDP user-data-dir placeholder

### 증상
- Chrome 디버그 인스턴스 기동에서 `WinError 123: 파일 이름, 디렉터리 이름 또는 볼륨 레이블 구문이 잘못되었습니다`.
- 워처 즉시 exit 1.

### 원인
`.env` 의 `KTXA_CDP_USER_DATA_DIR=C:\Users\<your-user>\chrome-ktx-watcher` — `<your-user>` 가 literal placeholder. Windows 파일 시스템이 `<` `>` 문자를 path 에 허용 안 함.

### 처리
실제 사용자명으로 치환:
```
KTXA_CDP_USER_DATA_DIR=C:\Users\USER\chrome-ktx-watcher
```
디렉토리도 사전 생성 (`mkdir -p`).

> **메모**: clone 받은 신규 환경에서 항상 발생. 스킬 1단계 환경 점검에 이 키 placeholder 검사 추가 고려.

---

## 6. 카드 정보 placeholder → 결제 강제 skip

### 증상
- `.env` 의 `PAY_CARD_NUM=0000-0000-0000-0000`, `PAY_ID6=000000` 등 placeholder.
- `KTXA_PAYMENT_MODE=true` 면 좌석 hold 후 결제 단계 진입했다가 실패 → 좌석 hold 풀림.

### 원인
신규 clone 환경에서 카드 정보 미설정. 워처는 그대로 결제 시도.

### 처리
스킬 6단계에서 PAY_* 값이 placeholder (`0000-` 같은 패턴) 이면 사용자에게 묻지 않고 `KTXA_PAYMENT_MODE=false` 로 강제 → 좌석 hold 후 사용자 수동 결제.

> **TODO**: 스킬에 PAY_* placeholder 자동 감지 로직 명시.

---

## 누적 변경 파일

| 파일 | 변경 요약 |
|---|---|
| `.env` | `KTXA_PAYMENT_MODE=false`, `KTXA_CDP_USER_DATA_DIR` 치환 |
| `.env.ktx` | 날짜/시각/윈도우/열차번호 |
| `ktx_watcher/korail/selectors.py` | `NOTICE_MODAL_*`, `WAITLIST_BUTTON`, `STANDING_BUTTON` 신규 |
| `ktx_watcher/korail/client.py` | `dismiss_notice_modal()` 신규 |
| `ktx_watcher/korail/search.py` | `_read_current_ym` / `_click_day` regex·다중 카드, priceBox 식별 위치 기반, 후보 필터 `status_kind` 분류, `navigate_to_search` polling dismiss, day-miss DOM dump |
| `ktx_watcher/korail/reserve.py` | row anchor / 액션 버튼 / success 키워드 status_kind 별 분기 |
| `ktx_watcher/main.py` | `kind=waitlist` 결제 단계 강제 skip |

## 검증 결과

- **5/29 KTX 121 (서울 08:12→부산 11:33)**: 매진 row → `kind=waitlist` → `예약대기신청` 버튼 클릭 → ✅ 예약대기 신청 완료
- **6/1 KTX 121 (08:12)**: 예약 가능 row → `kind=reserve` → `button.reservbtn` → ✅ 좌석 hold (10분 timer, 사용자 수동 결제)
