---
name: korean_air
description: 대한항공(Korean Air) 예매 워크플로우. 사용자가 항공 예매 관련 발언("air", "대한항공", "korean air", "ke", "비행기", "항공권", "마일리지", "보너스 항공권", "ICN", "GMP", IATA 코드, 노선명) 을 하면 시작. 절차 — (1) TRIP_TYPE/FARE_TYPE 결정 (2) 계정 확인 (필수, 로그인 없이는 진행 안 함) (3) 출발/도착/날짜/시간/좌석/인원 수집 (4) 검색 1회 실행으로 상태 확인 (5) 항공편 선택 (6) 알림 설정 (필요시 korail_alarm 호출) (7) 워처 실행. 결제는 좌석 hold 이후 사용자가 수동 진행.
---

# korean_air — Korean Air 예매 워크플로우 (CDP attach)

KE 는 KTX/SRT 와 달리 (1) 국내/국제 분기, (2) 보너스(마일리지)/일반운임 분기, (3) 다양한 캐빈클래스, (4) 라운드트립이 있다. 결제 자동화는 하지 않는다 — 좌석 hold (10분 timer) 까지만 자동.

**로그인 필수 — 익명/비로그인 경로는 지원하지 않는다.** `KOREAN_AIR_MODE` (search/reserve) 에 관계없이 워처 부팅 시점에 `ensure_logged_in()` 으로 KE 세션을 먼저 확보한다. `KOREAN_AIR_USER` / `KOREAN_AIR_PASS` 가 비어 있으면 2단계에서 즉시 수집하고, 못 받으면 워크플로우 중단.

### 파일 라우팅

| 키 종류 | 파일 |
|---|---|
| **여정 키** (`KOREAN_AIR_TRIP_TYPE/FARE_TYPE/ORIGIN/DEST/DEPART_DATE/RETURN_DATE/DEPART_TIMES/DEPART_TIME_WINDOW/RETURN_TIMES/RETURN_TIME_WINDOW/CABIN/PAX_ADULT/PAX_CHILD/PAX_INFANT/TOLERANCE_MIN/FLIGHT_NO`) | `c:\Users\kimghw\korail_watcher\.env.korean_air` |
| **그 외** (계정, KOREAN_AIR_MODE, KOREAN_AIR_ONCE, KOREAN_AIR_CDP_*, KOREAN_AIR_POLL_*, KOREAN_AIR_LOG_*, TEAMS_*, RAIL_RUN_MODE 등) | `c:\Users\kimghw\korail_watcher\.env` |

`.env.korean_air` 는 git tracked (`.env.ktx`/`.env.srt` 와 동일 정책). 워처가 `ENV_FILES` 맨 앞에서 우선 로드한다 (`korean_air_watcher/config.py`).

### ⚠ KE 홈 위젯은 가짜로 가득 — 함부로 만지지 말 것

KE 홈 검색 위젯은 일반 HTML form 처럼 보이지만 KDS (Korean Air Design System) 커스텀 컴포넌트가 깔려 있어 평범한 `click()`/`fill()` 으로는 안 먹는다. 사용자/스킬 흐름이 위젯을 새로 만지려 할 때마다 아래 함정 매번 부딪힘 — **가능하면 위젯 안 만지고 사용자가 띄워둔 select-flight 페이지에서 `page.reload()` 만**으로 폴링한다 (`_ensure_select_flight_referer` 구현 참고).

