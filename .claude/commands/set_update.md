---
description: "claude_toolkit 원본을 git pull 하고, commands/skills/agents/references 파일을 현행 Claude Code 스펙(2026-04 기준)에 맞는지 검사하여 최신 버전으로 갱신. 인자로 범위 지정 (commands, skill|skills, agents, references, all, 없음=전체)."
argument-hint: "[commands|skill|skills|agents|references|all] ..."
allowed-tools: Bash, Read, Glob, Grep, Agent
---

# /set_update 명령

인자: $ARGUMENTS

## 개요

"최신 버전"은 두 축이다. 둘 다 검사/보고한다.

1. **콘텐츠 최신화** — `$TOOLKIT`(원본 `claude_toolkit` 레포)을 `git pull`. 심볼릭 링크된 로컬 `.claude/`는 원본이 바뀌면 즉시 최신이 된다.
2. **스펙 최신화** — 파일들이 **Claude Code v2.1.111(2026-04) 현행 스펙**을 따르는지 검사. 구버전 frontmatter 키, 누락된 권장 필드, 비표준 구조를 진단 후 보고.

이 명령은 **자동 수정하지 않는다**. pull로 가져온 변경과 스펙 진단 리포트만 제공하고, 개선 항목은 사용자가 승인할 때만 수정 제안.

## 경로 정의

- `$TOOLKIT`: 원본 `claude_toolkit` 레포 경로. Windows 네이티브와 Ubuntu/WSL 환경을 모두 지원하기 위해 다음 우선순위로 결정한다. (1) env `$CLAUDE_TOOLKIT_ROOT`가 지정되어 있고 실존하면 그 값, (2) `$(dirname "$CLAUDE_PROJECT_DIR")/claude_toolkit`(소비자 프로젝트와 형제 위치)이 존재하면 그 값, (3) `$HOME/claude_toolkit`이 존재하면 그 값 (Ubuntu/WSL 일반 설치 위치), (4) Windows의 경우 `$USERPROFILE/claude_toolkit`도 시도, (5) 모두 실패하면 에러로 중단하고 사용자에게 경로를 질문.
- `$TOOLKIT/.claude/`: 원본 콘텐츠 디렉토리. `agents/`, `commands/`, `skills/`, `references/`가 모두 이 하위에 있음. 내부 경로 표기는 **소비자 `.claude/` 기준 상대 경로**(예: `commands/git.md`)를 쓰되, toolkit 측 실제 파일은 `$TOOLKIT/.claude/<범위>`에 있다.
- `$CLAUDE_PROJECT_DIR`: 본 명령이 실행되는 소비자 프로젝트 루트.
- `$SPEC_REF`: `$TOOLKIT/.claude/references/anthropic-*.md` (스펙 판정 근거 문서들).

## 인자

| 인자 | 범위 |
|------|------|
| `help` / `-h` / `--help` | 본 표(인자 목록과 각 범위 설명)만 출력하고 종료. pull/검사 수행 안 함. |
| `commands` | `commands/` 만 |
| `skill` 또는 `skills` | `skills/` 만 |
| `agents` | `agents/` 만 |
| `references` | `references/` 만 |
| `all` | 위 4개 전부 |
| (없음) | 전부를 대상으로 하되 pull 전후에 사용자 확인 |

여러 인자 허용: `commands skills`처럼 공백으로 나열하면 해당 범위만 diff 보고.

## 동작 순서

1. **원본 경로 및 상태 점검**
   - `$TOOLKIT` 결정: 다음 순서로 폴백한다. (a) `$CLAUDE_TOOLKIT_ROOT`가 설정되어 있고 그 경로가 실존하면 사용, (b) `$(dirname "$CLAUDE_PROJECT_DIR")/claude_toolkit`이 존재하면 사용, (c) `$HOME/claude_toolkit`이 존재하면 사용, (d) Windows 네이티브에서 `$USERPROFILE/claude_toolkit`이 존재하면 사용, (e) 모두 실패하면 에러로 중단하고 사용자에게 경로를 질문.
   - `git -C "$TOOLKIT" status --porcelain`로 작업 디렉토리가 깨끗한지 확인.
     - 변경이 있으면 사용자에게 보여주고 **pull을 계속할지 확인** (충돌 위험 경고).
   - `git -C "$TOOLKIT" rev-parse --abbrev-ref HEAD`로 현재 브랜치 확인.

