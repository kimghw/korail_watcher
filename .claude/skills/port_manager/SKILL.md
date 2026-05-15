---
name: port_manager
description: 현재 프로젝트의 서버·포트를 SSOT(port_list.md)에서 조회·등록·갱신·삭제하고, 등록된 서버를 상태확인→종료→재시작까지 처리. 행이 0이면 등록 안내, 1이면 자동 재시작, 2+이면 AskUserQuestion으로 선택받아 재시작. 포트 검색·종료·기동·표 편집은 port_ops.sh 스크립트로 위임. TRIGGER when 사용자가 /port_manager 호출, 현재 프로젝트 포트·서버 등록·조회·재시작·재기동 요청. DO NOT TRIGGER when 외부 호스트 접속, 배포·CI 파이프라인.
allowed-tools: Bash AskUserQuestion Read
argument-hint: [show|all|update [<path>]|add|<port>|rm <port>|help]
---

# port_manager — 프로젝트 서버 등록·조회·재시작

본 스킬은 **현재 프로젝트의 서버 정의(port_list.md)**를 관리하고, 등록된 서버를 **"상태 확인 → 실행 중이면 종료 → 새로 기동"** 시킨다. 인자에 따라 조회/등록/삭제 모드로도 동작한다.

> 본 스킬은 부작용(프로세스 kill·서버 기동·SSOT 파일 편집)을 일으킨다. 결과 검증은 호출 시점 Claude의 책임이다.

## 핵심 원칙

- **단일 출처(SSOT)**: 모든 결정은 `port_list.md` 한 파일에서 시작한다. 다른 곳을 추측하지 않는다.
- **스크립트 우선**: 포트 검색·상태·종료·기동·표 편집은 모두 `port_ops.sh` 가 처리한다. Claude가 `ss`/`lsof`/`kill`/`awk`/`sed` 로 표를 직접 다루지 않는다.
- **현재 프로젝트만 (기본)**: `basename "$CLAUDE_PROJECT_DIR"` 으로 결정한 프로젝트만 다룬다. 다른 프로젝트 행은 `all` 모드에서만 표시한다. **예외**: `update <path>` 는 인자로 받은 외부 경로를 대상 프로젝트로 사용한다(이때 프로젝트명은 `basename <path>`).
- **수량으로 분기**: 재시작 모드에서 행 수가 0 → 안내, 1 → 자동, 2+ → `AskUserQuestion` 으로 선택.
- **재시작은 명시적 절차**: `status → kill(있을 때만) → start → status` 순서를 따른다.

## 인자 분기 (`$ARGUMENTS`)

| 인자 | 모드 | 동작 |
|:---|:---|:---|
| (없음) | **재시작** | 현재 프로젝트 행을 보여주고 1행이면 자동 재시작, 2+행이면 `AskUserQuestion` 선택 후 재시작. 0행이면 등록 안내. |
| `show` | **조회** | 현재 프로젝트 행을 출력만. 재시작 안 함. 0행이면 미등록 메시지. |
| `all` 또는 `list` | **전체 조회** | `port_list.md` 전체 표를 그대로 출력. 다른 프로젝트 포함. |
| `update` | **자동 발견 등록 (현재 프로젝트)** | 현재 프로젝트에 속한 LISTEN 서버를 `discover` 로 찾아 보여주고, `AskUserQuestion` multiSelect 로 등록 대상을 고르게 한다. 다른 프로젝트와 같은 포트면 충돌 경고. |
| `update <path>` | **자동 발견 등록 (외부 프로젝트)** | `<path>` 디렉토리를 프로젝트 루트로 간주해 그 안에서 LISTEN 중인 서버를 발견·등록한다. 프로젝트명은 `basename <path>`. 등록 후엔 그 프로젝트 컨텍스트에서 `/port_manager` 로 재시작할 수 있다. |
| `<숫자>` | **등록/갱신** | 그 포트로 등록(미존재) 또는 갱신(존재). 서비스·시작명령·작업디렉토리는 `AskUserQuestion`. |
| `add` | **등록(대화형)** | 포트부터 `AskUserQuestion` 으로 받고 동일 절차. |
| `rm <port>` 또는 `remove <port>` | **삭제** | 현재 프로젝트의 그 행을 삭제. 사용자 확인 후. |
| `help` 또는 `-h` | **사용법** | 본 표를 그대로 출력하고 종료. |