| 함정 | 메커니즘 | 회피 |
|---|---|---|
| `chip-X` 가짜 라디오 | radio input 의 `checked` 속성이 UI 실상과 어긋남 | `is-checked` / `aria-checked` 또는 class 변화로 폴링 |
| `ui-switch` 토글 클릭 무시 | KDS-SWITCH 가 일반 `click()` 흡수 — pointerdown→up 또는 드래그 필요 | `mouse.down(x,y)→mouse.up(x,y)` 시퀀스. 더 쉬운 우회: URL 직접 진입 (`/booking/select-flight` vs `/booking/select-award-flight`) |
| fare-type 탭처럼 보이지만 탭 아님 | fare 는 토글이지 탭이 아님 — 탭으로 찾으면 매번 fail | ui-switch 트랙 좌표 또는 URL 분기 |
| `Escape` = discard | picker 안 Escape 는 변경 사항 버림 (열린 picker 자체가 닫혀있던 값은 보존) | 외부 영역 click 또는 picker 내부 "적용"/"확인" 클릭으로 닫음 |
| `page.url` stale | CDP 의 `pg.url` 캐시가 navigation 뒤에도 갱신 안 됨 | `pg.evaluate("location.href")` 또는 특정 element 존재로 판단 |
| KE 의 home redirect | idle 또는 봇 의심 상태에서 결과 페이지를 home 으로 강제 redirect | reload-only 폴링 + 이탈 시에만 warm-up 1회 |
| Akamai 403 (`/api/rp/dx/search/air-bounds`) | bot fingerprint 로 우리 fetch 만 차단, KE 자체 XHR 은 통과 | API 포기, DOM scrape (`[class*='itinerary']` + parent 8단계 ancestor walk) |
| 매진 판정 false positive | itinerary 카드 자체엔 fare 정보 없음 — "매진" 단어 검색해도 False | parent 8단계까지 walk 해서 매진/미운영/마일/원 단어 포함 ancestor 의 inner_text 사용 |

이미 발생했던 실제 사례와 검증된 fix 는 [references/troubleshooting.md](references/troubleshooting.md) 에 자세히. 새로 위젯 자동화를 만진다면 그 문서부터.

---

## ⚠ 사전 조건 — 동작 환경

**이 스킬은 `https://github.com/kimghw/korail_watcher.git` 를 clone 받은 디렉토리 안에서만 동작한다.** `korean_air_watcher`, `team_mcp` 모듈이 없으면 4·7 단계가 무조건 실패하므로 다른 위치에서는 **시작하지 않는다**.

### 워크플로우 시작 전 점검 (필수, 1회)

1. **repo 매칭** — `git -C "<cwd>" remote get-url origin` 가 `kimghw/korail_watcher.git` 인지 확인.
2. **필수 폴더 존재** — cwd 에 `korean_air_watcher/`, `team_mcp/` 가 있어야 함.

둘 중 하나라도 실패하면 사용자에게 그대로 보여준다:

> 이 스킬은 `https://github.com/kimghw/korail_watcher.git` 디렉토리에서만 동작합니다.
> 현재 위치: `<cwd>` — `korean_air_watcher` / `team_mcp` 모듈이 없어 진행할 수 없습니다.
>
> 해결:
> - `git clone https://github.com/kimghw/korail_watcher.git`
> - 또는 해당 폴더로 이동 후 다시 호출
> - 오래됐을 수 있으면 `git pull` 후 재시도

---

## 핵심 규칙

- 사용자가 한 번에 여러 정보를 주면 ("6월 1일 김포-제주 09:00 1명 이코노미") 해당 단계 skip.
- 빠진 것만 `AskUserQuestion` 으로 묻기. 짝지어진 입력(출발/도착, 날짜/시각, 캐빈/인원 등)은 한 호출로 묶는다.
- 사용자가 명시한 값은 라운딩/안전화 금지.
- 값은 따옴표 없이 저장 (예: `KOREAN_AIR_ORIGIN=ICN`).
- IATA 3-letter 공항코드로 정규화 (`김포` → `GMP`, `제주` → `CJU`, `인천` → `ICN`, `김해` → `PUS`).
- 비밀번호 / 카드정보 / 마일리지 잔액 stdout 출력 금지.

---

## 1단계 — TRIP_TYPE / FARE_TYPE 결정 + Fast-path

세션 변수 두 개를 먼저 정한다. `.env` 에 저장하는 키이기도 하다 (`KOREAN_AIR_TRIP_TYPE`, `KOREAN_AIR_FARE_TYPE`).

### Fast-path

사용자가 "그냥 예약해줘 / env 그대로 / 바로" 발화 → 2~6 단계 skip, 현재 설정으로 7단계 실행. `.env` 의 `KOREAN_AIR_ONCE=false` 만 보장하고 워처 띄움. 핵심값 한 블록 요약 후 묻지 않고 실행.

### AskUserQuestion (두 질문 묶음)

질문 1 — TRIP_TYPE:
- `oneway` (편도)
- `roundtrip` (왕복) — 워처가 매 iteration `[갈때]` outbound, `[올때]` return 두 검색을 번갈아 수행. 한 쪽 알림 발송하면 그 쪽은 dedup 되고 나머지만 계속 폴링. 둘 다 알림 완료되면 종료. 각 leg 가 별도 leg 라벨로 알림.
- `multi` (다구간) — 현재 워처는 미지원, 선택 시 "다구간은 수동 진행하세요" 알림 후 종료

