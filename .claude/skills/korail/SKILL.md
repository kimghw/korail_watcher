---
name: korail
description: KTX/SRT 통합 예매 워크플로우. 사용자가 기차 예매 관련 발언("korail", "코레일", "ktx", "srt", "기차 예매", "표 예매", "예매하자", "수서에서 부산", 열차번호 등) 을 하면 시작. 절차 — (1) RAIL_TYPE 선택 (2) 계정 확인/입력 (3) 출발/도착/날짜/시간/좌석 수집 (4) 시간표 조회 (5) 열차 선택 (6) 예약-only 인지 결제까지인지 (7) 알림 설정 (필요시 korail_alarm 호출) (8) 워처 실행.
---

# korail — KTX / SRT 통합 예매 워크플로우

사용자가 기차 예매를 시작하면 아래 순서대로 진행. 매 단계 결정을 받고 `c:\Users\kimghw\korail_watcher\.env` 를 in-place 수정. AZURE_*, DB_PATH 등 인프라 키는 절대 건드리지 않는다.

---

## ⚠ 사전 조건 — 동작 환경 (시작 전 반드시 확인)

**이 스킬은 `https://github.com/kimghw/korail_watcher.git` 를 clone 받은 디렉토리 안에서만 동작한다.**
그 외 위치에서는 `ktx_watcher` / `srt_watcher` / `team_mcp` 모듈이 없어 4·8단계가 무조건 실패하며,
스킬이 묻는 질문에 답을 다 받아도 의미 있는 결과를 줄 수 없다 — 따라서 다른 위치에서는 **시작하지 않는다**.

### 워크플로우 시작 전 점검 (필수, 1회)

다른 단계로 넘어가기 전 아래 둘 다 검증:

1. **repo 매칭** — cwd 의 git remote 가 이 repo 인지 확인.
   ```bash
   git -C "<cwd>" remote get-url origin
   # 기대값: https://github.com/kimghw/korail_watcher.git (혹은 SSH 변형)
   ```
2. **필수 폴더 존재** — cwd 에 `ktx_watcher/`, `srt_watcher/`, `team_mcp/` 세 폴더가 모두 있어야 함.

**둘 중 하나라도 실패 → 워크플로우 진입 중단.** 1·2단계로 넘어가지 말고 사용자에게 아래를 그대로 보여준다:

> 이 스킬은 `https://github.com/kimghw/korail_watcher.git` 를 clone 받은 디렉토리에서만 동작합니다.
> 현재 위치: `<cwd>` — 필수 모듈 (`ktx_watcher` / `srt_watcher` / `team_mcp`) 이 없어 진행할 수 없습니다.
>
> 해결:
> - 처음이라면: `git clone https://github.com/kimghw/korail_watcher.git`
> - 이미 clone 받아두었다면 해당 폴더로 이동 후 다시 호출
> - 오래됐을 수 있으면 해당 폴더에서: `git pull` 후 재시도
>
> 받은 디렉토리에서 이 스킬을 다시 호출해주세요.

이 시점에서는 사용자에게 진행 옵션을 주지 않는다 (어차피 실행에서 실패하므로 "계속 진행" 은 false hope).
사용자가 이미 자세한 여행 정보 (역/날짜/시간) 를 한 번에 입력한 상태라면, 그 입력은 응답 안에서만 메아리쳐 주고 `.env` 수정은 하지 않는다.

### 실행 중 실패 분기 — repo 위치/상태 의심 신호

4 단계 (`python -m ktx_watcher.main` / `srt_watcher.main`) 또는 8 단계 워처 기동에서 아래 중 하나가 나오면, 스킬 로직 잘못이 아니라 **위치 또는 stale clone 문제** 일 가능성이 크다:

