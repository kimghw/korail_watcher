---
name: chrome-bind
description: 크롬 아이콘(.lnk)을 지정하면 그 아이콘이 여는 창(포트·프로필)을 자동화 채널 바인딩 SSOT(chrome_binding.yaml)에 등록하고, 모든 KRS 자동화 러너가 krs_watcher/chrome_binding.resolve() 로 그 창에만 붙게 한다. 사용자가 더블클릭하는 창 = 자동화가 들어가는 창(공용, 같은 로그인 공유 → OTP 시소 없음). 지정 아이콘에 포트/프로필 인수가 없으면 백업(.bak) 후 주입. status 로 아이콘 인수·창 생존·기기신뢰(DEVICE_AUTH)까지 점검, launch 로 바인딩대로 기동. subscription(9444) 채널은 subscriptions.yaml settings 가 SSOT 라 제외. MCP 미사용 — 독립 스크립트 chrome_bind.py 직접 구동.
allowed-tools: Read, Edit, Write, Bash, Glob, Grep, AskUserQuestion
argument-hint: "[set <lnk경로> | status | launch | resolve] [--channel krs|second]  (아이콘 지정=자동화 통로 고정)"
---

# chrome-bind — 크롬 아이콘 지정 = 자동화 통로 고정

사용자가 **크롬 바로가기(.lnk)를 지정하면**, 그 아이콘이 여는 창(CDP 포트 + 프로필)을 바인딩 SSOT
`.claude/skills/chrome-bind/chrome_binding.yaml` 에 등록한다. **KRS 자동화 러너 전부가 이 SSOT 를 읽어 그 창으로만 붙는다** —
사용자가 쓰는 창과 자동화가 쓰는 창이 항상 같아서(공용) 로그인·기기신뢰(DEVICE_AUTH)를 공유하고,
OTP 를 서로 밀어내는 시소가 생기지 않는다.

> 배경: KRS 서버는 계정당 신뢰 기기(=브라우저 프로필) 1개만 유지 → 같은 계정을 두 프로필에서 번갈아
> 인증하면 서로 등록을 풀어 OTP 반복. 상세 → `KRS_ECLASS_CACHE/KRS_ECLASS_CACHE.md` §6.

## 핵심 원칙

- **바인딩 SSOT 는 한 장**: `.claude/skills/chrome-bind/chrome_binding.yaml` — **스킬 안에 두되 실값이라
  `.gitignore`+`.toolignore` 등록**(커밋·toolkit 동기화 모두 제외, CLAUDE.md 예외 조항 — 단일 로더 추상화·
  재생성 가능·머신별 설정이라 허용. 2026-07-02 사용자 결정). 채널(`krs`·`second`)마다
  `shortcut`(.lnk)·`port`·`user_data_dir`·`account`. 갱신은 이 스킬(`set`)로. 구위치 `<루트>/` 는 legacy 폴백.
- **러너는 resolve() 로만**: 자동화 코드는 포트/프로필을 하드코딩하지 않고
  `krs_watcher/chrome_binding.resolve(channel)` 을 쓴다. **바인딩 파일이 없으면 기존 하드코딩과 동일한
  폴백**(krs=9333·`KRS_ECLASS_CACHE/krs_chrome_profile`) — 하위호환.
- **아이콘이 곧 통로**: `set` 은 .lnk 의 인수에서 포트·프로필을 읽어 등록한다. 포트/프로필 인수가 없는
  일반 아이콘이면 **원본 백업(`KRS_ECLASS_CACHE/<이름>.lnk.bak`) 후 채널 기본값을 주입**해 전용 창 아이콘으로 만든다.
- **프로필=계정 1:1**: 한 채널 창에는 등록된 계정으로만 로그인(타 계정 금지 — DEVICE_AUTH 덮임).
  `second`(별도계정 9555)는 수동 전용 — 자동화는 붙지 않고 status 확인만.
- **subscription(9444) 채널 제외**: 구독 수집 포트·프로필은 `.claude/skills/subscription-receipt/subscriptions.yaml`
  `settings` 가 SSOT — 이중 정의하지 않는다.
- **비파괴**: 떠 있는 창을 종료하지 않는다. 자격증명은 어디에도 저장하지 않는다(로그인은 사용자가 창에서 직접).

## 입력 소스

