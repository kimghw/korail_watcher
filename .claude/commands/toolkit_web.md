---
description: "claude_toolkit 웹서버(web_service/server.py) 실행. Linux·WSL·Windows(Git Bash) 공통 래퍼 — uname 으로 OS 를 감지해 python 명령·탐색 루트를 자동 분기한 뒤 web_service/run.py 호출."
argument-hint: "[port] | bg [port] | stop | status"
allowed-tools: Bash, Read, Grep, Glob, AskUserQuestion
---

<!-- markdownlint-disable -->

# /web 명령 — claude_toolkit 웹서버 실행

인자: $ARGUMENTS

## 역할 분리 (중요)

이 레포의 웹서버는 **3계층**으로 분리돼 있다:

| 계층 | 파일 | 역할 | 플랫폼 |
|------|------|------|--------|
| 앱 | `web_service/server.py` | FastAPI 앱(ASGI `server:app`) | Linux · WSL · Windows |
| 런처 | `web_service/run.py` | venv 준비·포트 점검·기동·PID 관리·stop/status | Linux · WSL · Windows |
| 래퍼 | `.claude/commands/web.md` (이 파일) | OS 감지 → `CLAUDE_TOOLKIT_ROOT` 탐지 → 런처 호출 | Linux · WSL · **Windows(Git Bash)** |

**PowerShell/cmd** 에서 Claude Code 를 쓰는 경우에만 슬래시 커맨드 대신 레포에서 직접:

```powershell
cd <CLAUDE_TOOLKIT_ROOT>\web_service
py run.py              # 포어그라운드, 포트 8765
py run.py bg           # 백그라운드
py run.py stop         # 종료
py run.py status       # 상태
```

`run.py` 자체가 venv 생성·의존성 설치·포트 점검·Windows 분기(`CREATE_NEW_PROCESS_GROUP`, `taskkill`)까지 전부 처리한다.

## OS / Python 감지 (모든 동작에 선행)

```bash
UNAME="$(uname -s 2>/dev/null || echo unknown)"
case "$UNAME" in
  Linux*)
    if grep -qi microsoft /proc/version 2>/dev/null; then OS_KIND="wsl";
    else OS_KIND="linux"; fi ;;
  Darwin*)  OS_KIND="darwin" ;;
  MINGW*|MSYS*|CYGWIN*) OS_KIND="win_bash" ;;
  *) OS_KIND="unknown" ;;
esac

# python 명령 우선순위: python3 → py → python
for c in python3 py python; do
  if command -v "$c" >/dev/null 2>&1; then PYCMD="$c"; break; fi
done
[ -z "${PYCMD:-}" ] && { echo "python3/py/python 이 모두 없음"; exit 1; }
```

- `OS_KIND=linux` 또는 `wsl` → `PYCMD=python3` 기대.
- `OS_KIND=win_bash` (Git Bash / MSYS / Cygwin — Windows 네이티브 Claude Code 의 기본 Bash) → `PYCMD=py` 또는 `python` 기대.
- `OS_KIND=darwin` → `python3` 기대.

## 경로 정의

- `$CLAUDE_TOOLKIT_ROOT` — `claude_toolkit` 레포 루트. 아래 **탐지** 절차로 매번 결정한다.
- `$WEB = $CLAUDE_TOOLKIT_ROOT/web_service` — `server.py`, `run.py`, `requirements.txt` 존재 확인.
- **`CLAUDE_TOOLKIT_ROOT` 식별자** (고정 상수):

  ```
  CLAUDE_TOOLKIT_ROOT_ID=5a7a5dc046eda268d64df3af621de2c1640f0d66b0abe71fc2509f5e9562b319
  ```

  이 값은 `$CLAUDE_TOOLKIT_ROOT/.project_id` 에 기록돼 있으며, ID 일치 + `web_service/server.py` 존재 둘 다 통과하는 디렉토리만 유효.

## 탐지 (매번 실행)

각 단계에서 후보가 나오면 **반드시 `<후보>/web_service/server.py` 존재까지** 확인한 뒤 확정한다.

1. **환경변수 빠른 경로** — `$CLAUDE_TOOLKIT_ROOT` 설정돼 있으면:
   - `grep -q "$CLAUDE_TOOLKIT_ROOT_ID" "$CLAUDE_TOOLKIT_ROOT/.project_id" 2>/dev/null` 로 ID 매칭 확인.
   - `test -f "$CLAUDE_TOOLKIT_ROOT/web_service/server.py"` 로 존재 확인.
   - 둘 다 통과 → 그대로 사용.
   - 하나라도 실패 → 재탐색 안내 후 다음 단계로.

2. **현재 프로젝트 자체가 toolkit인지** — `$CLAUDE_PROJECT_DIR/.project_id` 의 ID 매칭 + `$CLAUDE_PROJECT_DIR/web_service/server.py` 존재 둘 다 통과하면 확정.

