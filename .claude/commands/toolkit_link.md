---
description: "kimghw/claude_toolkit와 현재 프로젝트 .claude/를 심볼릭 링크로 연결 (pull: 원본→로컬, promote: 로컬→원본, unlink: 로컬 링크 제거, status: 현재 연결 상태 조회)"
allowed-tools: Bash, Read, Glob, AskUserQuestion
---

<!-- markdownlint-disable -->

# /toolkit_link 명령

인자: $ARGUMENTS

## 경로 정의

- **원본 레포(claude_toolkit) 위치**: `claude_toolkit 레포 루트` — 본 문서에서 claude_toolkit 레포 루트를 가리키는 기호. 설치 위치가 바뀌면 이 표기만 기준으로 해석하면 됨. 이하 본문에서는 `$TOOLKIT`으로 참조.
- **원본 콘텐츠 디렉토리**: `$TOOLKIT/.claude/` — 이 레포는 자체적으로 `.claude/` 하위에 `agents/`, `commands/`, `skills/`, `references/`를 보관한다. 심볼릭 원본은 모두 이 경로 하위.
- **로컬 대상(소비자 프로젝트)**: `$CLAUDE_PROJECT_DIR` — 본 명령을 실행하는 현재 프로젝트 루트. `.claude/`가 생성/수정되는 위치.

## 동작 모드

각 인자(경로)에 대해 **상태를 먼저 판별**한 뒤 모드를 결정한다. 인자 하나하나를 독립적으로 처리한다. 사용자가 넘기는 `<rel>`(예: `commands/git.md`)은 **소비자 `.claude/` 기준 상대 경로**이며, 원본 측에서는 `$TOOLKIT/.claude/<rel>`로 해석한다.

| 로컬(`.claude/<rel>`) | 원본(`$TOOLKIT/.claude/<rel>`) | 모드 |
|---|---|---|
| 없음 | 있음 | **pull**: 원본 → 로컬 심볼릭 생성 |
| 실파일/실디렉토리 | 없음 | **promote**: 로컬 → 원본으로 이동 후 심볼릭으로 대체 |
| 심볼릭(원본 가리킴) | 있음 | **skip**: 이미 연결됨, 보고만 |
| 실파일/실디렉토리 | 있음 | **conflict**: 양쪽 존재 → 사용자 확인 후 선택 |
| 없음 | 없음 | **error**: 경로 없음 보고 |

### 제외 대상 (항상 처리하지 않음)

- **`settings.local.json`**: 프로젝트별 로컬 설정(권한 허용 목록 등)으로, 소비자 프로젝트마다 내용이 달라야 한다. 어떤 모드(pull/promote/conflict/`all`/인터랙티브)에서도 **링크·이동·복사 대상에서 영구 제외**한다. 사용자가 명시적으로 `settings.local.json`을 인자로 넘기더라도 처리하지 말고 "제외 대상" 사유와 함께 스킵 보고만 한다.
- **`.gitignore`, `settings.json`**(존재 시): 위와 동일하게 프로젝트별 설정이므로 제외.

## 동작 규칙

1. **사전 점검**
   - `$TOOLKIT`(= `<프로젝트 루트>`) 실제 경로를 확인. 없거나 접근 불가면 에러 후 중단하고 사용자에게 설치 위치를 물음.
   - `ls "$TOOLKIT/.claude"` 및 `ls -la "$CLAUDE_PROJECT_DIR/.claude/"`로 양쪽 구조 확인.
   - 소비자 프로젝트의 `.claude/`는 일반적으로 소비자 `.gitignore`에 등록되어 소비자 레포에 커밋되지 않음을 전제로 함. (toolkit 원본 레포에서는 `.claude/`가 트래킹 대상.)

