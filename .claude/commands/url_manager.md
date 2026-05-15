---
description: "현재 프로젝트의 서버·포트를 references/url_list.md 에서 조회·표시하고, 등록되지 않은 프로젝트는 사용자에게 받아 추가."
argument-hint: "[port] | list | help"
allowed-tools: Bash, Read, Edit, Write, AskUserQuestion
---

# /url_manager — 프로젝트 서버·포트 레지스트리

인자: $ARGUMENTS

## 단일 출처

`$CLAUDE_PROJECT_DIR/.claude/references/url_list.md` 가 모든 프로젝트의 서버·포트 할당을 관리한다.
파일이 없거나 비어 있으면 아래 헤더로 새로 생성한다.

```markdown
# 프로젝트 서버·포트 할당

| 프로젝트 | 포트 | 서비스 | 비고 |
|---------|------|-------|------|
```

## 현재 프로젝트 식별

```bash
PROJECT="$(basename "$CLAUDE_PROJECT_DIR")"
LIST="$CLAUDE_PROJECT_DIR/.claude/references/url_list.md"
```

## 인자별 동작

### (없음) — 기본 동작: **현재 프로젝트의 서버·포트 출력**

1. `LIST` 가 없거나 표 헤더가 없으면 위 헤더로 신규 생성.
2. `LIST` 에서 `PROJECT` 행을 모두 검색하여 **아래 "출력 형식" 그대로 stdout 에 출력**한다. 이게 본 커맨드의 기본 임무다.
3. 등록된 행이 하나도 없으면 → 미등록 메시지를 출력하고 `AskUserQuestion` 으로 다음을 받아 등록한다:
   - `port` (필수, 숫자)
   - `service` (필수, 자유 텍스트 — 예: "Web UI", "API")
   - `note` (선택)
   그 다음 `LIST` 표 끝에 한 행을 `Edit` 으로 추가하고, 추가된 행을 다시 출력 형식으로 표시.

### `<숫자>` — 포트 명시 등록/갱신

- `PROJECT` 행이 없으면 → 그 포트로 신규 등록 (service 는 `AskUserQuestion` 으로 받음).
- 있으면 → 기존 행을 표시하고 사용자 확인 후 포트를 갱신.
- 다른 프로젝트가 이미 그 포트를 사용 중이면(`LIST` 텍스트 매칭) **충돌 경고**를 표시하고 진행 여부를 `AskUserQuestion` 으로 확인.

### `list` / `all`

- `LIST` 전체를 그대로 출력 (다른 프로젝트 포함).

### `help` / `-h` / `--help`

- 본 인자 표만 출력하고 종료. 등록/조회 동작 없음.

## 동작 규칙

- 표의 기존 형식·열 순서·열 폭은 건드리지 않는다 — **표 끝에 행 추가**만 수행.
- 포트 점유 여부는 텍스트 매칭으로만 검사한다 (`ss`/`lsof` 등 실행 LISTEN 확인은 하지 않음).
- 누락된 컬럼은 빈칸이 아니라 `—` 로 채운다.
- `LIST` 는 references 이므로 git 에 커밋되어 팀과 공유될 수 있도록 한다.

## 출력 형식

등록된 경우 — 헤더 한 줄 + 각 행을 `포트  서비스 (비고)` 형태로 정렬해 표시:

```
[url_manager] TaskPilot — 등록된 서버·포트 N개
  3000  Web UI (next dev)
  8000  API (FastAPI)
```

비고가 `—` 면 괄호는 생략한다.

미등록인 경우:

```
[url_manager] TaskPilot — 등록된 서버·포트가 없습니다.
```

등록 직후:

```
[url_manager] TaskPilot — 신규 등록:
  3000  Web UI (next dev)
```