| 소스 | 처리 |
|:---|:---|
| **인자 `set <lnk경로>`** | 그 아이콘을 채널(기본 krs)에 바인딩. 포트 없으면 `--port`(또는 채널 기본) 주입. |
| **인자 `status`/`launch`/`resolve`** | 바인딩 점검 / 바인딩대로 기동 / 러너용 값 출력. |
| **`chrome_binding.yaml`** | 현재 바인딩(SSOT). 없으면 폴백값으로 동작. |
| **프롬프트 문장** | "이 아이콘으로 자동화 돌려줘" 등 → .lnk 경로 파싱, 모호하면 §AskUserQuestion 1. |

## 절차

### 0. 경로 확정
```
SK="$CLAUDE_PROJECT_DIR/.claude/skills/chrome-bind"
SCRIPT="$SK/chrome_bind.py"                  # 워커(독립 스크립트, MCP 미사용)
BINDING="$SK/chrome_binding.yaml"            # SSOT(실값 — 스킬 안, .gitignore+.toolignore)
LOADER="$CLAUDE_PROJECT_DIR/krs_watcher/chrome_binding.py"  # 러너들이 import 하는 로더(구위치 루트 폴백)
```

### 1. set — 아이콘 지정
1. `.lnk` 경로 확정(인자/프롬프트. 모호하면 §AskUserQuestion 1).
2. `python chrome_bind.py set "<lnk>" [--channel krs] [--port N]` 실행.
   - 대상이 chrome.exe 가 아니면 `not_chrome_lnk` 보고·중단.
   - 포트/프로필 인수 없으면 백업 후 주입(`injected` 필드로 보고).
3. 결과의 `binding` 을 §출력 형식으로 보고 + **그 창 규칙 1줄**(이 창에는 `account` 계정으로만 로그인).

### 2. status — 점검
`python chrome_bind.py status [--channel <ch>|--channel all]` (all=전 채널) → 채널별: 바인딩값·`lnk_match`
(아이콘 인수가 바인딩과 일치하는지 — 어긋나면 재지정 안내)·`cdp_alive`(창 생존)·`device_auth`(기기신뢰·만료).
어긋남은 ⚠ 로 보고. (참고: 러너 계열별 우선순위 = CLI 인자 > `KRS_CHROME_PROFILE` env > 바인딩 — env 를
쓰고 있다면 바인딩보다 우선하니 status 보고 시 함께 확인.)

### 3. launch — 기동
`python chrome_bind.py launch [--channel <ch>]` → 살아 있으면 `reused`, 아니면 바인딩대로 기동.

### 4. resolve — 러너 연동값
`python chrome_bind.py resolve [--channel <ch>]` → `{port, user_data_dir, shortcut, source}`.
러너 코드는 이 값을 `krs_watcher.chrome_binding.resolve()` 로 직접 import(스크립트 호출 불필요).

## 산출물

| 산출물 | 생성 조건 | 후속 사용처 |
|:---|:---|:---|
| `chrome_binding.yaml`(바인딩 SSOT) | `set` 실행 시 생성/갱신 | 모든 KRS 자동화 러너의 포트·프로필 resolve |
| 지정 아이콘 `.lnk`(인수 주입본) | 포트/프로필 없는 아이콘을 `set` 했을 때 | 사용자 더블클릭 = 공용 창 열기 |
| `KRS_ECLASS_CACHE/<이름>.lnk.bak`(원본 백업) | `.lnk` 인수 주입 직전 1회 | 원복(수동 복사) |
| status 점검 결과(JSON 출력) | `status` 실행 시 | 아이콘 변조·창 다운·기기신뢰 만료 진단 |
| `krs_watcher/chrome_binding.py`(로더) | 스킬 설치 시 1회(코드) | 러너 import — 바인딩 소비 |
| `architecture.svg` | 스킬 작성/수정 시 | 아키텍처 참조 |

## 산출물 명명

| 속성 | 값 |
|:---|:---|
| stem 유도 | SSOT 는 고정명 `chrome_binding.yaml`(스킬 폴더). 백업은 원본 파일명 그대로 + `.bak`(예 `거화 - Chrome.lnk.bak`). |
| suffix | 양식 `.template.yaml`(스킬 안) / 실값 suffix 없음(스킬 밖). 백업 `.bak`. |
| 확장자 | SSOT·양식 `.yaml`, 로더·워커 `.py`, 다이어그램 `.svg`. |
| 사용자 지정 옵션 | `--channel`(krs/second), `--port`(주입 포트). 아이콘 경로는 인자. |
| 충돌 처리 | 같은 채널 재지정(`set`)은 SSOT 덮어쓰기(이전 값은 git 아닌 .bak/문서로). `.bak` 은 기존 있으면 보존(첫 원본 유지). |

## 산출물 위치