2. **인자 해석**
   - **`help` / `-h` / `--help`**: 본 명령이 받는 인자(인자 없음/`all`/구체 경로/`unlink ...`/`status` 등)와 각 동작 설명을 요약 출력하고 종료 (파일시스템 변경 없음).
   - **인자 없음**: **인터랙티브 선택 모드** (아래 2-1 참조) — `agents/`, `commands/`, `skills/` 하위 항목을 카테고리별로 나열하고 `AskUserQuestion`으로 선택받는다.
   - **`all`**: 최상위 3개(`agents`, `commands`, `skills`)를 `.claude/`에 디렉토리 단위로 **pull-link**.
   - **구체 경로**(예: `references`, `skills/pdf2md`, `commands/git.md`): 위 상태표에 따라 **모드 자동 판별**.
   - **여러 항목**: 공백으로 나열 가능 (예: `references skills/md2wu`). 각 항목 독립 처리.
   - **`unlink <경로> [<경로> ...]`**: 지정한 경로의 심볼릭 링크만 선택적으로 제거 (아래 5-1 참조).
   - **`unlink all`**: `.claude/` 하위에서 `$TOOLKIT/.claude/`를 가리키는 **모든** 심볼릭 링크를 일괄 제거.
   - **`status`** 또는 **`list`**: `.claude/` 하위 항목들의 현재 연결 상태만 조회(읽기 전용, 변경 없음). 아래 5-2 참조.

2-1. **인터랙티브 선택 모드 (인자 없음 기본 동작)**
   - **폴더별 순차 질문**이 원칙: `agents/` → `commands/` → `skills/` 순서로 **한 번에 한 폴더만 묻는다**. 세 개를 한 번의 `AskUserQuestion` 호출에 묶지 말고, 폴더당 별도의 `AskUserQuestion` 호출을 순차로 쓴다(응답 받은 뒤 다음 폴더로). `references/`는 기본 후보에서 제외(필요하면 사용자가 구체 경로로 호출).
   - **각 폴더 처리 순서**:
     1. 해당 폴더의 직속 하위 항목을 `ls -1`로 수집. 파일/디렉토리 구분과 각 항목의 로컬 상태(없음 / 심볼릭(링크 대상 표시) / 실파일·실디렉토리)를 함께 파악한다.
     2. 폴더가 비어 있으면 "비어 있음"으로 보고하고 다음 폴더로 건너뛴다.
     3. `AskUserQuestion`(`multiSelect: true`)로 항목을 선택지로 제시:
        - **항목 ≤ 4개**: 각 항목을 개별 선택지로.
        - **항목 > 4개**: 선택지 3개는 주요 항목(이미 연결돼 있거나 대표성 있는 것 우선), 네 번째는 `전체(이 폴더 모두)`. 빠진 항목은 사용자가 "Other" 자유 입력으로 지정하도록 질문 본문에 안내. 항목이 너무 많아 한 질문으로도 부족하면 같은 폴더를 2개 질문으로 분할(예: "스킬 (1/2)", "스킬 (2/2)")해도 되지만, 되도록 `전체` 선택지 + Other 자유 입력으로 처리한다.
        - 이미 올바르게 링크된 항목(심볼릭 → `$TOOLKIT/.claude/...`)은 라벨 뒤에 `(연결됨)`으로 표시.
     4. 응답을 받아 해당 폴더 선택 목록에 누적.
   - **처리**: 세 폴더의 선택이 끝나면 누적된 선택 목록을 공백 나열 인자처럼 취급해 상태표에 따라 **모드 자동 판별** 후 일괄 처리. 처리 중 conflict/promote가 필요한 항목은 항목별로 별도 확인 프롬프트.
   - **빈 선택 / 전체 중단**: 세 폴더 모두 아무 항목도 고르지 않았거나 중간에 사용자가 중단하면 "선택된 항목 없음"으로 보고하고 종료.
   - **구체 경로가 필요한 경우 안내**: 순차 질문 UI로 다루기 불편한 깊은 경로(예: `skills/pdf2md/SKILL.md` 단독)는 `/toolkit_link <경로1> <경로2>` 식으로 직접 호출하도록 안내.

