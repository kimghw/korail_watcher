---
description: "Windows/복사 방식: claude_toolkit 원본(.project_id ID)을 grep으로 탐지한 뒤 .claude/를 복사 동기화. pull=원본→로컬(교집합), push=로컬→원본+git push, push <filepath>=특정 파일만 복붙+커밋+푸시"
allowed-tools: Bash, Read, Grep, Glob, AskUserQuestion
---

# /toolkit_merge_win 명령

인자: $ARGUMENTS

Windows/WSL 혼용 환경에서 심볼릭 링크가 번거롭거나 동작하지 않을 때 사용한다. 원본 `claude_toolkit` 레포의 `.claude/` 콘텐츠를 **파일 복사**로 현재 프로젝트와 양방향 동기화한다. 심볼릭 방식은 `/toolkit_link` 참조.

## 사전 조건 (필수)

**로컬 `$CLAUDE_PROJECT_DIR/.claude/` 는 원본에서 "파일 복사"로 받아온 실파일 트리여야만 동작한다.**

- 대상: 실제 파일(regular file)과 실제 디렉토리(regular directory)로 구성된 `.claude/` 트리.
- **금지**: `.claude/` 자체 또는 그 하위 어느 경로라도 **심볼릭 링크 / 바로가기 / junction / WSL LX_SYMLINK 리파스 포인트** 가 포함된 경우. 이 경우 본 명령은 즉시 중단하고 사용자에게 `/toolkit_link status` 로 확인할 것을 안내한다.
- 이유: 본 명령의 동기화는 `cp -f` 기반이라, 링크가 섞여 있으면 원본을 그대로 덮어써 실제 대상 파일이 파손되거나 링크 타깃이 의도치 않게 수정될 수 있다.

### 링크 감지 절차 (모든 동작에 선행)

1. `test -L "$CLAUDE_PROJECT_DIR/.claude"` — `.claude` 루트 자체가 링크면 중단.
2. `find "$CLAUDE_PROJECT_DIR/.claude" -type l -print` — 하위에 링크가 **하나라도** 있으면 중단.
3. Windows junction/리파스 포인트 확인이 필요한 경우 (WSL에서 `/mnt/*` 경로), 추가로 `ls -la` 출력 상 `->` 표시를 함께 점검.
4. 링크가 발견되면 경로 목록을 보고하고 다음 메시지로 종료:
   > `.claude/` 트리에 심볼릭/junction 링크가 포함되어 있습니다. `toolkit_merge_win` 은 복사 방식 전용이므로 중단합니다. 링크 관리가 필요하면 `/toolkit_link status` 를 사용하세요.

## 경로 정의

- **로컬(소비자) 프로젝트**: `$CLAUDE_PROJECT_DIR` — 본 명령을 실행하는 프로젝트 루트. 동기화 대상은 `$CLAUDE_PROJECT_DIR/.claude/`.
- **원본 레포(claude_toolkit)**: `$CLAUDE_TOOLKIT_ROOT`. 본 문서에서는 편의상 `$TOOLKIT`으로도 표기. 실제 경로는 아래 **원본 탐지** 절차로 매번 결정한다.
- **`CLAUDE_TOOLKIT_ROOT` 식별자** (고정 상수, 하드코딩):
  ```
  CLAUDE_TOOLKIT_ROOT_ID=5a7a5dc046eda268d64df3af621de2c1640f0d66b0abe71fc2509f5e9562b319
  ```
  이 값은 `$CLAUDE_TOOLKIT_ROOT/.project_id` 파일에 기록돼 있으며, 해당 파일의 내용이 이 ID와 일치하는 디렉토리만 유효한 `$CLAUDE_TOOLKIT_ROOT`로 인정한다.

## 원본 탐지 (모든 동작에 선행, 매번 실행)

0. **사용자 힌트 빠른 경로** — 현재 대화에서 사용자가 원본 경로를 직접 언급했다면(예: "원본은 `/home/foo/claude_toolkit` 에 있다"):
   - 제시된 경로에 대해 `grep -q "$CLAUDE_TOOLKIT_ROOT_ID" "<path>/.project_id" 2>/dev/null` 로 **반드시 ID 검증**.
   - ID 일치 + `<path>/.claude/` 존재 → 즉시 확정, step 1~3 전부 스킵.
   - ID 불일치/파일 없음 → `"사용자 제시 경로는 toolkit 레포가 아닙니다(ID 불일치)"` 고지 후 step 1 로 진행.
   - **주의**: 대화상 언급된 경로를 ID 검증 없이 채택하지 말 것. 잘못된 경로 채택은 엉뚱한 디렉토리를 원본으로 오인해 `push` 시 치명적 파괴를 일으킬 수 있다.