| 속성 | 값 |
|:---|:---|
| 디렉터리 | SSOT = **스킬 폴더** `chrome_binding.yaml`(.gitignore+.toolignore — 실값·머신별) · 로더 = `krs_watcher/` · 워커·양식 = 스킬 폴더(커밋). |
| ① 입력값 | 지정 아이콘 `.lnk` 는 사용자 공간(바탕화면 등) — 스킬은 경로만 참조. |
| 원본 보존 | `.lnk` 수정 전 `KRS_ECLASS_CACHE/<이름>.lnk.bak` 백업(최초 1회분 보존). 양식 주석은 지우지 않음. |
| 캐시 공유 | 바인딩 창(프로필)은 모든 KRS 스킬(rerp·kreclass-*)과 공유 — 그게 목적. subscription(9444)은 별도 SSOT. |
| 커밋 | 스킬 폴더(워커·양식·SKILL.md·svg)·로더는 추적. `chrome_binding.yaml`·`.bak` 은 .gitignore+**.toolignore**(머신별 — toolkit 공유 복사에서도 제외). |

## AskUserQuestion

| # | 트리거 | 질문 요지 | 옵션 | 기본 권장 |
|:--|:---|:---|:---|:---|
| 1 | `.lnk` 경로 불명(set 인데 경로 없음/여러 후보) | 어떤 아이콘을 지정할까? | 바탕화면 크롬 `.lnk` 후보들 \| 직접입력 | 후보 1건이면 그것 |
| 2 | 채널 불명(krs/second 모호) | 어느 채널에 바인딩할까? | KRS 자동화 공용(krs, 권장) \| 별도계정(second) | krs |
| 3 | 대상 아이콘에 포트/프로필 없음(주입 필요) | 아이콘에 전용 창 인수를 주입할까?(원본 백업) | 주입(권장 — 백업 후) \| 중단 | 주입 |
| 4 | status 에서 `lnk_match: false`(아이콘 변조 감지) | 아이콘을 바인딩값으로 되돌릴까? | `set` 재실행(권장) \| 그대로 두고 보고만 | set 재실행 |

> 인자/대화로 명확하면 묻지 않는다. status/resolve(읽기)는 질문 없이 진행.

## 출력 형식

```
[chrome-bind] set — 채널 krs
  아이콘:  D:\OneDrive - 한국선급\바탕 화면\거화 - Chrome.lnk
  바인딩:  port 9333 · 프로필 KRS_ECLASS_CACHE/krs_chrome_profile · 계정 김거화
  (주입:   포트/프로필 인수 추가, 원본 백업 → KRS_ECLASS_CACHE/거화 - Chrome.lnk.bak)
  규칙:    이 창에는 김거화 계정으로만 로그인. 자동화도 이 창으로만 붙음.
```
- status 는 채널별 `lnk_match`·`cdp_alive`·`device_auth`(만료일)를 표로. 어긋남은 `⚠` 한 줄씩(성공처럼 포장 금지).

## DO
- `set` 후 **반드시 status 로 검증**(lnk_match·cdp_alive) 후 보고.
- 포트/프로필 주입 전 **원본 .lnk 백업**(기존 .bak 있으면 보존).
- 러너 연동은 **로더 import**(`krs_watcher.chrome_binding.resolve`) 로 안내 — 하드코딩 재도입 금지.
- 바인딩 변경 시 사용자에게 **창 규칙 1줄**(이 창 = <계정> 전용·공용) 재고지.

## DON'T
- **떠 있는 크롬 창을 종료하지 않는다**(비파괴). 자격증명을 저장하지 않는다.
- chrome.exe 가 아닌 아이콘에 바인딩하지 않는다(`not_chrome_lnk` 보고).
- `subscription`(9444) 채널을 이 SSOT 에 추가하지 않는다(subscriptions.yaml settings 가 SSOT).
- 한 채널 창에 **다른 계정 로그인**을 안내하지 않는다(기기신뢰 덮임 → OTP 시소 재발).
- 바인딩 파일을 러너별로 복제하지 않는다 — SSOT 한 장.

## 체크리스트
- [ ] 액션 확정(set/status/launch/resolve). set 이면 `.lnk` 경로 확정(§AskUserQuestion 1).
- [ ] `chrome_bind.py <액션>` 실행 → JSON 결과 Read.
- [ ] set: 주입 여부·백업 경로 확인 → status 재검증(lnk_match true).
- [ ] 결과 보고(§출력 형식) + 창 규칙 1줄. 어긋남(⚠)은 숨기지 않는다.