3. **pull 모드** (원본 → 로컬 심볼릭)
   - 절대 경로 심볼릭 사용: `ln -s "$TOOLKIT/.claude/<rel>" "$CLAUDE_PROJECT_DIR/.claude/<rel>"`
   - 대상 상위 디렉토리가 없으면 `mkdir -p`로 먼저 생성.
   - 디렉토리 단위 링크(예: `.claude/skills`)와 하위 항목 링크(예: `.claude/skills/pdf2md`)는 충돌하므로 둘 중 하나만 선택하도록 안내.

4. **promote 모드** (로컬 → 원본 이동 후 심볼릭으로 대체)
   - 실행 전 사용자 확인 필수: "이 경로를 toolkit 원본으로 이동한 뒤 심볼릭으로 대체합니다" 요약 후 승인 대기.
   - 순서:
     1. 대상 상위 디렉토리 생성: `mkdir -p "$(dirname "$TOOLKIT/.claude/<rel>")"`
     2. 이동: `mv "$CLAUDE_PROJECT_DIR/.claude/<rel>" "$TOOLKIT/.claude/<rel>"`
     3. 심볼릭 생성: `ln -s "$TOOLKIT/.claude/<rel>" "$CLAUDE_PROJECT_DIR/.claude/<rel>"`
     4. 검증: `readlink` 결과가 `$TOOLKIT/.claude/<rel>`와 일치하는지 확인.
   - toolkit 레포에 add/commit/push는 **이 명령이 자동으로 하지 않는다**. `/toolkit_git`로 별도 커밋하도록 안내만.
   - 이동 중 에러 시 즉시 중단하고 현재 상태(이동됐는지 여부)를 보고.

5. **conflict / skip / error**
   - conflict: 양쪽 모두 존재 → 어떤 쪽을 정본으로 살릴지(로컬 버리고 pull / 원본 버리고 promote / 수동 머지) 사용자에게 확인.
   - skip: 이미 올바른 심볼릭이면 "이미 연결됨"으로 보고만.
   - error: 양쪽 다 없으면 경로 오타 가능성 보고.

5-1. **unlink 모드** (로컬 심볼릭 링크 제거)
   - **대상 판별**: 각 경로에 대해 `test -L "$CLAUDE_PROJECT_DIR/.claude/<rel>"` 로 심볼릭 여부 확인.
     - **실파일/실디렉토리**: 제거 거부 (데이터 손실 위험). "심볼릭이 아닙니다" 보고 후 스킵.
     - **없음**: "대상 없음" 보고 후 스킵.
     - **심볼릭이지만 `$TOOLKIT/.claude/`를 가리키지 않음**: 외부 링크일 수 있으므로 기본 스킵. 강제 제거는 사용자 명시적 확인 필요.
     - **심볼릭이고 `$TOOLKIT/.claude/` 하위를 가리킴**: 제거 대상.
   - **사전 확인**: 제거할 링크 목록을 `경로 → 원본` 형식으로 표시하고 사용자 승인 대기.
   - **실행**: `rm "$CLAUDE_PROJECT_DIR/.claude/<rel>"` (심볼릭 자체만 제거, 원본 `$TOOLKIT/.claude/<rel>`은 그대로 유지).
   - **`unlink all`**: `find "$CLAUDE_PROJECT_DIR/.claude/" -maxdepth 3 -type l` 로 심볼릭만 나열하고, `readlink`로 `$TOOLKIT/.claude/` 프리픽스를 가진 것만 필터링하여 일괄 제거 후보로 제시.
   - **사후 검증**: 제거된 경로에 `ls` 해서 없어졌는지 확인. 처리 결과는 6번 사후 확인에 포함.
   - 원본(`$TOOLKIT/.claude/<rel>`)은 절대 건드리지 않음. 원본까지 지우려면 toolkit 레포에서 직접 작업.

