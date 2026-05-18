---
description: "claude_toolkit 레포 git 자동화. ~/.claude/toolkit_dir 에 등록된 경로에서 동작 (어디서 호출하든 동일). 인자 없으면 stage+commit+push, 'pull'=pull, 'set'=경로 등록, 'show'=현재 경로, 'unset'=등록 해제"
allowed-tools: Bash, Read, Grep, Glob, AskUserQuestion
---

# /toolkit_git 명령

인자: $ARGUMENTS

## 대상 디렉토리 (`$TOOLKIT_DIR`)

이 명령은 **현재 실행 위치와 무관하게** `~/.claude/toolkit_dir` 파일에 기록된 claude_toolkit 레포 경로에서 동작한다. OS 별로 `$HOME` 이 다르므로(WSL=`/home/<user>`, Linux=`/home/<user>`, Windows Git Bash=`C:\Users\<user>`, macOS=`/Users/<user>`) 같은 머신에 WSL+Windows 가 공존해도 각 OS 가 자기 `~/.claude/toolkit_dir` 을 가진다.

- **파일 위치**: `~/.claude/toolkit_dir` (한 줄, 절대 경로).
- 파일이 없으면 `set` 안내 후 종료.

### TOOLKIT 식별자 (고정 상수)

```
CLAUDE_TOOLKIT_ROOT_ID=5a7a5dc046eda268d64df3af621de2c1640f0d66b0abe71fc2509f5e9562b319
```

이 ID 는 `<TOOLKIT_DIR>/.project_id` 파일에 기록돼 있다. `set` 동작은 이 ID 검증을 반드시 수행한다.

### 로드 절차 (`set` / `help` 이외 모든 인자에 선행)

1. `CONF="$HOME/.claude/toolkit_dir"` 존재 확인. 없으면 **현재 프로젝트 자동 등록 시도**:
   - 후보 경로를 순서대로 시도: `$CLAUDE_PROJECT_DIR` → `$PWD`.
   - 각 후보에 대해 `test -d "<후보>"` + `grep -q "$CLAUDE_TOOLKIT_ROOT_ID" "<후보>/.project_id" 2>/dev/null` 검사.
   - 매칭되면:
     - `mkdir -p "$HOME/.claude"` 후 절대 경로(`realpath` 또는 `cd "<후보>" && pwd -P`)를 `~/.claude/toolkit_dir` 에 한 줄 기록.
     - `[auto-set] 현재 프로젝트를 TOOLKIT_DIR 로 자동 등록: <경로>` 출력 후 step 2 로 계속 진행.
   - 어느 후보도 매칭 안 되면 기존 안내 출력 후 종료:
     ```
     $TOOLKIT_DIR 미설정 — /toolkit_git set 으로 먼저 경로를 등록하세요.
       /toolkit_git set            # 자동 탐색
       /toolkit_git set <path>     # 수동 지정
     ```
2. `TOOLKIT_DIR=$(head -n1 "$CONF")` 로 읽기.
3. 검증: `test -d "$TOOLKIT_DIR"` **AND** `grep -q "$CLAUDE_TOOLKIT_ROOT_ID" "$TOOLKIT_DIR/.project_id" 2>/dev/null` 둘 다 통과. 실패 시:
   ```
   ~/.claude/toolkit_dir 에 기록된 경로가 유효하지 않음: <TOOLKIT_DIR>
   /toolkit_git set 으로 재등록하세요.
   ```
   출력 후 종료.

## 동작 규칙

### 0. `help` / `-h` / `--help`

본 명령이 받는 인자 목록과 각 인자의 동작 설명만 출력하고 종료 (등록·git 작업 수행 안 함).

