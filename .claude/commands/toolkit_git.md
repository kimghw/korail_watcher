---
description: "claude_toolkit 레포 git 자동화. 인자 없으면 stage+commit+push, 'pull'이면 pull"
allowed-tools: Bash, Read, Grep, Glob
---

# /toolkit_git 명령

인자: $ARGUMENTS

대상 디렉토리: `$CLAUDE_PROJECT_DIR` (현재 프로젝트 루트 = claude_toolkit 레포).
이 명령은 claude_toolkit 레포 안에서 실행되는 것을 전제로 하며, 레포 위치가 바뀌어도 별도 수정이 필요 없다.

## 동작 규칙

0. **인자가 `help` / `-h` / `--help`인 경우**: 본 명령이 받는 인자 목록과 각 인자의 동작 설명을 한눈에 출력하고 종료 (실제 git 작업 수행 안 함).

1. **인자가 비어 있거나 없는 경우** (기본 동작):
   - `git -C "$CLAUDE_PROJECT_DIR" add -A`로 모든 변경사항 스테이지
   - `git -C "$CLAUDE_PROJECT_DIR" diff --cached --stat`으로 스테이지된 내용 확인
   - 변경사항이 없으면 push만 실행하고 종료 (이미 커밋된 내용이 remote에 없을 수 있음)
   - 변경사항이 있으면 diff를 분석해 간결한 커밋 메시지 자동 생성 (한국어, 1줄)
   - `git -C "$CLAUDE_PROJECT_DIR" commit`으로 커밋
   - `git -C "$CLAUDE_PROJECT_DIR" push`로 현재 브랜치에 푸시 (upstream 없으면 `-u origin <branch>` 사용)

2. **인자가 `pull`인 경우**:
   - `git -C "$CLAUDE_PROJECT_DIR" pull`을 실행하고 결과를 보여줌

3. **그 외 인자**:
   - 인자를 그대로 `git -C "$CLAUDE_PROJECT_DIR"` 뒤에 전달하여 실행