1. **환경변수 빠른 경로** — `$CLAUDE_TOOLKIT_ROOT`가 설정되어 있으면:
   - `grep -q "$CLAUDE_TOOLKIT_ROOT_ID" "$CLAUDE_TOOLKIT_ROOT/.project_id" 2>/dev/null` 로 매칭 확인.
   - 일치 → 그대로 사용하고 탐색 스킵.
   - 불일치/파일 없음 → 환경변수 무효로 간주. `"CLAUDE_TOOLKIT_ROOT이 유효하지 않음 — 재탐색합니다"` 고지 후 다음 단계로 폴백.

2. **파일명 기반 탐색 (느린 경로)** — **WSL · Windows 양측 루트를 모두 포함**한다:
   - 현재 OS 감지:
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
   - 탐색 루트 후보(OS 무관하게 **WSL 쪽 + Windows 쪽 경로를 같이** 구성한 뒤, 존재하는 것만 남기고 중복 제거):
     - **WSL/Linux 쪽**: `$HOME`, `/home`
     - **WSL 에서 본 Windows 드라이브**: `/mnt/c /mnt/d /mnt/e` (WSL 에서만 실제 존재)
     - **Windows(Git Bash/MSYS/Cygwin) 드라이브 루트**: `/c /d /e` (win_bash 환경에서만 실제 존재)
     - **Windows 사용자 프로필**: `$USERPROFILE` (win_bash 에서 `cygpath -u "$USERPROFILE"` 로 POSIX 경로 변환, 변환 실패 시 skip)
     - **상위 2단**: `$CLAUDE_PROJECT_DIR/..`, `$CLAUDE_PROJECT_DIR/../..`
   - 위 목록을 그대로 `test -d` 로 필터링하여 존재하는 것만 보존. 한쪽 OS 의 경로가 현재 환경에 없으면 자연히 탈락하므로, WSL 에서 호출해도 Windows 에서 호출해도 동일한 명세를 재사용할 수 있다.
   - 잡음 폴더는 `prune`로 제외하고, `timeout 10` 으로 전체 탐색 시간을 제한:
     ```
     timeout 10 find <roots> \( \
         -name node_modules -o -name .git -o -name .venv \
         -o -name dist -o -name build -o -name .cache \
         -o -name AppData -o -name Windows \
         -o -name 'Program Files' -o -name 'Program Files (x86)' \
         -o -name ProgramData -o -name System32 \
         -o -name '$Recycle.Bin' -o -name Library \
       \) -prune \
       -o -type f -name '.project_id' -print 2>/dev/null
     ```
   - `timeout` 이 exit 124 로 종료된 경우 탐색 결과가 불완전할 수 있음을 고지하고, 아래 **매칭 개수별 분기**의 **0-match 분기**로 진입해 `AskUserQuestion`(자유 텍스트)으로 경로를 직접 받는다.
   - 후보 각각에 대해 `grep -l "$CLAUDE_TOOLKIT_ROOT_ID" <file>` 로 ID 매칭 여부 확인.
   - **환경 보조 판정**: 매칭된 `.project_id` 경로가 `/mnt/*` 또는 `/c|/d|/e/*` 로 시작하면 Windows 파일시스템 위의 저장소라는 뜻이므로, 후속 복사(`cp -f`)에서 퍼미션/EOL 이슈가 날 수 있음을 보고에 같이 남긴다.
   - **Cross-boundary fallback (dubious ownership 대응)**: `git -C "$TOOLKIT" …` 실행 중 `fatal: detected dubious ownership in repository` 가 감지되면 **스킬은 자동 전환을 하지 않고**, 아래 두 우회안 중 하나를 사용자에게 안내만 한다:
     1. **`wsl.exe` 경유 실행** (Git Bash 에서 WSL 내부 레포 접근 시):
        ```
        wsl.exe -d <distro> -e bash -c 'cd "<TOOLKIT 경로>" && git …'
        ```
     2. **`safe.directory` 등록** (사용자 본인이 직접 실행):
        ```
        git config --global --add safe.directory "<TOOLKIT 경로>"
        ```
     스킬은 `git config` 를 자동 수정하지 않는다. 안내만 제공하며, 우회 명령은 사용자가 직접 수행해야 한다.