## 사용 도구

| 도구 | 용도 |
|:---|:---|
| `Bash` | `port_ops.sh` 호출 (list/list_all/has/add/update/remove/status/kill/start/restart) |
| `AskUserQuestion` | 재시작 시 2+행 선택, 등록 시 서비스/명령/디렉토리 수집, 삭제 시 확인 |
| `Read` | 필요 시 `port_list.md` 원본 표시 |

## 데이터 파일

**스킬 폴더 안**에서 관리한다 — `.claude/skills/port_manager/port_list.md` (claude_toolkit 원본: `$HOME/claude_toolkit/.claude/skills/port_manager/port_list.md`). 여러 프로젝트가 같은 toolkit 을 공유하므로 한 파일이 모든 프로젝트의 SSOT 역할을 유지한다. `port_ops.sh` 는 스크립트와 같은 폴더의 `port_list.md` 를 기본 경로로 사용한다 (override 가 필요하면 환경변수 `PORT_LIST` 로).

스키마:

| 열 | 의미 | 비고 |
|---|---|---|
| 프로젝트 | `basename $CLAUDE_PROJECT_DIR` 와 정확히 일치 | 공백 trim |
| 포트 | TCP 포트 번호 | 정수 |
| 서비스 | 사람이 읽는 이름 | 예: "Web UI", "API" |
| 시작명령 | 셸에서 실행할 단일 명령 | 예: `npm run dev`, `uvicorn app:app --port 8000` |
| 작업디렉토리 | 프로젝트 루트 기준 상대경로 | 루트면 `—` |

## 스크립트 인터페이스

`${CLAUDE_PROJECT_DIR}/.claude/skills/port_manager/port_ops.sh` (없으면 `$HOME/claude_toolkit/.claude/skills/port_manager/port_ops.sh`).

```text
# 조회
port_ops.sh list <project>                          # TSV: 포트\t서비스\t시작명령\t작업디렉토리
port_ops.sh list_all                                # port_list.md 전체 그대로
port_ops.sh has  <project> <port>                   # YES(exit 0) / NO(exit 1)

# 편집 (표 mutation)
port_ops.sh add    <project> <port> <service> <cmd> <cwd>
port_ops.sh update <project> <port> <service> <cmd> <cwd>
port_ops.sh remove <project> <port>

# 프로세스
port_ops.sh status  <port>                          # "RUNNING <pid>" | "STOPPED"
port_ops.sh kill    <port>                          # "KILLED <pid>" | "NOT_RUNNING" | "KILL_FAILED <pid>"
port_ops.sh start   <port> <cwd> <cmd...>           # "STARTED pid=<pid> log=<path>"
port_ops.sh restart <port> <cwd> <cmd...>           # kill + start

# 자동 발견
port_ops.sh discover [project_root]                 # TSV: 포트\tPID\t시작명령\t작업디렉토리 (PROJECT_ROOT 안에 속한 LISTEN 만)
port_ops.sh inspect  [project_root]                 # 프로젝트 내부 설정 파일에서 "선언된 서버" 추출. 실행 여부 무관. TSV: source\t이름\t포트\t시작명령\t작업디렉토리. 미상 필드는 "—". 스캔 대상: .vscode/mcp.json · .cursor/mcp.json · .mcp.json · mcp.json · claude_desktop_config.json · .taskpilot/mcp-launchers.json. python3 필요. **deep inspect**: 포트가 "—" 인 행은 cmd 의 스크립트 파일(.py/.js/.ts/.mjs/.cjs/.sh)을 cwd 기준으로 열어 `uvicorn.run(...port=)`, `app.run(port=)`, `.listen()`, `os.environ.get("..._PORT", N)`, `--port N`, `PORT = N` 등의 패턴을 grep 으로 추가 탐색해 채운다. 이때 source 라벨에 `+deep` 접미사가 붙는다.
```

