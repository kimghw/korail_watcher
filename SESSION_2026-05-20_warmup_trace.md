# 2026-05-20 air_watcher warm-up 트레이스 — 페이지·클릭·판단 기록

목적: KE 홈 위젯을 자동 클릭으로 `/booking/select-flight` 까지 진입해 Akamai 세션 확보.

## 1. 로그인 (✅ 성공)

| 단계 | 클릭 / 액션 | 페이지·상태 | 판단 / 코드 분기 |
|---|---|---|---|
| 1 | `page.goto("https://www.koreanair.com/")` | `/` (home), 로그아웃 indicator 없음 | `_is_logged_in()` false → 로그인 필요 |
| 2 | `page.goto("/login?returnUrl=%2F")` + `wait_for_selector("input[type=password]")` | `/login` | form hydration 대기 |
| 3 | shadow-piercing JS 로 `input[type=text]` / `input[type=password]` 에 ID/PW native setter 로 set | input 채워짐 (verify: `el.value === val`) | ID/PW 둘 다 OK |
| 4 | `_click_login_button()` — text="로그인" + width>200 인 button click | `/login` 그대로 (Akamai 검증 진행) | 25초 polling 시작 |
| 5 | "비밀번호 변경 안내" 모달 자동 dismiss (`90일 후에 변경` 클릭) | 모달 닫힘 | `_is_logged_in()` 재검사 |
| 6 | 로그아웃 indicator 발견 → 로그인 종료 | `/` 또는 `/login` (redirect 진행 중) | 성공 |

**로그인 부분은 안정. 다음 세션도 그대로 재사용 가능.**

---

## 2. Warm-up — 1차 시도 (1차 실패: 잘못된 페이지 도달)

목표: `/booking/select-flight/departure?...` (현금 운임)
도달: `/booking/select-award-flight/departure` (마일리지 운임)

| # | 클릭 / 액션 | 좌표·셀렉터 | 검증 결과 | 코드 판단 |
|---|---|---|---|---|
| 1 | home navigate (직전이 `/booking/select-award-flight`) | — | `/` 진입 | 직전 페이지 상관없이 home 강제 |
| 2 | `_ensure_trip_type("oneway")` — chip 라디오 클릭 | `label[for=chip-2]` 클릭 | `chip-1` 그대로 checked=true | **결정 1**: chip-2 라디오 자체를 .click() 해도 Angular 무반응. 라벨 클릭으로 우회 (작동) |
| 3 | `_ensure_fare_type("cash")` — 텍스트 매칭 | `text.includes('일반') && !includes('마일리지')` | 0건 매칭 → 3회 retry 후 warning 으로 skip | **이때 했어야**: 위젯 실제 텍스트 확인 후 키워드 결정. "일반" 은 KE 위젯에 없는 단어. |
| 4 | `_set_airport("origin", "CJU")` | `_widget_button("origin")` → swap button anchor 기반 | swap button "출발지와 도착지 바꾸기" 못 찾음 → row=[] → picker 안 열림 | **이때 했어야**: swap button 이 main DOM 에 없는 이유 = shadow DOM. shadow-piercing 으로 진짜 위젯 구조부터 확인. |
| 5 | warm-up 실패 종료 | — | — | 사용자에게 보고 |

### 1차 시도에서 놓친 점

- **위젯 전체가 Shadow DOM (`KDS-DIALOG`, `KDS-SWITCH` 커스텀 element) 인 걸 너무 늦게 알아챘다.**
  - cdp_book_final.py 의 `_widget_button` 코드는 shadow-piercing 을 이미 했었는데, 거기서 `swap.innerText.includes("출발지와 도착지 바꾸기")` 패턴은 여전히 유효. 단지 `_set_airport` 가 이 anchor 를 못 찾자 즉시 실패 처리.
  - 시작부터 shadow piercing 으로 KDS-DIALOG / KDS-SWITCH 의 attribute 들 (label-start, label-end, is-checked) 을 nuke 했어야 했다.

---

## 3. Warm-up — 2차 시도 (warm-up "통과" 했지만 award-flight 진입)

1차 실패 분석 후 다음 변경:
- shadow DOM piercing 으로 모든 button 검색
- `_widget_button` 의 swap anchor 가 KDS-DIALOG 내부에 있는 진짜 구조로 작동 확인