- `ModuleNotFoundError: No module named 'ktx_watcher'` (혹은 `srt_watcher` / `team_mcp` / `playwright` 등)
- `python: No module named ktx_watcher.main` / `srt_watcher.main`
- `FileNotFoundError` 가 repo 내부 path (`config/...`, `team_mcp/login.py` 등) 를 가리킬 때
- import 는 되는데 새 환경변수/플래그 (`RAIL_*`, `KTXA_PAYMENT_MODE` 등) 가 무시되거나 `unknown option` 으로 거부될 때 → 코드가 오래됨

이 경우 stdout/stderr 그대로 보여주고 한 블록 덧붙임:

> 위 에러는 보통 다음 둘 중 하나입니다:
> 1. 이 스킬이 `https://github.com/kimghw/korail_watcher.git` clone 디렉토리 **밖** 에서 실행됨
> 2. clone 받았지만 **버전이 오래되어** 새 모듈/플래그가 없음
>
> 현재 cwd: `<cwd>`.
> 해결:
> - 올바른 폴더로 이동했는지 확인
> - 해당 폴더에서 `git pull` 후 재시도
> - 그래도 안 되면 `git clone https://github.com/kimghw/korail_watcher.git` 로 새로 받기

그 외 정상 경로(모듈 import OK, 로그인 또는 좌석 매진 같은 비즈니스 실패) 면 이 안내를 띄우지 않는다 — 진짜 문제를 가린다.

---

## 핵심 규칙
- 사용자가 한 번에 여러 정보를 주면 (예: "5월 25일 경주→오송 13:38 KTX 1명 일반실") 해당 단계 skip.
- 모호하거나 빠진 것만 `AskUserQuestion` 으로 묻기.
- 사용자가 명시한 값은 라운딩/안전화 금지 (13:38 → 13:30 X).
- `.env` 값은 따옴표 없이 저장 (예: `RAIL_ORIGIN=경주`).
- 여정 (`RAIL_*`) 과 결제 (`PAY_*`) 는 KTX/SRT 공통 — 한 번만 묻는다.
- 기타 입력은 사용자가 형식 없이 입력 — `AskUserQuestion` 의 자동 Other 선택지로 들어온 값은 그대로 받아 의미 단위로 해석한다 (정규화/검증은 각 단계 규칙에 따름).

---

## 1단계 — RAIL_TYPE 결정

`.env` 의 `RAIL_TYPE` 읽음.

- 사용자가 KTX/SRT 어느 쪽인지 명시했으면 `RAIL_TYPE=ktx|srt` 로 갱신.
- 명시 안 했고 기존이 `both` 면 `AskUserQuestion`:
  - 질문: "어떤 시스템을 사용하시나요?"
  - 옵션: `KTX` / `SRT` / `둘 다`

---

## 2단계 — 계정 확인 / 입력

선택된 시스템(들) 마다 ID/PW 키 확인:

| RAIL_TYPE | 키 |
|---|---|
| ktx | `KTXA_USER`, `KTXA_PASS` |
| srt | `SRT_USER`, `SRT_PASS` |
| both | 양쪽 모두 |

- **둘 다 비어 있으면**: 사용자에게 직접 묻기 — "KTX (Korail) 회원 ID 입력해주세요" → 입력받아 `.env` 저장. 비밀번호도 동일.
- **이미 채워져 있으면**: ID 만 마스킹해서 보여주고 `AskUserQuestion`:
  - 질문: "현재 저장된 KTX 계정 (ID: 117399****) 으로 진행할까요?"
  - 옵션: `이 계정으로 진행` / `다른 계정 입력`
  - "다른 계정" 이면 ID/PW 새로 받아 저장.

> 비밀번호 값은 사용자에게 그대로 다시 보여주지 말 것.

---

## 3단계 — 여행 정보 수집

저장 키 (모두 `RAIL_*` 한 세트, 양 워처가 fallback 으로 읽음):

| 의미 | 키 |
|---|---|
| 출발역 | `RAIL_ORIGIN` |
| 도착역 | `RAIL_DEST` |
| 날짜 | `RAIL_DATE` |
| 선호 시각(들) | `RAIL_TIMES` |
| 허용 시간대 | `RAIL_TIME_WINDOW` |
| 인원 | `RAIL_PASSENGERS` |
| 좌석 등급 | `RAIL_SEAT_CLASS` |
| 시간 오차(분) | `RAIL_TOLERANCE_MIN` |
| 열차번호 (선택) | `RAIL_TRAIN_NO` |

