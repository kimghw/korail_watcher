---
name: air
description: 대한항공(Korean Air) 예매 워크플로우. 사용자가 항공 예매 관련 발언("air", "대한항공", "korean air", "ke", "비행기", "항공권", "마일리지", "보너스 항공권", "ICN", "GMP", IATA 코드, 노선명) 을 하면 시작. 절차 — (1) TRIP_TYPE/FARE_TYPE 결정 (2) 계정 확인 (3) 출발/도착/날짜/시간/좌석/인원 수집 (4) 검색 1회 실행으로 상태 확인 (5) 항공편 선택 (6) 알림 설정 (필요시 korail_alarm 호출) (7) 워처 실행. 결제는 좌석 hold 이후 사용자가 수동 진행.
---

# air — Korean Air 예매 워크플로우 (CDP attach)

KE 는 KTX/SRT 와 달리 (1) 국내/국제 분기, (2) 보너스(마일리지)/일반운임 분기, (3) 다양한 캐빈클래스, (4) 라운드트립이 있다. 결제 자동화는 하지 않는다 — 좌석 hold (10분 timer) 까지만 자동.

### 파일 라우팅

| 키 종류 | 파일 |
|---|---|
| **여정 키** (`AIR_TRIP_TYPE/FARE_TYPE/ORIGIN/DEST/DEPART_DATE/RETURN_DATE/DEPART_TIMES/DEPART_TIME_WINDOW/RETURN_TIMES/RETURN_TIME_WINDOW/CABIN/PAX_ADULT/PAX_CHILD/PAX_INFANT/TOLERANCE_MIN/FLIGHT_NO`) | `c:\Users\kimghw\korail_watcher\.env.air` |
| **그 외** (계정, AIR_MODE, AIR_ONCE, AIR_CDP_*, AIR_POLL_*, AIR_LOG_*, TEAMS_*, RAIL_RUN_MODE 등) | `c:\Users\kimghw\korail_watcher\.env` |

`.env.air` 는 git tracked (`.env.ktx`/`.env.srt` 와 동일 정책). 워처가 `ENV_FILES` 맨 앞에서 우선 로드한다 (`air_watcher/config.py`).

---

## ⚠ 사전 조건 — 동작 환경

**이 스킬은 `https://github.com/kimghw/korail_watcher.git` 를 clone 받은 디렉토리 안에서만 동작한다.** `air_watcher`, `team_mcp` 모듈이 없으면 4·7 단계가 무조건 실패하므로 다른 위치에서는 **시작하지 않는다**.

### 워크플로우 시작 전 점검 (필수, 1회)

1. **repo 매칭** — `git -C "<cwd>" remote get-url origin` 가 `kimghw/korail_watcher.git` 인지 확인.
2. **필수 폴더 존재** — cwd 에 `air_watcher/`, `team_mcp/` 가 있어야 함.

둘 중 하나라도 실패하면 사용자에게 그대로 보여준다:

> 이 스킬은 `https://github.com/kimghw/korail_watcher.git` 디렉토리에서만 동작합니다.
> 현재 위치: `<cwd>` — `air_watcher` / `team_mcp` 모듈이 없어 진행할 수 없습니다.
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
- 값은 따옴표 없이 저장 (예: `AIR_ORIGIN=ICN`).
- IATA 3-letter 공항코드로 정규화 (`김포` → `GMP`, `제주` → `CJU`, `인천` → `ICN`, `김해` → `PUS`).
- 비밀번호 / 카드정보 / 마일리지 잔액 stdout 출력 금지.

---

## 1단계 — TRIP_TYPE / FARE_TYPE 결정 + Fast-path

세션 변수 두 개를 먼저 정한다. `.env` 에 저장하는 키이기도 하다 (`AIR_TRIP_TYPE`, `AIR_FARE_TYPE`).

### Fast-path