3. **매칭 개수별 분기**:
   - **정확히 1개**: 그 파일의 부모 디렉토리를 `$CLAUDE_TOOLKIT_ROOT`으로 확정.
   - **2개 이상**: **`AskUserQuestion`으로 사용자에게 선택을 묻는다**. 각 후보를 `<경로>  (HEAD <shortsha>)` 형식으로 선택지로 제시. 후보가 4개를 넘으면 상위 3개 + `그 외 직접 입력` 옵션으로 구성하고 본문에 전체 목록을 나열한다.
   - **0개**: 에러 고지 후 `AskUserQuestion`(자유 텍스트 입력)으로 `$CLAUDE_TOOLKIT_ROOT` 경로 직접 지정 요청. 입력받은 경로 역시 `.project_id`의 ID가 일치해야 수용, 불일치면 재질의.

4. **확정 후 사후 처리**:
   - 보고: `CLAUDE_TOOLKIT_ROOT = <경로>  (HEAD <shortsha>, <clean|dirty>)`.
   - `$CLAUDE_TOOLKIT_ROOT` 환경변수가 미설정이거나 확정 경로와 다르면, 쉘 rc에 다음을 추가하도록 **안내만** 한다(자동 수정 금지):
     ```
     export CLAUDE_TOOLKIT_ROOT="<확정 경로>"
     ```
   - **자기 자신 방지**: `realpath "$CLAUDE_TOOLKIT_ROOT"` == `realpath "$CLAUDE_PROJECT_DIR"` 이면 "로컬 == 원본" 에러로 즉시 중단 (claude_toolkit 레포 자체에서 실행된 경우).

## 공통 규칙

- **동기화 대상**: `.claude/` 하위 전체 (`agents/`, `commands/`, `skills/`, `references/`, 기타 파일).
- **제외 (exclude)**:
  - `settings.local.json` — 프로젝트 로컬 설정, 공유 금지.
  - `.project_id` — 원본 식별 파일, 복사 금지.
  - `.git/`, `.DS_Store`, `*.swp`, `*.tmp` — 잡파일.
- **심볼릭 링크 처리**: 사전 조건 절차에서 로컬에 링크가 있으면 이미 중단되었으므로, 이 단계에 도달한 시점의 로컬은 순수 복사 트리임이 보장된다. 원본 `$TOOLKIT/.claude/` 쪽에 링크가 섞여 있으면 해당 파일은 복사 대신 **스킵**하고 그 사실을 리포트한다.

## 인자별 동작

### 0. `help` / `-h` / `--help` — 인자 도움말

- 본 명령이 받는 인자(인자 없음=`diff`, `pull`, `push [<filepath>...] [--allow-dirty-origin]`, `diff`)와 각 동작 설명만 요약 출력하고 종료. 원본 탐지·파일 복사·git 작업 전부 수행하지 않는다.

### 1. `pull` — 원본 → 로컬, **교집합만**

- 로컬 `.claude/` 기준으로 재귀 순회하며, 각 파일 경로가 `$TOOLKIT/.claude/<rel>`에도 존재하는지 확인.
- **양쪽 모두 존재하는 파일만** 원본 버전으로 덮어쓴다. 원본에만 있는 신규 파일은 **가져오지 않는다** (교집합 원칙).
- 로컬에만 있는 파일(로컬 추가분)은 건드리지 않는다.
- 절차:
  1. **원본 dirty 사전 검사**: `git -C "$TOOLKIT" status --porcelain .claude` 실행.
     - clean → 정상 진행.
     - dirty → 경고 배너 출력:
       > ⚠ 원본 `$TOOLKIT/.claude/` 에 커밋되지 않은 변경이 있습니다. pull 은 **커밋된 버전이 아닌 working tree 현재 상태**를 복사합니다.
       dirty 파일 목록을 보여주고 사용자에게 계속할지 확인. 미확인 시 중단.
  2. 사전 계획: 갱신 예정 목록 / 원본-only 스킵 목록 / 로컬-only 보존 목록을 테이블로 표시하고 사용자 승인 대기.
  3. 변경이 큰 항목은 `diff -u`로 샘플 몇 개를 사전 표시.
  4. 실행: 각 대상에 대해 `cp -f "$TOOLKIT/.claude/<rel>" "$CLAUDE_PROJECT_DIR/.claude/<rel>"`.
- 결과 보고: `갱신 N · 동일 M · 원본-only 스킵 K · 로컬-only 보존 L`.

