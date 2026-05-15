# Claude Code 전체 권한 허용 설정

> **인자**: 본 문서는 참고용으로 별도 인자를 받지 않는다. `help` / `-h` / `--help`가 주어지면 "인자를 받지 않는 참고 문서"임을 한 줄로 알리고 본 문서 내용을 그대로 표시한다.

## 방법 1: CLI 실행 시 옵션

```bash
claude --dangerously-skip-permissions
```

이 플래그를 사용하면 모든 도구 호출에 대해 사용자 승인 없이 자동으로 허용됩니다.

---

## 방법 2: settings.json 에서 허용 규칙 설정

`~/.claude/settings.json` (글로벌) 또는 프로젝트의 `.claude/settings.json` (프로젝트별)에 아래 내용을 추가합니다.

```json
{
  "permissions": {
    "allow": [
      "Bash(*)",
      "Edit(*)",
      "Write(*)",
      "Read(*)",
      "Glob(*)",
      "Grep(*)",
      "Agent(*)",
      "WebFetch(*)",
      "WebSearch(*)",
      "NotebookEdit(*)",
      "TodoWrite(*)",
      "mcp__*"
    ],
    "deny": []
  }
}
```

### 각 항목 설명

| 규칙 | 의미 |
|------|------|
| `Bash(*)` | 모든 Bash 명령 실행 허용 (npm, git, docker 등 전부 포함) |
| `Edit(*)` | 모든 파일 편집 허용 |
| `Write(*)` | 모든 파일 생성/덮어쓰기 허용 |
| `Read(*)` | 모든 파일 읽기 허용 |
| `Glob(*)` | 파일 검색 허용 |
| `Grep(*)` | 내용 검색 허용 |
| `Agent(*)` | 서브에이전트 실행 허용 |
| `WebFetch(*)` | 웹 URL 접근 허용 |
| `WebSearch(*)` | 웹 검색 허용 |
| `NotebookEdit(*)` | Jupyter 노트북 편집 허용 |
| `TodoWrite(*)` | 할 일 목록 작성 허용 |
| `mcp__*` | 모든 MCP 서버 도구 허용 |

---

## 방법 3: 특정 명령어만 허용하고 싶을 때

Bash 명령어를 세분화해서 허용할 수도 있습니다.

```json
{
  "permissions": {
    "allow": [
      "Bash(npm *)",
      "Bash(npx *)",
      "Bash(node *)",
      "Bash(git *)",
      "Bash(docker *)",
      "Bash(python *)",
      "Bash(pip *)",
      "Bash(cargo *)",
      "Bash(go *)",
      "Bash(make *)",
      "Bash(ls *)",
      "Bash(mkdir *)",
      "Bash(rm *)",
      "Bash(cp *)",
      "Bash(mv *)",
      "Bash(chmod *)",
      "Bash(curl *)",
      "Bash(wget *)",
      "Edit(*)",
      "Write(*)",
      "Read(*)",
      "Glob(*)",
      "Grep(*)",
      "Agent(*)",
      "WebFetch(*)",
      "WebSearch(*)",
      "NotebookEdit(*)",
      "TodoWrite(*)",
      "mcp__*"
    ],
    "deny": []
  }
}
```

---

## 주의사항

- `--dangerously-skip-permissions` 는 이름 그대로 **위험할 수 있습니다**. 신뢰할 수 있는 환경에서만 사용하세요.
- `Bash(*)` 는 `rm -rf /` 같은 파괴적 명령도 허용하므로 주의가 필요합니다.
- 프로덕션 환경이나 공유 시스템에서는 방법 3처럼 필요한 명령만 허용하는 것을 권장합니다.