5-2. **status 모드** (읽기 전용 조회)

   목적: 현재 프로젝트의 `.claude/` 하위 항목이 각각 어디와 연결되어 있는지, 어느 버전의 toolkit을 참조 중인지 한눈에 보여준다. 파일 변경 없음.

   - **수집**: `.claude/` 직속 및 `agents/`·`commands/`·`skills/`·`references/` 2단 하위까지 `find "$CLAUDE_PROJECT_DIR/.claude" -maxdepth 3 \( -type l -o -type f -o -type d \)`로 항목 나열.
   - **분류**: 각 항목을 다음 4 카테고리로 판정.
     - **[toolkit]**: 심볼릭이고 `readlink -f` 결과가 `$TOOLKIT/.claude/` 하위.
     - **[외부]**: 심볼릭이지만 `$TOOLKIT/.claude/` 밖을 가리킴.
     - **[로컬]**: 심볼릭이 아닌 실파일/실디렉토리.
     - **[없음]**: 원본에는 있는데(`$TOOLKIT/.claude/<rel>` 존재) 로컬에는 없는 항목(참고용, `pull` 후보).
   - **toolkit 버전 정보**: `git -C "$TOOLKIT" rev-parse --short HEAD` 및 `git -C "$TOOLKIT" status --porcelain`로 현재 커밋·워킹트리 상태를 같이 출력. 커밋되지 않은 변경이 있으면 "dirty" 표시.
   - **깨진 링크 점검**: `[toolkit]` 카테고리 항목 중 `readlink -f` 결과가 실존하지 않으면 "**broken**" 표식을 붙여 별도 보고(toolkit 원본이 이동/삭제된 경우).
   - **출력 형식**: 카테고리별로 그룹화해 표시. 예:
     ```
     toolkit: $TOOLKIT = /mnt/c/claude_toolkit/claude_toolkit  (HEAD a1b2c3d, clean)

     [toolkit]
       .claude/commands/            → $TOOLKIT/.claude/commands
       .claude/agents/              → $TOOLKIT/.claude/agents
       .claude/skills/pdf2md/       → $TOOLKIT/.claude/skills/pdf2md
     [외부]
       .claude/skills/foo           → /other/path/foo
     [로컬]
       .claude/skills/my-local      (실디렉토리)
       .claude/settings.local.json  (실파일)
     [없음 — toolkit에 있지만 로컬 미링크]
       references/, agents/<x>.md
     [broken]
       (없음)
     ```
   - **요약 한 줄**: `toolkit: N개 · 외부: N개 · 로컬: N개 · 깨짐: N개`.
   - 이 모드는 사용자 승인 프롬프트 없이 즉시 출력하고 종료. `/toolkit_link pull`, `/toolkit_link unlink` 등 후속 호출로 상태를 바꿀 수 있음을 안내.

6. **사후 확인**
   - `ls -la "$CLAUDE_PROJECT_DIR/.claude/<rel 상위>"` 및 `readlink`로 링크 검증.
   - 처리된 항목별로 `모드 | 경로 | 결과` 요약 보고.

## 예시

- `/toolkit_link all` → 3개 최상위 디렉토리 pull-link
- `/toolkit_link skills/pdf2md skills/md2wu` → 2개 스킬 pull-link
- `/toolkit_link references` → 로컬 `.claude/references/`가 실디렉토리이고 원본에 없으면 **promote** (toolkit으로 이동 후 심볼릭 대체)
- `/toolkit_link unlink skills/pdf2md` → 해당 심볼릭 링크만 제거 (원본은 보존)
- `/toolkit_link unlink skills/pdf2md commands/git.md` → 여러 링크 선택 제거
- `/toolkit_link unlink all` → `.claude/` 내 toolkit 대상 심볼릭 링크 일괄 제거
- `/toolkit_link` (인자 없음) → `agents/` → `commands/` → `skills/` 순서로 폴더별 multiSelect 질문을 띄워 항목 선택 후 일괄 pull-link
- `/toolkit_link status` (또는 `list`) → 현재 `.claude/` 항목별 연결 상태(toolkit/외부/로컬/없음/broken) 조회만, 변경 없음