질문 2 — FARE_TYPE:
- `cash` (일반운임)
- `miles` (보너스/마일리지)
- `both` — 워처가 두 운임 모두 폴링, miles 우선

명시 발화가 있으면 질문 skip.

---

## 2단계 — 계정 확인 / 입력 (필수)

워처는 부팅 시 `ensure_logged_in()` 으로 KE 에 자동 로그인한다. 따라서 `KOREAN_AIR_USER` / `KOREAN_AIR_PASS` 는 **반드시** 채워져 있어야 한다 — 익명 진행 불가.

`.env` 의 키:

| 키 | 의미 |
|---|---|
| `KOREAN_AIR_USER` | 스카이패스 번호 또는 이메일 |
| `KOREAN_AIR_PASS` | 비밀번호 |

- 둘 다 비어있으면 직접 받기. 사용자가 거부하면 워크플로우 중단 ("로그인 없이는 진행할 수 없습니다").
- 채워져 있으면 ID 마스킹 (`ABC***@krs.co.kr` 또는 `1234***`) 후 `AskUserQuestion`:
  - 질문: "현재 저장된 KE 계정 (ID: ABC***) 으로 진행할까요?"
  - 옵션: `이 계정으로 진행` / `다른 계정 입력`

> 비밀번호 값은 사용자에게 그대로 다시 보여주지 말 것.

---

## 3단계 — 여정 정보 수집

저장 키 (`.env.korean_air`):

| 의미 | 키 | 비고 |
|---|---|---|
| 출발 공항 | `KOREAN_AIR_ORIGIN` | IATA 3-letter (e.g. ICN, GMP) |
| 도착 공항 | `KOREAN_AIR_DEST` | 동일 |
| 출발 날짜 | `KOREAN_AIR_DEPART_DATE` | YYYY-MM-DD |
| 출발 선호 시각 | `KOREAN_AIR_DEPART_TIMES` | HH:MM 쉼표 |
| 출발 허용 시간대 | `KOREAN_AIR_DEPART_TIME_WINDOW` | `HH:MM,HH:MM` |
| 귀국 날짜 | `KOREAN_AIR_RETURN_DATE` | roundtrip 만 |
| 귀국 선호 시각 | `KOREAN_AIR_RETURN_TIMES` | roundtrip 만 |
| 귀국 허용 시간대 | `KOREAN_AIR_RETURN_TIME_WINDOW` | roundtrip 만 |
| 캐빈 | `KOREAN_AIR_CABIN` | `economy`/`prestige`/`first` 또는 빈 값(ANY) |
| 성인 | `KOREAN_AIR_PAX_ADULT` | 기본 1 |
| 소아 | `KOREAN_AIR_PAX_CHILD` | 기본 0 |
| 유아 | `KOREAN_AIR_PAX_INFANT` | 기본 0 |
| 시간 오차(분) | `KOREAN_AIR_TOLERANCE_MIN` | 기본 30 |
| 항공편 번호 (선택) | `KOREAN_AIR_FLIGHT_NO` | e.g. `KE001` — 있을 때만 4단계 검색 |

### 3-1) 출발지 / 도착지 — AskUserQuestion (두 슬롯)

**국내선 (TRIP 거리·정황상 한국 내 노선)** 옵션:
- 출발: `GMP (김포)`, `ICN (인천)`, `CJU (제주)`, `PUS (부산/김해)` + Other
- 도착: `CJU`, `PUS`, `GMP`, `TAE (대구)` + Other

**국제선** 옵션 (popular):
- 출발: `ICN (인천)`, `GMP (김포)`, `PUS (부산)`, `CJU (제주)` + Other
- 도착: `NRT (나리타)`, `LAX (LA)`, `JFK (뉴욕)`, `CDG (파리)` + Other

Other 로 한글 도시명/공항명 들어오면 IATA 로 매핑. 매핑 실패 시 한 줄 알림 + 재질문.

### 3-2) 날짜 + 시간대 — 자유 입력

`korail` 과 동일 파싱 규칙:
- 단일 시각 → `*_TIMES=HH:MM`, `*_TIME_WINDOW` 는 ±30분.
- 구간 → `*_TIME_WINDOW=시작,끝`, `*_TIMES` 는 중앙값.