| # | 클릭 / 액션 | 좌표·셀렉터 | 검증 결과 | 코드 판단 |
|---|---|---|---|---|
| 1 | home navigate | — | `/` | OK |
| 2 | `_ensure_trip_type` | label[for=chip-2] | chip-2 checked | OK |
| 3 | `_ensure_fare_type("cash")` | (기존 키워드 "일반") | 매칭 없음 → warning skip | **놓침**: 여전히 fare 탭 실제 텍스트 확인 안 했음 |
| 4 | `_set_airport("origin")` | shadow `ui-fromto__button -order1` x=345 y=383 | 텍스트가 "출발지 SEL 서울/모든 공항" — CJU 아님 | picker 열림 |
| 5 | picker 안 "제주" 입력 → CJU 결과 클릭 | shadow-piercing input + 결과 li | `_airport_matches` → 출발지 CJU 확정 | OK |
| 6 | `_set_airport("dest")` | x=542 y=204 "To 도착지" | 도착지 picker 열림 → 김포→GMP 선택 | OK |
| 7 | `_set_depart_date(2026-05-29)` | date button click → picker open → ui-switch 편도 click → 29일 셀 click | cls `-start` 확인 | OK |
| 8 | `_find_search_button()` → click | x=1581 y=204 (via 'cta' fallback) | URL=`/booking/select-award-flight/departure` | **결정 2**: 검색은 동작 (URL 변경) 하지만 award 페이지. fare 탭 안 누른 게 원인. |

### 2차 시도에서 놓친 점

- **`_ensure_fare_type` 의 warning skip 을 "치명적이지 않다" 고 판단한 게 잘못.** KE 가 fare 탭 안 바꾸면 마지막 사용 탭 그대로 사용 → 우리가 cash 원해도 사용자 계정의 마지막 검색이 miles 였으면 그대로 miles 로 검색됨.
- 위젯의 fare 탭 실제 텍스트 ("예매" / "마일리지 예매") 와 KDS-SWITCH 의 `is-checked` 속성 토글 패턴을 캡쳐로 확인했어야 했음.

---

## 4. Warm-up — 3차 시도 (fare keyword "예매" 로 수정)

| # | 클릭 / 액션 | 좌표·셀렉터 | 검증 결과 | 코드 판단 |
|---|---|---|---|---|
| 3 | `_ensure_fare_type("cash")` — want_kw="예매" / avoid_kw="마일리지" | shadow-piercing button text 매칭 | `'항공편 예매'` (`ui-quickbooking__button`, ariaSel='true') 매칭됨 — 섹션 nav 헤더 | **놓침**: "예매" 라는 substring 이 "항공편 예매" 에도 매칭. text === '예매' 로 정확 일치 검사 했어야. |
| 8 | search btn click | x=1581 y=204 | URL → award-flight | 동일 문제 |

### 3차 시도에서 놓친 점

- substring vs exact match. KE 위젯엔 다양한 곳에 "예매" 포함된 텍스트가 있다 (`항공편 예매`, `예매`, `마일리지 예매`, `이어서 예매`...). 정확 일치 또는 부모 컨테이너 기반 필터 필수.

---

## 5. Warm-up — 4차 시도 (KDS-SWITCH `is-checked` 토글)

shadow-piercing 으로 fare 탭의 실제 구조 파악:

```
KDS-SWITCH (label-start="예매", label-end="마일리지 예매")
  └─ KDS-SWITCH_1 (is-checked="true|false")
       ├─ SPAN "예매"        ← cash 클릭 좌표
       └─ SPAN "마일리지 예매"  ← miles 클릭 좌표
```

- `is-checked='true'` → 마일리지
- `is-checked='false'` → 예매

| # | 클릭 / 액션 | 좌표·셀렉터 | 검증 결과 | 코드 판단 |
|---|---|---|---|---|
| 3 | KDS-SWITCH 좌측 (label-start) SPAN 좌표 click | x=315 y=308 (스크롤 위치 따라 변동) | 첫 click 후 `is-checked` 그대로 true. 둘째 click 후 false. | OK 됐는데 ── |
| 4 | `_set_airport("origin")` | 다음 step | **Execution context destroyed** | **결정 3**: fare 토글이 비동기 페이지 nav 를 일으킴. 토글 후 안정화 대기 안 했음. |

→ 토글 후 `wait_for_load_state("domcontentloaded", timeout=8s)` + `sleep(2)` 추가.

---

## 6. Warm-up — 5차 시도 (토글 후 안정화)

| # | 클릭 / 액션 | 결과 |
|---|---|---|
| 3 | fare KDS-SWITCH toggle → is-checked=false 확정 | OK |
| 3a | wait_for_load_state + sleep(2) | OK |
| 4-7 | origin / dest / date 모두 통과 | 셀 클래스 `-start -end` 확인 |
| 8 | `_find_search_button()` → x=1581 y=204 | click 시점에 button.disabled=False ✓ |
| 9 | `_wait_select_flight(timeout_s=25)` | **25초 timeout → URL=`/` (home) 그대로** |

### 결정적 발견 (5차에서 캡쳐 후)

캡쳐 + shadow-piercing probe 결과:
- 실제 검색 버튼 위치: **x=1522 y=360 w=118** (`ui-button -basic -cta -small`)
- `_find_search_button` 이 잡은 좌표 x=1581 y=204 의 버튼은 **다른 CTA 버튼** (위젯 외부, 같은 클래스 우연히 매칭)

**원인**: `_find_search_button` 이 단순히 클래스 `ui-button -basic -cta -small` 패턴에 일치하는 첫 버튼을 잡았는데, 이 클래스는 KE 사이트 곳곳의 작은 CTA 버튼에 공통. 위젯의 검색 버튼과 외부 다른 버튼이 우연히 같은 클래스 → 잘못된 좌표 click.