2. **pull 전 스냅샷**
   - `OLD_HEAD=$(git -C "$TOOLKIT" rev-parse HEAD)` 기록.
   - `git -C "$TOOLKIT" fetch --quiet`로 원격 최신화 후 `git -C "$TOOLKIT" rev-list OLD_HEAD..@{u} --count`로 **가져올 커밋 수** 미리 보고.
   - 가져올 커밋이 0이면 "이미 최신" 보고 후 종료.

3. **git pull (fast-forward 우선)**
   - `git -C "$TOOLKIT" pull --ff-only`를 실행.
   - fast-forward 불가(로컬에 커밋 있음, 원격과 분기) 시 **중단**하고 사용자에게 상황 보고. 이 명령은 rebase/merge를 자동으로 하지 않는다.

4. **변경 분석 (인자 범위로 필터)**
   - `git -C "$TOOLKIT" diff --stat $OLD_HEAD HEAD -- .claude/<범위>`로 변경 파일 목록. (toolkit 레포 내부 실제 경로는 `.claude/` 프리픽스가 붙는다.)
   - `git -C "$TOOLKIT" log --oneline $OLD_HEAD..HEAD -- .claude/<범위>`로 커밋 요약.
   - 추가/수정/삭제를 구분하여 표시. 사용자에게 보여줄 때는 `.claude/` 프리픽스를 벗긴 상대 경로(예: `commands/foo.md`)로 정리해도 무방.

5. **로컬 링크 상태 점검**
   - 각 범위 디렉토리에 대해 `$CLAUDE_PROJECT_DIR/.claude/<범위>` 상태 확인:
     - **심볼릭이고 `$TOOLKIT/.claude/<범위>`를 가리킴**: "즉시 반영됨"으로 보고.
     - **실디렉토리/실파일**: "링크되지 않은 로컬 복사본 — `/toolkit_link <범위>`로 전환하면 이후 자동 갱신됨" 안내.
     - **없음**: "로컬에 아직 링크 안 됨 — `/toolkit_link <범위>`로 생성 가능" 안내.
     - **심볼릭이지만 다른 곳을 가리킴**: 외부 링크로 간주, 건드리지 않고 경고만.
   - 범위 내 **개별 항목**(예: `skills/pdf2md`)이 디렉토리 링크 밑이 아니라 별도 링크일 수 있으므로, `find "$CLAUDE_PROJECT_DIR/.claude/<범위>" -maxdepth 2 -type l`로 하위 심볼릭도 함께 점검.

6. **스펙 준수 검사 (v2.1.111 기준) — 다중 서브에이전트 병렬 디스패치**
   - 범위 내 모든 `*.md` / `SKILL.md`를 열거한 뒤 **배치로 나눠 `Explore` 서브에이전트들에 병렬로 위임**한다. 메인 에이전트는 오케스트레이터 역할만 수행하고 실제 읽기/진단은 서브에이전트가 담당한다(메인 컨텍스트 보호).
   - 판정 근거는 `$TOOLKIT/.claude/references/anthropic-frontmatter.md`, `anthropic-skill-anatomy.md`, `anthropic-progressive-disclosure.md`를 참조. 각 서브에이전트에 이 경로들을 프롬프트에 명시 전달.

### 6-0. 병렬 디스패치 규칙

1. **대상 열거**: 범위별로 대상 파일 전체 경로 수집.
   - `commands` → `$TOOLKIT/.claude/commands/*.md`
   - `skills` → `$TOOLKIT/.claude/skills/*/SKILL.md` (필요 시 하위 `references/*.md` 포함 여부는 사용자 확인)
   - `agents` → `$TOOLKIT/.claude/agents/*.md`
   - `references` → `$TOOLKIT/.claude/references/*.md`