Roundtrip 이면 출발/귀국 한 번에 묻는다:
> "출발과 귀국 일정을 한 번에 알려주세요 (예: '6월 1일 09:00 출발, 6월 5일 18:00~21:00 귀국')"

### 3-3) 캐빈 — AskUserQuestion

- `Economy`
- `Prestige (비즈니스)`
- `First`
- `상관 없음 (ANY)` → `KOREAN_AIR_CABIN=`

보너스(miles) 면 First/Prestige 가 풀리기 어려우니 "어떤 클래스라도 잡으면 알림"을 권유. 단, 사용자가 명시했으면 그 값 그대로.

### 3-4) 인원

명시 안 했으면 기존 값 유지. 한 줄로 받으면 즉시 분해 ("성인 2 소아 1" → `ADULT=2`, `CHILD=1`).

### 3-5) 항공편 번호 (선택)

사용자가 알면 `KOREAN_AIR_FLIGHT_NO` 에 저장. 4단계 우선순위에 사용.

---

## 4단계 — 검색 1회 실행 (조건부)

**전제: `KOREAN_AIR_FLIGHT_NO` 가 있을 때만.** 없으면 4·5단계 skip, 워처가 시간 매칭으로 잡도록 둠.

```bash
KOREAN_AIR_MODE=search KOREAN_AIR_ONCE=true python -m korean_air_watcher.main
```

stdout 에서 "후보 발견:" 라인 파싱. 추출 실패하면 로그 그대로 보여주고 진행.

---

## 5단계 — 항공편 선택 (AskUserQuestion)

**4단계 skip 되었으면 이 단계도 skip.**

후보 (최대 4개) 를 옵션으로 제시.
- 라벨: `"KE1207 09:00→10:10 ICN→CJU Economy"`
- description: `잔여석 / Saver 보너스 / 일반운임 가격`
- 후보 1개면 자동 확정.
- 매칭되는 `KOREAN_AIR_FLIGHT_NO` 가 있으면 첫 옵션으로.
- 후보 0개면 "이 조건으로 잡히는 편 없음 — 다시?" 묻고 3단계로.

선택 후 `KOREAN_AIR_DEPART_TIMES` 를 그 시각 하나로 좁히고 `KOREAN_AIR_DEPART_TIME_WINDOW` 도 ±15분으로 좁힘 (`.env.korean_air`).

---

## 6단계 — 알림 설정

`AskUserQuestion`:
- 질문: "Teams 알림을 받으시겠어요?"
- 옵션: `알림 받기` / `알림 안 받기`

### 알림 받기 선택 시

`.env` 의 키 검증 (KTX/SRT 와 공유):
- `TEAMS_ENABLED=true`
- `TEAMS_USER_EMAIL`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, `AZURE_TENANT_ID`
- `DB_PATH` 의 auth.db 에 토큰 존재

하나라도 빠지면 → **`korail_alarm` 스킬 invoke**. (같은 인증, 같은 prefix 만 `[AIR WATCHER]` 로 바뀜)

성공 시 본 워크플로우 계속. 실패 시: "알림 인증 실패 — 알림 없이 진행할까요?" 묻고 분기.

### 알림 안 받기 선택 시

`.env` 의 `TEAMS_ENABLED=false` 설정.

---

## 7단계 — 워처 실행

### 무한 폴링이 기본 설계 (멈추지 않는다)

- 좌석은 풀렸다 닫혔다 반복하므로 한 번 잡았다고 종료하지 않는다.
- 양쪽 leg(왕복) 매 iteration 모두 폴링. 같은 항공편/캐빈 조합은 `seen_flights` dedup 으로 중복 알림 차단.
- 종료 조건은 오직 사용자 신호(SIGINT/Ctrl+C) 또는 fatal site-layout 변경.
- `KOREAN_AIR_ONCE=true` 는 검증·디버그 전용 — 워크플로우는 항상 `false` 로 강제 (`.env`). 사용자가 명시적으로 "한 번만 / 1회 / 검증용" 발화해야만 `true` 허용.

### 실행 명령

```bash
python -m korean_air_watcher.main
```

### 실행 모드 (background / foreground)

`.env` 의 `RAIL_RUN_MODE` 로 결정 (KTX/SRT 와 공유). 묻지 않음.

| 값 | 동작 |
|---|---|
| `background` 또는 비어 있음 | `run_in_background=true` + `Monitor` 로 감시 |
| `foreground` | `run_in_background=false`, 워처가 끝날 때까지 다른 작업 불가 |