3. **파일명 기반 탐색** — `OS_KIND` 에 따라 루트가 달라진다:

   ```bash
   case "$OS_KIND" in
     wsl)      ROOTS="/mnt/c /mnt/d /mnt/e $HOME /home" ;;
     linux|darwin) ROOTS="$HOME /home" ;;
     win_bash) ROOTS="/c /d /e $HOME ${USERPROFILE:+$(cygpath -u "$USERPROFILE" 2>/dev/null)}" ;;
     *) ROOTS="$HOME" ;;
   esac
   ROOTS="$ROOTS ${CLAUDE_PROJECT_DIR:-$PWD}/.. ${CLAUDE_PROJECT_DIR:-$PWD}/../.."
   ```

   - 존재하는 루트만 남기고 중복 제거.
   - 잡음 폴더 제외하며 `.project_id` 탐색:

     ```
     find <roots> \( -name node_modules -o -name .git -o -name .venv \
         -o -name dist -o -name build \) -prune \
         -o -type f -name '.project_id' -print 2>/dev/null
     ```

   - `grep -l "$CLAUDE_TOOLKIT_ROOT_ID" <file>` 로 ID 매칭 후보 수집, `<부모>/web_service/server.py` 존재 확인.
   - **`.project_id` 위치로 환경 보조 판정**: 매칭된 파일 경로가 `/mnt/*` 또는 `/c|/d|/e/*` 로 시작하면 Windows 파일시스템 위에 있다는 뜻이므로, UI 의 Browse 모달이 /mnt 스타일로 뜨거나 symlink 모드가 차단될 수 있음을 고지.

4. **매칭 개수별 분기**:
   - **1개**: 확정.
   - **2개 이상**: `AskUserQuestion`으로 선택.
   - **0개**: 에러 후 `AskUserQuestion`(자유 텍스트)으로 경로 입력받음.

5. **사후**: `CLAUDE_TOOLKIT_ROOT = <경로>` 보고. 환경변수 미설정이면 안내만 (자동 수정 금지):

   ```
   export CLAUDE_TOOLKIT_ROOT="<확정 경로>"
   ```

## 인자 → 런처 위임

모든 인자는 그대로 `$PYCMD $WEB/run.py <인자…>` 로 전달한다. `$PYCMD` 는 위 **OS / Python 감지** 단계에서 결정된 값.

| 인자 | 런처 동작 |
|------|-----------|
| `help` / `-h` / `--help` | 본 표(인자 목록과 각 런처 동작)만 출력하고 종료. 서버 기동/종료/탐지 수행 안 함. |
| (없음) | 포어그라운드, 포트 8765 |
| `<숫자>` | 포어그라운드, 지정 포트 |
| `bg` / `background` | 백그라운드, 포트 8765 |
| `bg <숫자>` | 백그라운드, 지정 포트 |
| `stop` | 백그라운드 프로세스 종료 (`.server.pid`) |
| `status` | 현재 상태 조회 |

## 동작 순서

### 공통 사전 점검

1. `$WEB/server.py`, `$WEB/run.py` 존재 확인 — 없으면 중단.
2. `"$PYCMD" --version` 확인 (3.10+ 권장). 없으면 설치 안내.
   - Linux/WSL: `sudo apt-get install -y python3 python3-venv`
   - Windows(Git Bash): https://www.python.org/downloads/ (또는 `winget install Python.Python.3`)
3. **venv/의존성 설치는 `run.py` 내부에서 자동 처리** — 래퍼는 관여하지 않는다.
   - `python3-venv` 패키지 미설치로 venv 생성 실패 시(Linux) 위 안내.
   - 시스템 파이썬 직접 설치를 원하면 `CLAUDE_TOOLKIT_NO_VENV=1 /web …` 로 호출.

### 기동 (인자 없음 / 숫자 / `bg` / `bg <숫자>`)

```bash
cd "$WEB" && "$PYCMD" "$WEB/run.py" $ARGUMENTS
```

- 포트 점검·venv 준비·PID 기록 모두 런처가 담당.
- 포어그라운드는 Ctrl+C 로 종료.
- 백그라운드는 시작 직후 5초 이내 `127.0.0.1:$PORT` TCP 핸드셰이크 확인까지 런처가 수행.
- Windows(Git Bash) 에서 백그라운드 기동 시 런처 내부적으로 `CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS` 를 사용한다.

### `stop` / `status`

```bash
"$PYCMD" "$WEB/run.py" stop     # 또는 status
```

Windows 에서 `stop` 은 내부적으로 `taskkill /PID … /F /T` 를 사용한다.

## 동작 규칙

- **호스트는 기본 `127.0.0.1`**. 외부 노출은 `HOST=0.0.0.0 python server.py` 로 직접 실행하거나, uvicorn 을 수동 기동.
- **포트 자동 변경 금지**: 점유 시 런처가 에러 반환. 사용자가 다른 포트로 재시도.
- **의존성은 `$WEB/.venv` venv 기반**. `CLAUDE_TOOLKIT_NO_VENV=1` 시만 시스템 파이썬에 설치.

## Claude 어시스트 (UI 기능)

웹 UI 하단 `🤖 Claude 어시스트` 패널. 자연어 질의 → 카탈로그(`skills/agents/commands/references`) 중 관련 항목 체크박스 자동 선택.

- **백엔드**: `POST /api/assist` — 서버가 `claude -p` 서브프로세스 호출, 90초 타임아웃.
- **응답**: `{"items": [...], "reason": "..."}` 화이트리스트 필터.
- **Enter 키**로 질의, `이전 선택 해제` 버튼은 마지막 어시스트가 켠 체크박스만 해제.
- **사전조건**: PATH 상에 `claude` CLI + `claude /login` 인증 완료.

## 예시

- `/web` → 127.0.0.1:8765 포어그라운드.
- `/web 9000` → 127.0.0.1:9000 포어그라운드.
- `/web bg` → 백그라운드, 기본 포트.
- `/web bg 9000` → 백그라운드, 포트 9000.
- `/web status` → 상태 조회.
- `/web stop` → 백그라운드 서버 종료.