호출 시 항상 `PROJECT_ROOT="$CLAUDE_PROJECT_DIR"` 를 export 한다 (cwd 해석 기준).

## 절차 — 모드별

### 공통 준비

```bash
PROJECT="$(basename "$CLAUDE_PROJECT_DIR")"
OPS="$CLAUDE_PROJECT_DIR/.claude/skills/port_manager/port_ops.sh"
[ -x "$OPS" ] || OPS="$HOME/claude_toolkit/.claude/skills/port_manager/port_ops.sh"
export PROJECT_ROOT="$CLAUDE_PROJECT_DIR"
```

### 모드: 재시작 (인자 없음)

1. `"$OPS" list "$PROJECT"` 로 행 수집.
2. 행 수 분기:
   - **0개**: `[port_manager] <PROJECT> — 등록된 서버 없음. /port_manager <port> 또는 /port_manager add 로 등록하세요.` 출력 후 종료.
   - **1개**: 자동 선택 (한 줄로 표시).
   - **2+개**: `AskUserQuestion` 호출 (§AskUserQuestion 규약).
3. 선택된 행으로 재시작:
   - `"$OPS" status "$PORT"` → `RUNNING <pid>` 이면 알리고 `"$OPS" kill "$PORT"`.
   - `"$OPS" start "$PORT" "$CWD" $CMD` (CMD 는 단어 분리 허용, 따옴표 없이).
   - 2~3초 대기 후 `"$OPS" status "$PORT"` 재확인.
4. 결과 보고 (§출력 형식). **기동 성공 시 클릭 가능한 URL 링크를 별도 줄에 출력한다** — 반드시 코드블록(``` ```) 바깥에 마크다운 하이퍼링크 형식 `👉 [http://localhost:<PORT>](http://localhost:<PORT>)` 로. 코드블록 내부에 두면 클릭이 안 되므로 금지.

### 모드: 조회 (`show`)

1. `"$OPS" list "$PROJECT"` 결과를 출력 형식 (포트·서비스·시작명령·작업디렉토리) 로 정리해 표시. 재시작 절차는 건너뛴다.
2. 0행이면 미등록 메시지.

### 모드: 전체 조회 (`all` / `list`)

1. `"$OPS" list_all` 결과를 그대로 코드블록으로 출력.

### 모드: 자동 발견 등록 (`update` 또는 `update <path>`)

이미 떠 있는 서버를 스캔해 SSOT 에 일괄 등록·갱신한다. **포트 충돌(다른 프로젝트가 같은 포트 사용)을 보여주는 것**이 핵심.

**0. 대상 프로젝트 결정 (인자에 따라 분기)**:
   - 인자 없음 (`update`): `TARGET_DIR="$CLAUDE_PROJECT_DIR"`, `TARGET_PROJECT="$(basename "$TARGET_DIR")"` — 기본 동작.
   - 인자가 경로 (`update <path>`): `<path>` 를 절대경로로 정규화하여 `TARGET_DIR` 로 사용. `TARGET_PROJECT="$(basename "$TARGET_DIR")"`. 디렉토리 존재를 먼저 확인하고 없으면 `[port_manager] <path> — 디렉토리를 찾을 수 없습니다.` 출력 후 종료. 이하 절차에서 `$PROJECT`, `$CLAUDE_PROJECT_DIR` 자리에 각각 `$TARGET_PROJECT`, `$TARGET_DIR` 을 사용한다.