### 이때 했어야 했던 것

- 검색 버튼을 위젯 컨테이너 내부로 한정해서 찾기:
  - `KE-MAIN-QUICK-BOOKING` 또는 `ui-quickbooking__panel` 자손인 button
  - 또는 `aria-label` 정확 일치 (button 의 aria-label 이 "항공편 검색" 일 가능성)
  - 또는 위젯 row 의 가장 오른쪽 button (다른 button 들 좌표 평균과 비교)

---

## 다음에 할 작업 (즉시)

1. `_find_search_button` 을 위젯 컨테이너 기반 검색으로 재작성:
   ```js
   // KE-MAIN-QUICK-BOOKING 내부에서 가장 오른쪽 CTA 버튼
   const panel = document.querySelector('ke-main-quick-booking, [id=main-booking-widget]');
   const btns = panel.querySelectorAll('button.ui-button.-basic.-cta');
   // 또는 aria-label="항공편 검색"
   ```
2. 검색 버튼 click 후 navigation 대기 (`page.expect_navigation` 또는 polling 으로 URL 변경 감지)
3. URL `/booking/select-flight/...` 진입 확인 시 warm-up 성공
4. 그 페이지에서 air-bounds XHR POST → 200 검증

## 일반 원칙 (적용 부족)

- **CLAUDE.md 의 "동작 검증 — 의도한 반응이 없으면 화면을 캡쳐해서 직접 확인"** 을 매 단계 안 했다. 1·2·3차 모두 grep/probe 만 하다가 4차에서야 캡쳐로 진짜 구조 파악.
- 향후 위젯 작업은 매 단계 후 `Page.captureScreenshot` + 시각 확인 의무화.

---

## 추가 검증 (5차 이후 후속)

### fare 토글 매핑 보정
- 캡쳐로 시각 확인: 토글 후 `is-checked='false'` 일 때 **마일리지 예매** 가 선택됨.
- 즉 `is-checked='true'` = cash, `'false'` = miles 로 **매핑 반대였음**. `_ensure_fare_type` 의 want_checked 매핑 수정 (`true if cash`).

### 직접 navigate 도 막힘 (Akamai page-block)
- `page.goto("/booking/select-flight/departure?bookingType=R&...&tripType=OW")` 실행
- URL 은 select-flight 로 정상 변경 (`location.href` 확인)
- 그러나 **페이지 body 가 완전히 빈 상태** (스크린샷 = 전체 흰색)
- 즉 Akamai 는 직접 navigate 의 URL 변경은 허용하지만 페이지 HTML/JS 컨텐츠 로딩을 차단

### 위젯 경유로 도달한 booking 페이지에서도 air-bounds 막힘
- 5차 후속 시도에서 위젯 클릭 → `/booking/calendar-fare-bonus` 진입 (마일리지 calendar 모드)
- 페이지 자체는 정상 로드되어 "출발지 CJU / 도착지 GMP / 가는날 / 오는날 tab" 등 정상 렌더링
- 동일 컨텍스트에서 cash air-bounds XHR → **여전히 403** (Akamai reference 다른 ID)

### 핵심 결론

세 가지 다른 경로 (직접 goto / 위젯 거쳐 calendar / 위젯 거쳐 award-flight) 에서 모두 air-bounds = 403.
공통점: 모든 요청이 **Playwright/CDP-attached Chrome 의 Runtime.evaluate 컨텍스트**에서 발사된 XHR.

가설: Akamai Bot Manager 가 **fetch/XHR 요청의 stack trace 또는 caller 컨텍스트** 를 검사. 정상 user script 가 만든 XHR 와, `Runtime.evaluate` 가 주입한 IIFE 내부에서 만든 XHR 의 시그너처가 다르게 보일 가능성.

이 가정이 맞다면 Playwright/CDP 로는 KE air-bounds 직접 호출이 **구조적으로 안정 불가능**. 대안:
1. **위젯 검색 결과를 페이지 DOM 에서 파싱** — KE 가 자체 air-bounds 를 호출해 화면에 그린 결과를 추출. (api 안 거치고 결과만 추출)
2. **모바일 앱 API 흉내** (X-AKamai 토큰 / SDK 헤더) — 위험성 있고 분석 필요.
3. **Chrome extension 으로 페이지 컨텍스트에서 XHR** — Playwright 가 아닌 진짜 사용자 페이지에서 실행되는 코드라 fingerprint 차이 없을 가능성.

## 오늘 세션 종료 시점

- 코드: `_ensure_fare_type` KDS-SWITCH 토글 패턴 + `is-checked` 매핑 보정 적용.
- 검증: 위젯 워밍업으로 booking 페이지(calendar-fare-bonus / select-award-flight) 진입까지 가능.
- 막힌 곳: air-bounds XHR 가 어떤 페이지에서도 403.
- 다음 우선순위: 위 가설 1번 (페이지 DOM 파싱) 으로 방향 전환 또는 사용자 결정 대기.