```
/toolkit_git [인자] — claude_toolkit 레포 전용 git 자동화

  이 명령은 "현재 쉘의 작업 디렉토리" 와 무관하게, OS 별로 한 번 등록해 둔
  claude_toolkit 레포 경로($TOOLKIT_DIR)에서 동작합니다. 등록 정보는
  ~/.claude/toolkit_dir 파일(한 줄, 절대경로)에 보관되며, $HOME 이 OS 마다
  다르므로 WSL · Linux · Windows Git Bash · macOS 가 자연스럽게 분리됩니다.
  최초 1회 `set` 으로 경로를 등록한 뒤 어디서든 호출하면 됩니다.

인자:

  (없음)            $TOOLKIT_DIR 에서 stage(-A) → 커밋 메시지 자동 생성(한국어 1줄)
                    → commit → push. 변경 없으면 push 만 시도.
                    (예: 다른 프로젝트 작업 중에도 toolkit 변경분을 한 줄로 푸시)

  pull              $TOOLKIT_DIR 에서 git pull 실행. 원본 최신 변경 반영.

  set [<path>]      ~/.claude/toolkit_dir 에 claude_toolkit 레포 경로를 등록.
                    - path 생략: OS 별 루트(WSL: /home·/mnt/c-e, Linux: /home·$HOME,
                      win_bash: /c-e·$USERPROFILE, darwin: $HOME·/Users)를
                      timeout 10s find 로 스캔해 .project_id 가 toolkit ID 와
                      일치하는 디렉토리를 자동 탐색.
                    - path 지정: 절대경로로 정규화 후 .project_id ID 검증.
                    매칭 0개면 자유 텍스트로 직접 입력, 2개 이상이면 AskUserQuestion
                    으로 선택.

  show              현재 등록된 $TOOLKIT_DIR, 브랜치, HEAD, status(clean/dirty) 출력.
                    어디서 호출하든 동일한 정보를 보여줍니다.

  unset             ~/.claude/toolkit_dir 파일 삭제. 다시 쓰려면 set 재실행.

  help | -h | --help
                    이 도움말 출력 (등록·git 작업 일절 수행 안 함).

  <그 외>           인자를 그대로 `git -C "$TOOLKIT_DIR"` 뒤에 전달.
                    (예: /toolkit_git status, /toolkit_git log --oneline -5,
                         /toolkit_git diff HEAD~1)

선행 검증 (`set`/`help` 제외 모든 인자):
  1) ~/.claude/toolkit_dir 존재 — 없으면 set 안내 후 종료.
  2) 기록된 경로가 실재 디렉토리.
  3) 그 디렉토리의 .project_id 가 toolkit 고정 ID 와 일치.
  하나라도 실패하면 `/toolkit_git set` 으로 재등록 안내 후 종료.

예시:
  /toolkit_git set                          # 최초 1회, OS 자동 탐색으로 등록
  /toolkit_git set /home/foo/claude_toolkit # 수동 지정
  /toolkit_git show                         # 현재 등록 상태 확인
  /toolkit_git                              # 변경분 자동 커밋·푸시
  /toolkit_git pull                         # 원격 변경 가져오기
  /toolkit_git status                       # toolkit 레포 상태 조회
  /toolkit_git unset                        # 등록 해제
```

### 1. `set [<path>]` — TOOLKIT_DIR 등록

**path 가 주어진 경우**:
- 절대 경로로 정규화 (`realpath` 또는 `cd "$path" && pwd -P`).
- `test -d <path>` + `grep -q "$CLAUDE_TOOLKIT_ROOT_ID" <path>/.project_id` 검증.
- 실패 시 에러 출력 후 종료 (`경로가 claude_toolkit 레포가 아닙니다 — ID 불일치 또는 .project_id 없음`).
- 통과 시 `mkdir -p "$HOME/.claude"` 후 `~/.claude/toolkit_dir` 에 한 줄 기록.

**path 생략 시 (자동 탐색)**:

1. OS 감지:
   ```
   UNAME="$(uname -s 2>/dev/null || echo unknown)"
   case "$UNAME" in
     Linux*)
       if grep -qi microsoft /proc/version 2>/dev/null; then OS_KIND="wsl";
       else OS_KIND="linux"; fi ;;
     Darwin*)              OS_KIND="darwin" ;;
     MINGW*|MSYS*|CYGWIN*) OS_KIND="win_bash" ;;
     *)                    OS_KIND="unknown" ;;
   esac
   ```