1. **두 가지 소스에서 동시 수집** (서버가 떠 있을 필요 없음):
   - **실행중**: `"$OPS" discover "$TARGET_DIR"` (TSV: 포트·PID·시작명령·작업디렉토리). LISTEN 중인 프로세스만 잡힘.
   - **선언**: `"$OPS" inspect "$TARGET_DIR"` (TSV: source·이름·포트·시작명령·작업디렉토리). 프로젝트 내부 설정 파일(`.vscode/mcp.json`, `.cursor/mcp.json`, `.mcp.json`, `claude_desktop_config.json`, `.taskpilot/mcp-launchers.json`)을 스캔. 실행 안 돼 있어도 잡힘. 포트나 cmd가 미상이면 `—`. `PROJECT_ROOT="$TARGET_DIR"` export 후 호출.
2. **둘 다 0행이면** `[port_manager] <TARGET_PROJECT> — 실행 중인 서버도, 선언된 서버도 찾지 못했습니다. /port_manager add 로 수동 등록하세요.` 출력 후 종료. (외부 경로 모드일 때 메시지 끝에 `대상 경로: <TARGET_DIR>` 한 줄 덧붙임.)
3. **머지·라벨링**:
   - 같은 `(포트, 시작명령)` 또는 `(이름)` 으로 양쪽에 동시 등장하면 한 행으로 합치고 `[실행중+선언]` 라벨.
   - 실행중만: `[실행중]` 라벨, pid 표시.
   - 선언만: `[선언:<source>]` 라벨. 예: `[선언:vscode-mcp]`, `[선언:claude-desktop]`, `[선언:taskpilot-launcher]`.
   - 각 후보에 대해 `"$OPS" has "$TARGET_PROJECT" "$PORT"` 결과를 보조 라벨로 추가 — YES면 `[등록됨]`, NO면 `[신규]`. 포트가 `—` 이면 보조 라벨 생략.
   - 신규 중 같은 포트가 다른 프로젝트 행에 있으면 `[충돌:<다른프로젝트>]` 라벨.
4. 후보 표를 §출력 형식대로 보여준다. 외부 경로 모드일 때 표 헤더에 `(외부: <TARGET_DIR>)` 명시.
5. `AskUserQuestion` (**multiSelect: true**) 로 등록·갱신할 항목을 고르게 한다 (§AskUserQuestion 규약).
6. 각 선택 항목에 대해 누락 필드를 보충:
   - **포트가 `—`**: 사용자에게 묻는다 (`AskUserQuestion`; 옵션 예시 + Other). stdio MCP(`claude-desktop` 등)는 포트 개념이 없으니 사용자가 `skip` 으로 응답하면 제외한다 (해당 행은 SSOT 에 추가하지 않고 결과 보고에서만 "stdio — 건너뜀" 으로 표시).
   - **시작명령이 `—`**: 사용자에게 묻는다. detect 값이 있으면 기본으로 제시.
   - **작업디렉토리가 `—`**: 사용자에게 묻는다. 외부 경로 모드면 `$TARGET_DIR` 기준 상대경로 또는 절대경로로 입력 받기.
   - **서비스 이름**: 사용자에게 묻는다(짧은 라벨). 기본으로 inspect 의 `이름` 또는 cmd 첫 토큰 제시.
7. 실행:
   - 신규: `"$OPS" add  "$TARGET_PROJECT" "$PORT" "<svc>" "<cmd>" "<cwd>"`
   - 등록됨(갱신): `"$OPS" update "$TARGET_PROJECT" "$PORT" "<svc>" "<cmd>" "<cwd>"`
   - 충돌: 사용자가 **그대로 진행 선택 시**에만 add. (충돌 자체는 차단하지 않지만, 같은 포트를 두 프로젝트가 동시에 쓸 수 없다는 점을 경고로 명시.)
8. 결과 행을 §출력 형식으로 보여준다. 외부 경로 모드면 안내 한 줄 추가: `이 행들은 <TARGET_PROJECT> 프로젝트 컨텍스트에서 /port_manager 로 재시작할 수 있습니다.`

### 모드: 등록·갱신 (`<숫자>` 또는 `add`)