### 3-1) 출발지 / 도착지 — AskUserQuestion

각각 별도 질문으로 받는다 (한 번에 두 개 묻지 않기). 4지선다 + 자동 Other.

**출발지 옵션 (popular 4):**
- `서울` (KTX 경부)
- `수서` (SRT 경부/호남)
- `오송` (KTX/SRT 환승 핵심)
- `부산`
- (자동 Other) — 사용자 자유 입력

**도착지 옵션 (popular 4):**
- `부산`
- `오송`
- `서울`
- `수서`
- (자동 Other)

사용자가 Other 로 직접 입력하면 **하단 정차역 참고표** 에 있는지 검증.
- 있으면 그대로 저장.
- 없으면 한 줄 알림 + 다시 묻기: "'XX' 역은 KTX/SRT 정차역 목록에 없습니다. 정확한 역명으로 다시 입력해주세요."

`RAIL_TYPE` 에 따라 추가 검증:
- `srt` 인데 사용자가 `광명` (KTX 전용) 선택 → 알림 + 재선택.
- `ktx` 인데 사용자가 `수서` (SRT 전용) 선택 → 알림 + 재선택.
- `both` 인데 한 쪽에만 있는 역 → "이 역은 SRT 만 서비스합니다. RAIL_TYPE 을 srt 로 좁힐까요, 다른 역 선택할까요?" 묻기.

### 3-2) 날짜 — 자유 입력

"언제 가시나요? (예: 2026-05-25, 5월 25일, 내일)" 사용자 자유 입력 받기.
- `YYYY-MM-DD` 로 정규화.
- 연도 없으면 currentDate 기준 가장 가까운 미래.
- 과거 날짜면 한 줄 확인 ("과거 날짜인데 맞나요?"). 임의 +1년 금지.

### 3-3) 시간 / 시간대 — 자유 입력

"몇 시쯤? (예: 13:38, 오후 1시반, 13~14시)" 입력 받기.
- 단일 시각 → `RAIL_TIMES=HH:MM`, `RAIL_TIME_WINDOW` 는 그 시각 ±30분 시단위 반올림.
- 시간대 → `RAIL_TIME_WINDOW=HH:MM,HH:MM`, `RAIL_TIMES` 는 중앙값.

### 3-4) 좌석 등급 — AskUserQuestion

- 질문: "좌석 등급은?"
- 옵션:
  - `일반실`
  - `특실`
  - `둘 다 상관 없음` — `RAIL_SEAT_CLASS=` 를 빈 값으로 두면 워처가 ANY 매칭.

### 3-5) 인원

명시 안 했으면 기존 값 유지. 명시했으면 `RAIL_PASSENGERS` 갱신.

### 3-6) 열차번호 (선택)

사용자가 알면 `RAIL_TRAIN_NO` 에 저장. 워처는 시간 매칭이라 직접 안 쓰지만 5단계 추천 우선순위에 사용.

---

## 4단계 — 시간표 조회

선택된 시스템(들) 워처를 **search 모드 + 1회** 로 실행해서 후보 추출.

| RAIL_TYPE | 명령 (환경변수 임시 override) |
|---|---|
| ktx | `KTXA_MODE=search KTXA_ONCE=true python -m ktx_watcher.main` |
| srt | `SRT_MODE=search SRT_ONCE=true python -m srt_watcher.main` |
| both | 둘 다 (병렬 또는 순차) |

stdout/stderr 에서 "후보 발견:" / "Found candidate:" 라인 파싱. 추출 실패하면 로그 텍스트 그대로 사용자에게 보여주고 진행.

> TODO: 워처에 `--dump-json` 옵션 추가하면 깔끔.

---

## 5단계 — 열차 선택 (AskUserQuestion)