2. 탐색 루트 구성 (OS 별 — 존재하는 것만 남기고 중복 제거):
   - **wsl**: `/home /mnt/c /mnt/d /mnt/e $HOME`
   - **linux**: `$HOME /home`
   - **darwin**: `$HOME /Users`
   - **win_bash**: `/c /d /e $HOME` + `cygpath -u "$USERPROFILE" 2>/dev/null` (변환 가능 시)

3. 잡음 폴더 제외 + `timeout 10 find` 로 `.project_id` 수집:
   ```
   timeout 10 find <roots> \( -name node_modules -o -name .git -o -name .venv \
       -o -name dist -o -name build -o -name .cache \
       -o -name AppData -o -name Windows -o -name 'Program Files' \
       -o -name 'Program Files (x86)' -o -name ProgramData -o -name System32 \
       -o -name '$Recycle.Bin' -o -name Library \
     \) -prune \
     -o -type f -name '.project_id' -print 2>/dev/null
   ```
   `timeout` 이 exit 124 면 탐색 불완전임을 고지하고 `AskUserQuestion`(자유 텍스트)로 폴백.

4. `grep -l "$CLAUDE_TOOLKIT_ROOT_ID" <files>` 로 ID 매칭 후보 추출. 각 후보의 부모 디렉토리가 TOOLKIT_DIR 후보.

5. 매칭 개수별 분기:
   - **1개**: 그 경로로 확정 후 파일에 기록.
   - **2개 이상**: `AskUserQuestion` 으로 선택. 각 후보는 `<경로>  (HEAD <shortsha>)` 형식으로 표시. 4개 초과 시 상위 3개 + `그 외 직접 입력`.
   - **0개**: `AskUserQuestion`(자유 텍스트) 으로 경로 입력 요청. 입력값도 ID 검증, 실패 시 재질의.

**결과 출력**:
```
[set] TOOLKIT_DIR = <경로>
       기록 파일: ~/.claude/toolkit_dir
       HEAD: <shortsha> (<branch>, <clean|dirty>)
```

### 2. `show` — 현재 등록 경로 조회

로드 절차 수행 후:
```
TOOLKIT_DIR = <경로>
branch:  <branch>
HEAD:    <git -C "$TOOLKIT_DIR" log -1 --oneline 출력>
status:  <clean | N files changed>
```

### 3. `unset` — 등록 해제

- `~/.claude/toolkit_dir` 존재 시 삭제 → `[unset] removed ~/.claude/toolkit_dir`.
- 없으면 `[unset] 이미 등록되지 않음`.

### 4. 인자 없음 (기본 동작 — stage + commit + push)

- 로드 절차로 `$TOOLKIT_DIR` 확정.
- `git -C "$TOOLKIT_DIR" add -A` 로 모든 변경사항 스테이지.
- `git -C "$TOOLKIT_DIR" diff --cached --stat` 으로 스테이지 내용 확인.
- 변경 없음 → `git -C "$TOOLKIT_DIR" push` 만 실행 (이미 커밋된 분이 원격에 없을 수 있음) 후 종료.
- 변경 있음 → diff 분석해 한국어 1줄 커밋 메시지 자동 생성 → `git -C "$TOOLKIT_DIR" commit -m "<msg>"` → `git -C "$TOOLKIT_DIR" push` (upstream 없으면 `-u origin <branch>`).

### 5. `pull`

- `git -C "$TOOLKIT_DIR" pull` 실행하고 결과를 보여줌.

### 6. 그 외 인자

- 인자를 그대로 `git -C "$TOOLKIT_DIR"` 뒤에 전달 (예: `/toolkit_git status` → `git -C "$TOOLKIT_DIR" status`).

## 예시

- `/toolkit_git set` → 자동 탐색해 TOOLKIT_DIR 등록.
- `/toolkit_git set /home/foo/claude_toolkit` → 지정 경로 등록(ID 검증 포함).
- `/toolkit_git show` → 현재 등록 경로·브랜치·HEAD 출력.
- `/toolkit_git` → TOOLKIT_DIR 에서 stage+commit+push.
- `/toolkit_git pull` → TOOLKIT_DIR 에서 git pull.
- `/toolkit_git status` → TOOLKIT_DIR 에서 git status.
- `/toolkit_git unset` → 등록 해제.