1. **포트 결정**: 인자가 숫자면 그 값. `add` 인자면 `AskUserQuestion` 으로 받기.
2. **충돌 검사**:
   - `"$OPS" has "$PROJECT" "$PORT"` → YES면 갱신 모드, NO면 신규.
   - `grep` 으로 다른 프로젝트가 같은 포트를 쓰는지 확인. 충돌 시 경고를 출력하고 `AskUserQuestion` 으로 진행 여부 확인.
3. **필드 수집** (`AskUserQuestion` 4문항, 한 번에 묶기):
   - 서비스 이름 (예: "Web UI", "API")
   - 시작명령 (예: `npm run dev`)
   - 작업디렉토리 (프로젝트 루트 기준 상대경로; 루트면 `—` 입력 또는 빈칸)
   - 갱신 모드일 때만: 확인 ("기존 행을 갱신하시겠습니까?")
4. **실행**:
   - 신규: `"$OPS" add  "$PROJECT" "$PORT" "<svc>" "<cmd>" "<cwd>"`
   - 갱신: `"$OPS" update "$PROJECT" "$PORT" "<svc>" "<cmd>" "<cwd>"`
5. 결과 행을 출력 형식으로 한 줄 표시.

### 모드: 삭제 (`rm <port>` / `remove <port>`)

1. `"$OPS" has "$PROJECT" "$PORT"` → NO 면 `[port_manager] <PROJECT>:<PORT> — 등록되지 않음.` 종료.
2. 해당 행을 표시한 뒤 `AskUserQuestion` 으로 확인.
3. 확인 시 `"$OPS" remove "$PROJECT" "$PORT"`.

### 모드: 도움말 (`help` / `-h`)

본 SKILL.md 의 §인자 분기 표를 그대로 출력하고 종료. 다른 행동 없음.

## AskUserQuestion 규약

### 재시작 모드 — 2+ 행 선택

```yaml
question: "<PROJECT> 에 등록된 서버가 N개입니다. 어느 것을 재시작할까요?"
header: "서버 선택"
multiSelect: false
options:
  - label: "<SERVICE> :<PORT>"
    description: "<CMD>  @  <CWD>   현재: RUNNING <pid> | STOPPED"
```

- 옵션 description 에는 **현재 상태**(status 결과)를 미리 조회해 포함.
- 행이 4개를 초과하면 처음 3개만 보이고 4번째 옵션은 "그 외 N개는 직접 입력"; 사용자가 Other 로 응답.

### 자동 발견 모드 — 등록 대상 선택 (multiSelect)

```yaml
question: "<PROJECT> 에서 실행 중인 서버 N개를 찾았습니다. SSOT 에 등록·갱신할 항목을 모두 고르세요."
header: "등록 대상"
multiSelect: true
options:
  - label: "<PORT> · <SERVICE_INFERRED>"
    description: "[신규|등록됨|충돌:<other-proj>]  <CMD>  @  <CWD>   pid=<PID>"
```

- 옵션 label 의 `SERVICE_INFERRED` 는 cmdline 의 첫 토큰이나 알기 쉬운 키워드(예: `next-server` → "Web UI"). 추론이 어렵으면 `port:<PORT>` 만.
- description 에 분류 라벨을 **맨 앞**에 넣어 사용자가 충돌을 한눈에 본다.
- 후보가 4개 초과면 처음 3개 + Other "직접 입력".

### 등록 모드 — 필드 수집

질문 3개 또는 4개를 한 번에 묶어 보낸다 (Other 입력으로 자유 텍스트):

```yaml
- question: "서비스 이름은?"
  header: "서비스"
  options:
    - label: "Web UI"
    - label: "API"
    - label: "Worker"
- question: "시작명령은?"
  header: "시작명령"
  options:
    - label: "npm run dev"
    - label: "uvicorn app:app --reload"
- question: "작업디렉토리는? (프로젝트 루트 기준 상대경로)"
  header: "작업디렉토리"
  options:
    - label: "—  (프로젝트 루트)"
    - label: "web"
    - label: "server"
```

### 삭제 모드 — 확인