사용자가 "그냥 예약해줘 / env 그대로 / 바로" 발화 → 2~6 단계 skip, 현재 설정으로 7단계 실행. `.env` 의 `AIR_ONCE=false` 만 보장하고 워처 띄움. 핵심값 한 블록 요약 후 묻지 않고 실행.

### AskUserQuestion (두 질문 묶음)

질문 1 — TRIP_TYPE:
- `oneway` (편도)
- `roundtrip` (왕복)
- `multi` (다구간) — 현재 워처는 미지원, 선택 시 "다구간은 수동 진행하세요" 알림 후 종료

질문 2 — FARE_TYPE:
- `cash` (일반운임)
- `miles` (보너스/마일리지)
- `both` — 워처가 두 운임 모두 폴링, miles 우선

명시 발화가 있으면 질문 skip.

---

## 2단계 — 계정 확인 / 입력

`.env` 의 키:

| 키 | 의미 |
|---|---|
| `AIR_USER` | 스카이패스 번호 또는 이메일 |
| `AIR_PASS` | 비밀번호 |

- 둘 다 비어있으면 직접 받기.
- 채워져 있으면 ID 마스킹 (`ABC***@krs.co.kr` 또는 `1234***`) 후 `AskUserQuestion`:
  - 질문: "현재 저장된 KE 계정 (ID: ABC***) 으로 진행할까요?"
  - 옵션: `이 계정으로 진행` / `다른 계정 입력`

> 비밀번호 값은 사용자에게 그대로 다시 보여주지 말 것.

---

## 3단계 — 여정 정보 수집

저장 키 (`.env.air`):

| 의미 | 키 | 비고 |
|---|---|---|
| 출발 공항 | `AIR_ORIGIN` | IATA 3-letter (e.g. ICN, GMP) |
| 도착 공항 | `AIR_DEST` | 동일 |
| 출발 날짜 | `AIR_DEPART_DATE` | YYYY-MM-DD |
| 출발 선호 시각 | `AIR_DEPART_TIMES` | HH:MM 쉼표 |
| 출발 허용 시간대 | `AIR_DEPART_TIME_WINDOW` | `HH:MM,HH:MM` |
| 귀국 날짜 | `AIR_RETURN_DATE` | roundtrip 만 |
| 귀국 선호 시각 | `AIR_RETURN_TIMES` | roundtrip 만 |
| 귀국 허용 시간대 | `AIR_RETURN_TIME_WINDOW` | roundtrip 만 |
| 캐빈 | `AIR_CABIN` | `economy`/`prestige`/`first` 또는 빈 값(ANY) |
| 성인 | `AIR_PAX_ADULT` | 기본 1 |
| 소아 | `AIR_PAX_CHILD` | 기본 0 |
| 유아 | `AIR_PAX_INFANT` | 기본 0 |
| 시간 오차(분) | `AIR_TOLERANCE_MIN` | 기본 30 |
| 항공편 번호 (선택) | `AIR_FLIGHT_NO` | e.g. `KE001` — 있을 때만 4단계 검색 |

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
- `상관 없음 (ANY)` → `AIR_CABIN=`

보너스(miles) 면 First/Prestige 가 풀리기 어려우니 "어떤 클래스라도 잡으면 알림"을 권유. 단, 사용자가 명시했으면 그 값 그대로.

### 3-4) 인원

명시 안 했으면 기존 값 유지. 한 줄로 받으면 즉시 분해 ("성인 2 소아 1" → `ADULT=2`, `CHILD=1`).

### 3-5) 항공편 번호 (선택)

사용자가 알면 `AIR_FLIGHT_NO` 에 저장. 4단계 우선순위에 사용.

---

## 4단계 — 검색 1회 실행 (조건부)

**전제: `AIR_FLIGHT_NO` 가 있을 때만.** 없으면 4·5단계 skip, 워처가 시간 매칭으로 잡도록 둠.

```bash
AIR_MODE=search AIR_ONCE=true python -m air_watcher.main
```

stdout 에서 "후보 발견:" 라인 파싱. 추출 실패하면 로그 그대로 보여주고 진행.