### 2. `push [<filepath>...] [--allow-dirty-origin]` — 로컬 → 원본 + `git push`

두 가지 모드:
- **전체 push** (`<filepath>` 인자 없음): `.claude/` 하위 전체 동기화.
- **부분 push** (`<filepath>` 인자 1개 이상): 지정한 파일만 복붙 + commit + push.

#### 2a. 전체 push (인자 없음)

- 로컬 `.claude/` 하위 전체를 원본 `$TOOLKIT/.claude/` 하위로 복사. 기존 파일은 **덮어쓰기**.
- 원본에만 있던 파일(로컬에 없는 파일)은 **삭제하지 않음** (안전 기본값).
- 절차:
  1. **원본 dirty 사전 검사 + 차단**: `git -C "$TOOLKIT" status --porcelain .claude` 를 **복사 전에 먼저** 실행.
     - clean → 정상 진행.
     - dirty → **기본적으로 중단**. 이유: 로컬 sync 분과 origin-로컬 미커밋 변경분이 같은 자동 커밋에 혼합되어 디버깅 불가능한 혼종 커밋이 만들어지기 때문.
       - 사용자가 `push --allow-dirty-origin` 플래그를 **명시적으로** 넘긴 경우에만 진행. 이 경우에도 dirty 파일 목록 + "혼합 커밋이 생성될 수 있음" 경고를 반드시 표시.
       - 그 외에는 `"원본 dirty — push 중단. 원본에서 먼저 커밋하거나 push --allow-dirty-origin 으로 강제 실행하세요."` 메시지와 함께 종료.
  2. 사전 계획: 복사 대상 / 신규 생성 / 덮어쓰기 목록을 보여주고 사용자 승인 대기.
  3. 실행: `cp -f` 파일 단위 복사, 신규 상위 디렉토리는 `mkdir -p`.
  4. `git -C "$TOOLKIT" status --porcelain .claude` 로 변경 확인.
  5. 변경 없음 → `"푸시할 변경 없음"` 출력 후 종료.
  6. 변경 있음 →
     - `git -C "$TOOLKIT" add -A .claude`
     - `git -C "$TOOLKIT" diff --cached --stat .claude` 표시
     - diff 기반 **한국어 1줄** 커밋 메시지 자동 생성 (예: `commands: toolkit_merge_win 추가, skills/pdf2md 갱신`)
     - `git -C "$TOOLKIT" commit -m "<msg>"`
     - `git -C "$TOOLKIT" push` (upstream 없으면 `-u origin <branch>`)
- 결과 보고: 복사 파일 수, 커밋 해시, push 결과.

#### 2b. 부분 push (`<filepath>` 인자 사용)

지정한 파일만 원본의 동일 상대 경로로 복붙한 뒤 그 파일들에 한해 commit + push 한다. **다른 파일의 dirty 는 무시**되므로 원본 작업 도중에도 안전하게 단일 파일을 밀어 올릴 수 있다.

##### 인자 형식

`<filepath>` 는 다음 중 어느 형태든 허용. 모두 `.claude/` 하위 **상대 경로**로 정규화한다:

| 입력 형태 | 예시 |
|---|---|
| 절대 경로 (Windows / POSIX) | `c:\vscode\hwpx-docx\.claude\commands\set_subAgents.md`<br>`/c/vscode/hwpx-docx/.claude/commands/set_subAgents.md` |
| 프로젝트 루트 기준 상대 경로 | `.claude/commands/set_subAgents.md` |
| `.claude/` 내부 상대 경로 | `commands/set_subAgents.md` |

##### 검증 (각 인자에 대해, 하나라도 실패하면 전체 중단)

1. 정규화 결과가 `realpath "$CLAUDE_PROJECT_DIR/.claude/"` **하위**에 있어야 함. 트리 밖 경로 거부.
2. 로컬에 실제 파일로 존재 (`-f`).
3. 제외 목록(`settings.local.json`, `.project_id`, `.git/*`, `*.swp`, `*.tmp`)에 해당하면 거부.
4. 심볼릭 링크면 거부 (사전 조건 위반).

##### 절차

1. **원본 dirty 사전 검사 (좁힌 범위)**:
   ```
   git -C "$TOOLKIT" status --porcelain -- .claude/<rel1> .claude/<rel2> ...
   ```
   - clean → 정상 진행.
   - 지정 파일에 한해 dirty → 전체 push 와 동일한 정책: 기본 중단, `--allow-dirty-origin` 명시 시에만 진행.
   - 지정 외 파일의 dirty 는 **무시**(부분 push 의 핵심 가치).