2. **배치 분할**:
   - 대상 파일이 **≤ 3개**면 에이전트 호출 없이 메인이 직접 진단 (오버헤드 회피).
   - **4~12개**면 파일당 1개 에이전트 (최대 동시 12개).
   - **> 12개**면 `ceil(N/4)` 개 배치로 나눠 배치당 ~4개 파일씩 묶어 디스패치.
3. **동시 호출**: 모든 `Agent` 호출은 **한 번의 응답에 병렬 블록**으로 발행한다(순차 호출 금지). `subagent_type` 은 기본 `Explore`, 대상이 너무 많거나 판정 근거 문서까지 넓게 읽어야 하면 `general-purpose`.
4. **에이전트 프롬프트 템플릿** (각 에이전트에 동일 형식으로 전달):

   ```text
   역할: Claude Code v2.1.111 스펙 감리자.
   판정 근거 문서 (먼저 읽을 것):
     - $TOOLKIT/.claude/references/anthropic-frontmatter.md
     - $TOOLKIT/.claude/references/anthropic-skill-anatomy.md
     - $TOOLKIT/.claude/references/anthropic-progressive-disclosure.md
   검사 체크리스트: 아래 6-1 / 6-2 / 6-3 표를 그대로 적용.
   대상 파일 (배치):
     - <path1>
     - <path2>
     ...
   요구 출력 (JSON, 300 단어 이하):
     [
       {
         "file": "<path>",
         "verdict": "pass|warn|fail",
         "issues": [
           {"rule": "<체크표 #번호>", "severity": "info|warn|error", "message": "<한국어 1줄>"}
         ]
       }
     ]
   수정은 하지 말 것. 진단만.
   ```

5. **결과 취합**: 모든 에이전트 결과를 받아 하나의 테이블로 병합. 각 파일은 최고 심각도(`fail` > `warn` > `pass`)로 분류. 에이전트 응답이 JSON 파싱에 실패하면 그 배치만 메인이 직접 재진단.

### 6-1. 공통 frontmatter 체크

| # | 검사 항목 | 권장 | 구버전 신호 |
|---|-----------|------|-------------|
| 1 | `description` 필드 존재 | ✅ 필수 (자동 트리거 근거) | 없음 또는 100자 미만 |
| 2 | `description` 길이 ≤ 1536자 (description + when_to_use 합산) | ✅ | 초과 → `when_to_use`로 분리 권장 |
| 3 | `TRIGGER` / `DO NOT TRIGGER` 패턴 명시 | ✅ (v2.1.105+) | 없음 |
| 4 | 비공식 frontmatter 키 | 없어야 함 | `enabled:`, `invoke_mode:`, `version:`, `metadata:` 등 발견 시 경고 |
| 5 | `argument-hint` (인자 받는 커맨드) | ✅ (v2.1.X+) | 없음 |
| 6 | `allowed-tools` 패턴 세분화 (예: `Bash(git *)`) | ✅ 권장 | 도구명만 (`Bash`) |

### 6-2. commands 전용 체크

| # | 검사 항목 | 비고 |
|---|-----------|------|
| 7 | 본문에 `$ARGUMENTS` 또는 `$0`/`$1` 등 인덱스 접근 사용 | v2.1.X 이후 `$N` 단축형 지원 |
| 8 | 부수 효과 있는 커맨드는 `disable-model-invocation: true` 고려 | Claude 자동 호출 방지 |

### 6-3. skills(SKILL.md) 전용 체크

| # | 검사 항목 | 권장 | 구버전 신호 |
|---|-----------|------|-------------|
| 9 | `name` 필드가 폴더명과 일치, 소문자·숫자·하이폰만, 64자 이하 | ✅ | 대문자/공백/특수문자 |
| 10 | 본문에 "When to Use" 섹션 없음 (frontmatter `description`에 있어야) | ✅ | 본문에 있으면 트리거 효과 없음 → 이동 권장 |
| 11 | SKILL.md 본문 ≤ 500줄 | ✅ | 초과 → `references/`로 분리 권장 |
| 12 | 지원 파일 구조: `references/`, `scripts/`, `assets/` 분리 | ✅ | 모두 SKILL.md에 몰려있으면 경고 |
| 13 | `README.md`, `CHANGELOG.md`, `INSTALLATION_GUIDE.md` 등 메타 문서 없음 | ✅ | 있으면 혼란 유발, 제거 권장 |
| 14 | `paths` 필드 (특정 파일 타입 전용 스킬) | 선택 | 없어도 무방 |
| 15 | `context: fork` + `agent` 조합 (서브에이전트 필요 시) | 선택 | 필요한데 없으면 안내 |