---

## 5단계 — 항공편 선택 (AskUserQuestion)

**4단계 skip 되었으면 이 단계도 skip.**

후보 (최대 4개) 를 옵션으로 제시.
- 라벨: `"KE1207 09:00→10:10 ICN→CJU Economy"`
- description: `잔여석 / Saver 보너스 / 일반운임 가격`
- 후보 1개면 자동 확정.
- 매칭되는 `AIR_FLIGHT_NO` 가 있으면 첫 옵션으로.
- 후보 0개면 "이 조건으로 잡히는 편 없음 — 다시?" 묻고 3단계로.

선택 후 `AIR_DEPART_TIMES` 를 그 시각 하나로 좁히고 `AIR_DEPART_TIME_WINDOW` 도 ±15분으로 좁힘 (`.env.air`).

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

### 무한 재시도 보장 (필수)

- `AIR_ONCE` 가 `true` 면 강제로 `false` 로 (`.env`).
- 사용자가 "한 번만 / 1회" 명시한 경우만 `true` 허용.

### 실행 명령

```bash
python -m air_watcher.main
```

### 실행 모드 (background / foreground)

`.env` 의 `RAIL_RUN_MODE` 로 결정 (KTX/SRT 와 공유). 묻지 않음.

| 값 | 동작 |
|---|---|
| `background` 또는 비어 있음 | `run_in_background=true` + `Monitor` 로 감시 |
| `foreground` | `run_in_background=false`, 워처가 끝날 때까지 다른 작업 불가 |

`Monitor` 호출 시 `persistent: true`, `timeout_ms` 는 사용자가 명시적으로 시간을 준 경우만 사용. 임의 5분/30분/1시간으로 자르지 말 것.

### CDP 포트 분리

`.env` 의 `AIR_CDP_PORT` 는 기본 `9446` — KTX(`9444`)/SRT(default) 와 겹치지 않게. `AIR_CDP_USER_DATA_DIR` 도 별도 (`C:\Users\kimghw\chrome-air-watcher` 권장). 동시에 KTX/SRT 워처 띄워도 충돌 없음.

---

## 좌석 hold 이후 — 결제는 수동

KE 워처는 좌석 hold(보통 10분 timer) 까지만 자동화한다. 알림에 "결제 페이지 진입 — 10분 안에 수동 결제" 포함. 자동 결제 안 함.

이유:
- KE 결제는 보안 모듈(ISP/안심클릭 등) 이 매번 다르고 본인인증 SMS 들어가는 경우가 잦아 안정적 자동화 어려움
- 마일리지 결제는 정책상 사람 확인 필요한 경우 다수

PAY_* 키는 KE 에서 사용하지 않는다 — KTX/SRT 전용으로 두자.

---

## 하지 말 것

- `AZURE_*` / `DB_PATH` / `AIR_CDP_*` 의 포트·path 임의 수정 금지.
- `.env.share` 는 템플릿 — 손대지 않음.
- `.env` 에 여정 키 (`AIR_ORIGIN` 등) 쓰지 말 것. 여정은 무조건 `.env.air`.
- 사용자 명시값 라운딩 금지.
- 비밀번호 / 마일리지 잔액 stdout 출력 금지.
- 사용자 발화에 "취소/삭제" 가 있으면 `.env` / `.env.air` 수정 안 하고 무엇을 지울지 다시 묻기.

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
3. 출발 `GMP`, 도착 `CJU`, 날짜 `2026-06-01`, TIMES `09:00`, TIME_WINDOW `08:30,09:30`, CABIN `economy`, PAX_ADULT `1`. → **`.env.air` 일괄 갱신**.
4. `AIR_FLIGHT_NO` 없음 → 4·5단계 skip.
5. (skip)
6. 알림 받기/안 받기 → `.env` 의 `TEAMS_ENABLED`.
7. 실행 → 워처가 `AIR_TIME_WINDOW` 안의 09:00 ±30분 보너스석 폴링.