`Monitor` 호출 시 `persistent: true`, `timeout_ms` 는 사용자가 명시적으로 시간을 준 경우만 사용. 임의 5분/30분/1시간으로 자르지 말 것.

### CDP 포트 분리

`.env` 의 `KOREAN_AIR_CDP_PORT` 는 기본 `9446` — KTX(`9444`)/SRT(default) 와 겹치지 않게. `KOREAN_AIR_CDP_USER_DATA_DIR` 도 별도 (`C:\Users\kimghw\chrome-korean-air-watcher` 권장). 동시에 KTX/SRT 워처 띄워도 충돌 없음.

---

## 좌석 hold 이후 — 결제는 수동

KE 워처는 좌석 hold(보통 10분 timer) 까지만 자동화한다. 알림에 "결제 페이지 진입 — 10분 안에 수동 결제" 포함. 자동 결제 안 함.

이유:
- KE 결제는 보안 모듈(ISP/안심클릭 등) 이 매번 다르고 본인인증 SMS 들어가는 경우가 잦아 안정적 자동화 어려움
- 마일리지 결제는 정책상 사람 확인 필요한 경우 다수

PAY_* 키는 KE 에서 사용하지 않는다 — KTX/SRT 전용으로 두자.

---

## 하지 말 것

- `AZURE_*` / `DB_PATH` / `KOREAN_AIR_CDP_*` 의 포트·path 임의 수정 금지.
- `.env.share` 는 템플릿 — 손대지 않음.
- `.env` 에 여정 키 (`KOREAN_AIR_ORIGIN` 등) 쓰지 말 것. 여정은 무조건 `.env.korean_air`.
- 사용자 명시값 라운딩 금지.
- 비밀번호 / 마일리지 잔액 stdout 출력 금지.
- 사용자 발화에 "취소/삭제" 가 있으면 `.env` / `.env.korean_air` 수정 안 하고 무엇을 지울지 다시 묻기.

---

## 부록 — 자주 쓰는 IATA 매핑

### 국내선
| 도시/한글 | IATA | 비고 |
|---|---|---|
| 김포 | GMP | 서울 국내선 메인 |
| 인천 | ICN | 국제선 메인, 일부 국내선 |
| 김해/부산 | PUS | |
| 제주 | CJU | |
| 대구 | TAE | |
| 청주 | CJJ | |
| 광주 | KWJ | |
| 울산 | USN | |
| 여수 | RSU | |
| 양양 | YNY | |
| 포항경주 | KPO | |
| 사천 | HIN | |

### 국제선 — KE 직항 인기
| 도시 | IATA |
|---|---|
| 도쿄 나리타 | NRT |
| 도쿄 하네다 | HND |
| 오사카 | KIX |
| 후쿠오카 | FUK |
| 베이징 | PEK |
| 상하이 푸동 | PVG |
| 홍콩 | HKG |
| 방콕 | BKK |
| 싱가포르 | SIN |
| LA | LAX |
| 뉴욕 JFK | JFK |
| 샌프란시스코 | SFO |
| 파리 | CDG |
| 런던 | LHR |
| 프랑크푸르트 | FRA |
| 시드니 | SYD |

`Other` 입력은 위 매핑 + 추가 도시명 휴리스틱으로 변환. 실패 시 재질문.

---

## 빠른 예시

입력:
> 6월 1일 김포에서 제주, 09:00, 1명, 이코노미, 보너스로

처리:
1. TRIP_TYPE=`oneway` (귀국 언급 없음 — 묻고 확정), FARE_TYPE=`miles` (보너스 명시).
2. 계정 — 마스킹 보여주고 한 번 확인 (`.env`).
3. 출발 `GMP`, 도착 `CJU`, 날짜 `2026-06-01`, TIMES `09:00`, TIME_WINDOW `08:30,09:30`, CABIN `economy`, PAX_ADULT `1`. → **`.env.korean_air` 일괄 갱신**.
4. `KOREAN_AIR_FLIGHT_NO` 없음 → 4·5단계 skip.
5. (skip)
6. 알림 받기/안 받기 → `.env` 의 `TEAMS_ENABLED`.
7. 실행 → 워처가 `KOREAN_AIR_TIME_WINDOW` 안의 09:00 ±30분 보너스석 폴링.