후보 (최대 4개) 를 옵션으로 제시.

- 라벨: `"KTX 034 13:38 일반실"` 같은 형태
- description: 잔여석 / 매진 / 가격
- 후보 1개면 묻지 않고 자동 확정.
- 후보 > 4 이면 시간순 상위 4 만.
- `RAIL_TRAIN_NO` 가 있고 매칭되는 후보가 있으면 그걸 첫 옵션으로.
- 후보 0개면 "이 조건으로 잡히는 열차 없음 — 다시?" 묻고 3단계로.

선택 후 `RAIL_TIMES` 를 그 시각 1개만으로 좁히고 `RAIL_TIME_WINDOW` 도 ±15분으로 좁힘.

---

## 6단계 — 예약-only / 결제까지

`AskUserQuestion`:
- 질문: "예약만 잡을까요, 결제·발권까지 진행할까요?"
- 옵션:
  - `예약만 (좌석 hold 10분)`
  - `결제·발권까지 자동`

선택 결과를 `.env` 에 반영:

| 결과 | KTX 키 | SRT 키 |
|---|---|---|
| 예약만 | `KTXA_PAYMENT_MODE=false` | `PAYMENT_MODE=false` |
| 결제까지 | `KTXA_PAYMENT_MODE=true` | `PAYMENT_MODE=true` |

`KTXA_MODE`, `SRT_MODE` 는 `reserve` 로 (예약·결제 모두 reserve 모드 필요).

### 결제까지인 경우 — 카드 정보 확인

`.env` 의 `PAY_*` 키 (KTX/SRT 공통):

| 키 | 형식 |
|---|---|
| `PAY_CARD_NUM` | `9999-9999-9999-9999` |
| `PAY_CARD_MM` | `01`~`12` |
| `PAY_CARD_YY` | `2025`~`2037` |
| `PAY_CARD_PW2` | 카드 비번 앞 2자리 |
| `PAY_ID6` | 주민번호 앞 6자리 |

- 하나라도 비었으면 사용자에게 받기.
- 다 있으면 카드번호 끝 4자리만 보여주고 (`****-****-****-6569`) `AskUserQuestion`:
  - 질문: "이 카드로 결제할까요?"
  - 옵션: `이 카드로` / `다른 카드 입력`

---

## 7단계 — 알림 설정

`AskUserQuestion`:
- 질문: "Teams 알림을 받으시겠어요?"
- 옵션: `알림 받기` / `알림 안 받기`

### 알림 받기 선택 시

`.env` 의 다음 키 검증:

| 키 | 의미 |
|---|---|
| `TEAMS_ENABLED` | `true` 로 설정 |
| `TEAMS_USER_EMAIL` | 회사 계정 이메일 — 알림 받는 사람 |
| `AZURE_CLIENT_ID` / `AZURE_CLIENT_SECRET` / `AZURE_TENANT_ID` | Azure 앱 등록 |
| `DB_PATH` 의 auth.db | OAuth 토큰 저장 위치 |

위 키 중 **하나라도 비어 있거나** `DB_PATH` 의 auth.db 에 해당 계정 토큰이 없으면 → **`korail_alarm` 스킬 invoke**.

`korail_alarm` 이 성공 반환하면 본 워크플로우 계속. 실패하면 사용자에게 한 줄: "알림 인증 실패 — 알림 없이 진행할까요?" 묻고 분기.

### 알림 안 받기 선택 시

`.env` 의 `TEAMS_ENABLED=false` 설정. 그 외 Azure/Teams 키는 건드리지 않음.

---

## 8단계 — 워처 실행

`AskUserQuestion`:
- 질문: "지금 바로 워처를 띄울까요?"
- 옵션: `지금 실행` / `나중에 (.env 만 저장)`

실행 시:

| RAIL_TYPE | 명령 |
|---|---|
| ktx | `python -m ktx_watcher.main` |
| srt | `python -m srt_watcher.main` |
| both | 두 개 동시 (별도 터미널 또는 `run_in_background=true`) |