```yaml
question: "<PROJECT>:<PORT> (<SERVICE>) 를 정말 삭제할까요?"
header: "삭제 확인"
options:
  - label: "삭제"
  - label: "취소"
```

## 출력 형식

### 재시작 모드 — 1행 자동 선택

상태/로그 블록은 코드펜스 안, URL 하이퍼링크는 **반드시 코드펜스 바깥**에 별도 줄로 출력한다 (그래야 클릭 가능).

```
[port_manager] TaskPilot · Web UI :3000 (자동 선택, 등록 행 1개)
  npm run dev  @  web
  기존: RUNNING 42465  →  KILLED
  신규: RUNNING 51812  (log: /tmp/port_manager/TaskPilot-3000.log)
```

👉 [http://localhost:3000](http://localhost:3000)

URL 줄은 **기동 후 status 재확인이 `RUNNING` 일 때만** 출력한다. `STOPPED` 면 URL 줄을 생략하고 로그 경로 안내만 남긴다.

### 조회 모드

표 본문은 코드펜스 안에, **클릭 가능한 URL 목록은 코드펜스 바깥에 별도 섹션**으로 출력한다.

```
[port_manager] TaskPilot — 등록된 서버·포트 N개
  3000  Web UI   npm run dev  @  web
  8000  API      uvicorn app:app --reload  @  server
```

- 👉 [http://localhost:3000](http://localhost:3000) — Web UI
- 👉 [http://localhost:8000](http://localhost:8000) — API

비고가 `—` 면 ` @ —` 생략. 0행이면 `[port_manager] TaskPilot — 등록된 서버가 없습니다.` (URL 섹션 생략)

### 등록·갱신 모드

```
[port_manager] TaskPilot — 신규 등록:
  8000  API   uvicorn app:app --reload  @  server
```

갱신은 `신규 등록` → `행 갱신` 으로 변경.

### 자동 발견 모드 (`update` 또는 `update <path>`)

후보 표시 단계 — 라벨을 맨 앞에 둬 충돌을 한눈에 확인. 외부 경로 모드면 헤더에 경로 명시:

```
[port_manager] TaskPilot — 발견된 서버 N개
  [신규]              3000  next-server      pid=532946  @  web
  [등록됨]            8000  uvicorn          pid=611002  @  server
  [충돌: OtherProj]   5173  vite             pid=712345  @  web
```

외부 경로 모드 예 (`update /home/kimghw/connector_auth`) — `discover`(실행중)와 `inspect`(선언) 결과를 함께 표시:

```
[port_manager] connector_auth — 발견된 서버 N개 (외부: /home/kimghw/connector_auth)
  [실행중][신규]               8091  python  pid=44012  @  mcp_outlook/mcp_server
  [선언:vscode-mcp][신규]      8091  —       (outlook)  @  —
  [선언:claude-desktop][stdio] —     python ... server_stdio.py  (calendar)
  [선언:taskpilot-launcher]    —     .venv/bin/python mcp_todo/...  (todo)  @  —
```

- 실행중 + 선언이 같은 (포트, cmd) 로 매칭되면 `[실행중+선언:<source>]` 로 한 행으로 합칩니다.
- 포트가 `—` 인 행은 후속 단계에서 사용자에게 묻습니다. stdio 라 표시된 행은 `skip` 가능.

처리 결과:

```
[port_manager] TaskPilot — 자동 발견 등록 결과:
  + 신규  3000  Web UI   npm run dev  @  web
  ~ 갱신  8000  API      uvicorn app:app --reload  @  server
```

- `+` = 신규 add, `~` = 기존 행 update, `=` = 변경 없이 건너뜀.
- 0건이면 `[port_manager] <PROJECT> — 등록한 행이 없습니다.`
- 외부 경로 모드면 결과 블록 아래에 `이 행들은 <PROJECT> 프로젝트 컨텍스트에서 /port_manager 로 재시작할 수 있습니다.` 한 줄 추가.

### 삭제 모드

```
[port_manager] TaskPilot — 행 삭제:
  8000  API   uvicorn app:app --reload  @  server
```

## DO

- 스크립트로 위임한다 — Claude가 `ss`/`lsof`/`kill` 이나 표 마크다운을 직접 다루지 않는다.
- 재시작 모드에서 2+행이면 **반드시** `AskUserQuestion` 으로 사용자에게 묻는다.
- 시작 직후 status 재확인으로 기동 검증.
- 등록 시 다른 프로젝트가 같은 포트를 쓰면 충돌 경고를 띄우고 사용자에게 확인.
- 로그 경로를 결과에 포함해 디버깅 단서를 남긴다.
- **URL은 코드블록 바깥에 마크다운 하이퍼링크로 출력한다** — `👉 [http://localhost:<PORT>](http://localhost:<PORT>)`. 코드펜스 안에 두면 클릭이 안 된다.

## DON'T

- `port_list.md` 를 Edit/Write 로 직접 손대지 않는다. 모든 mutation 은 `port_ops.sh add/update/remove` 로.
- 다른 프로젝트의 행을 건드리지 않는다 (전체 조회 외).
- 시작명령을 "유추" 하지 않는다. 필요한 필드는 모두 사용자에게 묻는다.
- 기동 실패 시 자동 재시도 루프를 만들지 않는다.
- 인자가 숫자가 아닌 미지의 문자열이면 추측 실행하지 않는다 — `help` 안내.

## 흔한 함정

| 증상 | 원인 | 해결 |
|:---|:---|:---|
| `RUNNING` 인데 kill 후 다시 `RUNNING` | 부모 프로세스가 자식을 재spawn (예: `next dev` watcher) | `port_ops.sh kill` 은 LISTEN PID만 종료. 부모-자식 트리는 사용자가 직접 처리하도록 안내. |
| `STARTED` 직후 `STOPPED` | 시작명령이 즉시 실패 | 로그 경로 안내. 자동 재시작 안 함. |
| 행이 보이지 않음 | 프로젝트명 대소문자/공백 불일치 | `port_list.md` 첫 컬럼이 `basename $CLAUDE_PROJECT_DIR` 와 정확히 일치해야 함 |
| 표가 깨짐 | 셀에 `|`/`\` 가 들어감 | `port_ops.sh add/update` 가 자동 이스케이프함. Edit 로 수동 편집은 금지. |
| `add` 가 실패 ("row already exists") | 같은 (project,port) 행이 이미 있음 | `update` 사용 또는 먼저 `remove` |
| `inspect` 가 포트를 못 찾음 | 포트가 외부 설정 파일(.env, settings, config 클래스)이나 다른 모듈 import 로만 정의됨 / 스크립트가 표준 위치에 없음 | `--port` 인자나 환경변수로 명시 추가, 또는 `add` 로 직접 등록 |
| Deep inspect 가 잘못된 포트 잡음 | 스크립트 안에 여러 port 리터럴이 있고 첫 번째가 메인이 아님 | 결과를 사용자에게 보여주고 확정 전 검토. `add` 로 정확한 값 직접 등록 가능 |

## 체크리스트

- [ ] `$ARGUMENTS` 를 모드 분기 표에 맞게 해석했다.
- [ ] 모든 표 mutation 은 `port_ops.sh` 로 위임했다 (직접 편집 금지).
- [ ] 재시작 모드에서 행 수에 따라 분기(0/1/2+) 했다.
- [ ] 2+ 행에 대해 `AskUserQuestion` 으로 물었다.
- [ ] 등록 모드에서 다른 프로젝트의 포트 충돌을 검사했다.
- [ ] `update` 모드에서 `discover` 결과를 분류(신규/등록됨/충돌)해 사용자에게 보여줬다.
- [ ] `update` 모드 multiSelect 선택 결과만 add/update 했다 (선택 안 한 행은 건드리지 않음).
- [ ] kill 은 RUNNING 일 때만 호출했다.
- [ ] start 후 status 재확인을 수행했다.
- [ ] 결과 보고가 출력 형식을 따른다.