### 6-4. 진단 실행 방법

- frontmatter 파싱: 파일 상단 `---` 블록을 `sed -n '/^---$/,/^---$/p'` 또는 `awk`로 추출.
- 비공식 키 탐지: `grep -E '^(enabled|invoke_mode|version|metadata):' <file>` 매치.
- 본문 줄 수: `awk '/^---$/{c++; next} c>=2' <file> | wc -l`.
- "When to Use" 섹션 탐지: `grep -nE '^#+\s*when\s+to\s+use' -i <file>`.

7. **사후 보고**
   - 형식:
     ```
     [콘텐츠]
     $TOOLKIT: <OLD_HEAD[:7]> → <NEW_HEAD[:7]> (<N개 커밋>)
     <범위> 변경: +<추가> ~<수정> -<삭제>
       + commands/foo.md
       ~ skills/bar/SKILL.md

     [로컬 링크]
     commands/: 심볼릭 ✓ (즉시 반영)
     skills/:   실디렉토리 ⚠ (재링크 권장: /toolkit_link skills)

     [스펙 준수 — v2.1.111 기준]
     ✓ 통과: 5개 파일
     ⚠ 권장 개선: 2개 파일
       - commands/git.md — argument-hint 누락
       - skills/foo/SKILL.md — 본문에 "When to Use" 섹션 발견 (frontmatter로 이동 권장)
     ✗ 구버전 신호: 1개 파일
       - skills/bar/SKILL.md — 비공식 frontmatter 키 `version:` 발견
     ```
   - 각 개선 항목에 대해 "수정 제안을 보여드릴까요?" 프롬프트로 마무리 (자동 수정 금지).

## 동작 규칙

- **커밋/푸시 안 함**: 이 명령은 오직 pull 만 한다. 원본에 변경을 쓰려면 `/toolkit_git`을 사용.
- **자동 재링크 안 함**: 실파일로 남은 로컬 복사본을 자동으로 심볼릭으로 바꾸지 않는다. 사용자가 직접 `/toolkit_link`을 호출해야 함(데이터 손실 방지).
- **자동 스펙 수정 안 함**: 진단 리포트만 제공. 개선 수정은 사용자가 항목별로 승인하고, 수정 대상 파일이 심볼릭이면 **원본(`$TOOLKIT/.claude/`)**을 편집한다(링크 경유하지 말 것).
- **스킬 인자 동의어**: `skill`과 `skills` 모두 `skills/` 디렉토리를 의미하도록 처리.
- **범위 외 변경도 표시**: 인자로 `commands`만 줬더라도 pull로 가져온 전체 커밋 개수와 요약은 보고(투명성 확보). 단, 파일 목록 diff와 스펙 검사는 인자 범위로 한정.
- **스펙 기준 출처**: 판정은 `$SPEC_REF` 문서들을 따른다. 이 문서들이 최신이 아니라고 판단되면 먼저 `$SPEC_REF` 갱신을 제안.
- **검사는 병렬 에이전트 위임**: 스펙 준수 검사는 파일 수에 따라 `Explore` 서브에이전트들에 병렬 디스패치(6-0 참조). 메인은 오케스트레이션·집계만 담당, 실제 파일 읽기와 체크리스트 판정은 에이전트 단에서 수행하여 메인 컨텍스트를 보호한다. 3개 이하일 때만 메인 직접 진단.

## 예시

- `/set_update commands` → commands/ 대상 pull + diff + 스펙 검사
- `/set_update skill` → skills/ 대상 (동의어: `skills`)
- `/set_update skills/pdf2md` → 특정 스킬 하위만
- `/set_update all` → 4개 디렉토리 전체
- `/set_update commands skills` → 두 범위 동시
- `/set_update` (인자 없음) → 전체 pull 전 사용자 확인 후 진행