`both` 일 때 Chrome 분리: KTX 는 `KTXA_CDP_PORT=9444` + `KTXA_CDP_USER_DATA_DIR`. SRT 는 `SRT_CDP_URL` 로 별도 포트 띄우든지 Playwright 기본으로.

---

## 하지 말 것

- `AZURE_*` (CLIENT_ID 빼고는 사용자 동의 없이) / `DB_PATH` / `KTXA_CDP_*` 의 포트/path 같은 인프라 키는 임의 수정 금지.
- `.env.share` 는 템플릿 — 손대지 않음.
- 사용자 명시값 라운딩 금지.
- 비밀번호 / 카드정보 / 토큰을 stdout 으로 출력 금지.
- 사용자 발화에 "취소/삭제/지워" 가 있으면 .env 수정 안 하고 무엇을 지울지 다시 묻기.

---

## 부록 — KTX / SRT 정차역 참고표

### KTX (한국철도, Korail)

| 노선 | 정차역 |
|---|---|
| 경부고속 | 서울, 광명, 천안아산, 오송, 대전, 김천(구미), 동대구, 신경주, 울산(통도사), 부산 |
| 호남고속 | 용산, 광명, 천안아산, 오송, 공주, 익산, 정읍, 광주송정, 나주, 목포 |
| 경부일반 | 서울, 영등포, 수원, 평택, 천안, 조치원, 대전, 서대전, 김천, 구미, 동대구, 경산, 밀양, 구포, 부산 |
| 전라선 | 용산, 익산, 전주, 남원, 곡성, 구례구, 순천, 여천, 여수EXPO |
| 강릉선 | 청량리, 상봉, 만종, 횡성, 둔내, 평창, 진부(오대산), 강릉 |
| 동해선 | 동대구, 신경주, 포항 |

### SRT (수서고속)

| 노선 | 정차역 |
|---|---|
| 경부 | 수서, 동탄, 평택지제, 천안아산, 오송, 대전, 김천(구미), 서대구, 동대구, 신경주, 울산(통도사), 부산 |
| 호남 | 수서, 동탄, 평택지제, 천안아산, 오송, 공주, 익산, 정읍, 광주송정, 나주, 목포 |
| 경전 | (경부 본선 경유 후) 동대구, 밀양, 진영, 창원중앙, 창원, 마산, 진주 |
| 동해 | 동대구, 신경주, 포항 |

### 한쪽 시스템 전용 (RAIL_TYPE 검증 시 사용)

- **KTX 전용**: 서울, 용산, 광명, 영등포, 수원, 청량리, 상봉, 만종, 횡성, 둔내, 평창, 진부, 강릉, 영등포 등 (일반선 + 강릉선)
- **SRT 전용**: 수서, 동탄, 평택지제, 진영, 창원중앙, 마산
- **공통**: 천안아산, 오송, 대전, 김천(구미), 동대구, 신경주, 울산(통도사), 부산, 공주, 익산, 정읍, 광주송정, 나주, 목포, 포항

---

## 빠른 예시

입력:
> 5월 25일 경주에서 오송, 13:38, 1명, 일반실, 예약만, 알림은 받지 마

처리:
1. RAIL_TYPE — 명시 안 함 → 묻기 (또는 기존 `both` 유지 후 진행).
2. 계정 — 마스킹 보여주고 한 번 확인.
3. 출발 `경주` (참고표 검증 OK), 도착 `오송` (OK). 날짜 `2026-05-25`. 시각 `13:38`, window `13:00,14:00`. 좌석 `일반실`. 인원 `1`. → `.env` 일괄 갱신.
4. search 모드 1회 실행, 후보 추출.
5. 후보 중 `KTX 034 13:38` 있으면 자동 첫 옵션.
6. 예약-only 선택 → `KTXA_PAYMENT_MODE=false`.
7. 알림 안 받기 → `TEAMS_ENABLED=false`. korail_alarm 호출 안 함.
8. 지금 실행? → 답에 따라 실행 or 종료.