2. 사전 계획: 복사 대상 파일 목록과 각 항목의 `cp` 전후 `diff --stat` 또는 `diff -u` 샘플 표시 후 사용자 승인 대기.
3. 실행: 각 인자에 대해 `mkdir -p "$(dirname "$TOOLKIT/.claude/<rel>")"` + `cp -f "$CLAUDE_PROJECT_DIR/.claude/<rel>" "$TOOLKIT/.claude/<rel>"`.
4. `git -C "$TOOLKIT" add -- .claude/<rel1> .claude/<rel2> ...` (해당 파일만 스테이징, `add -A` 금지).
5. `git -C "$TOOLKIT" diff --cached --stat -- .claude/<rel1> ...` 표시.
6. 변경 없음 → `"푸시할 변경 없음 (지정 파일이 원본과 동일)"` 출력 후 종료.
7. 변경 있음 →
   - diff 기반 **한국어 1줄** 커밋 메시지 자동 생성. 부분 push 는 지정 파일명을 그대로 노출 (예: `commands/set_subAgents.md 갱신` 또는 다중 시 `commands/set_subAgents.md, skills/foo/SKILL.md 갱신`).
   - `git -C "$TOOLKIT" commit -m "<msg>"`
   - `git -C "$TOOLKIT" push` (upstream 없으면 `-u origin <branch>`)
- 결과 보고: 처리 파일 수, 커밋 해시, push 결과.

### 3. `diff` — 미리보기 (변경 없음)

- pull/push 실행 시 보게 될 계획 테이블만 조회.
- 섹션 분리:
  - `원본 → 로컬 (pull 시 반영될 것)` — 교집합 대상 중 내용이 다른 항목.
  - `로컬 → 원본 (push 시 반영될 것)` — 로컬에 있고 원본과 다르거나 원본에 없는 항목.
- 각 항목: `<rel>   원본-sha vs 로컬-sha (±N줄)` 형식.

### 4. 인자 없음 또는 기타

- 인자 없음 → **`diff`와 동일하게 동작** (변경 미리보기만, 실제 파일 변경·`git commit`·`push` 없음). 파괴적 동작(`pull`/`push`)은 사용자가 반드시 **명시적으로 입력**해야만 수행된다.
- 첫 번째 인자가 `pull` / `push` / `diff` 가 아닌 미상의 토큰이면 → `pull` / `push` 의 부속 인자(filepath 등)인지 모호하므로 사용법 요약 출력 후 종료. 부분 push 는 반드시 첫 토큰을 `push` 로 시작해야 인식된다 (예: `push commands/foo.md`).
- 알 수 없는 인자 → 사용법 요약 출력 후 종료.

> ⚠ **안전 기본값**: 인자 없이 `/toolkit_merge_win` 을 호출하면 `diff` 와 동일하게 변경 미리보기만 표시한다. 원본 레포를 덮어쓰는 `push` 는 **반드시 명시적으로** `/toolkit_merge_win push` 로 호출해야 수행된다. `pull` 도 마찬가지.

## 예시

- `/toolkit_merge_win` → `diff`와 동일 (변경 미리보기만, 실제 파일 변경·`git commit`·`push` 없음).
- `/toolkit_merge_win pull` → 원본의 최신 버전으로 로컬의 기존 파일만 갱신 (신규 파일 추가 없음). 원본 dirty 면 경고 후 사용자 확인.
- `/toolkit_merge_win push` → 로컬 수정분을 **전체** 원본에 복사 후 `git commit + push`. **원본 dirty 면 기본 중단**.
- `/toolkit_merge_win push --allow-dirty-origin` → 원본 dirty 에도 불구하고 강제 진행(혼합 커밋이 생성될 수 있음).
- `/toolkit_merge_win push commands/set_subAgents.md` → **그 파일만** 원본에 복붙 + 단일 파일 commit + push.
- `/toolkit_merge_win push .claude/commands/set_subAgents.md` → 위와 동일 (프로젝트 루트 기준 경로도 허용).
- `/toolkit_merge_win push c:\vscode\hwpx-docx\.claude\commands\set_subAgents.md` → 위와 동일 (절대 경로도 허용).
- `/toolkit_merge_win push commands/set_subAgents.md skills/foo/SKILL.md` → 두 파일만 묶어서 단일 커밋으로 push.
- `/toolkit_merge_win diff` → 변경 미리보기만, 실제 변경은 수행하지 않음.
