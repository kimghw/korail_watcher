---
description: "Codex/Gemini 서브에이전트 설정. 기본은 CLI 설치·인증, 'mcp' 인자 시 MCP 서버 등록, 'update' 인자 시 등록된 엔진에 대해 웹검색으로 최신 모델 후보를 조사하고 사용자 선택을 받아 재설정."
allowed-tools: Bash, Read, Edit, Write, WebSearch, WebFetch
---

# /set_subAgents 명령 — 서브에이전트(Codex/Gemini) 설정

인자: $ARGUMENTS

## 인자 요약

| 인자 | 동작 |
|------|------|
| `help` / `-h` / `--help` | 본 표(인자 목록과 각 동작 설명)만 출력하고 종료. 실제 설치/등록/갱신 수행 안 함. |
| (없음) | **기본**: Codex/Gemini CLI 설치 + 인증 (Node.js 20+ 사전 점검 포함). 아래 "CLI 설치 (기본 동작)" 섹션. |
| `mcp` | Claude Code MCP 서버로 Codex/Gemini 등록만 수행. **CLI 설치·인증은 이미 완료됐다고 가정**하며, 미설치 시 먼저 `/set_subAgents` 실행을 안내하고 중단. 아래 "MCP 등록 (옵션)" 섹션. |
| `update` | **이미 등록된** Codex/Gemini 서브에이전트에 대해 웹검색으로 최신 모델 후보를 조사하고, 사용자 선택을 받아 아래 "최신 모델 정보" 표를 갱신한 뒤 재설정. 미등록 엔진은 스킵. |

## 최신 모델 정보 (단일 출처)

이 섹션의 값이 **"최신 모델"의 정의**이다. 모델이 새로 출시되면 이 표만 수정하면 `/set_subAgents update`가 자동으로 새 값을 적용한다.

**참고:** `update` 인자로 호출하면 이 표는 **자동으로 갱신될 수 있다**. update 모드는 등록된 엔진에 대해 웹검색으로 최신 모델 후보를 조사 → 사용자 선택을 받아 → 본 표의 해당 행을 Edit으로 덮어쓴 뒤 이후 단계를 진행한다. 자세한 절차는 아래 "update 모드 → 단계 0" 참조.

| 엔진 | 최신 모델 | 프로필 이름 | 보조 설정 |
|------|-----------|------------|-----------|
| Codex | `gpt-5.5` | `xhigh` | `reasoning_effort = "xhigh"` |
| Gemini | `gemini-3.1-pro` | — | — |

> Codex 는 **프로필 기반** 으로 관리한다. `~/.codex/config.toml` 에 `[profiles.xhigh]` 블록으로 정의하고, CLI/MCP 모두 `--profile xhigh` 플래그로 호출한다. 글로벌 기본값(top-level `model` / `reasoning_effort`)은 사용하지 않는다 — 프로필이 단일 진실의 원천(single source of truth).
>
> 값을 갱신할 때는 공식 출처(OpenAI / Google 공지, `codex --help`, `gemini models list` 등)에서 확인 후 위 표를 업데이트하고 본 문서의 다른 예시들도 동일한 값으로 맞춘다. `update` 모드를 사용하면 이 확인/갱신 과정을 반자동으로 처리할 수 있다.

---

## CLI 설치 (기본 동작)

인자가 없을 때 수행하는 기본 시나리오. **MCP 등록은 하지 않는다.** MCP 연동이 필요하면 이후 `/set_subAgents mcp` 로 별도 호출.

### 0. 사전 준비 — Node.js 20+ 및 Claude Code CLI

1. Node.js 버전 점검:

   ```bash
   node -v
   ```

2. 없거나 20 미만이면 NodeSource 설치 스크립트 실행:

   ```bash
   curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash - && sudo apt-get install -y nodejs
   ```

3. Claude Code CLI 점검/설치 (없을 때만):

   ```bash
   command -v claude >/dev/null || sudo npm install -g @anthropic-ai/claude-code
   ```

### 1. Codex CLI (OpenAI)

#### 설치

```bash
sudo npm install -g @openai/codex
```

#### 인증

| 방식 | 명령어 |
|---|---|
| 구독 (ChatGPT Pro/Plus/Team) | `codex login --device-auth` → 브라우저에서 디바이스 코드 입력 |
| API 키 | `export OPENAI_API_KEY="sk-..."` |

#### 설정 파일 (`~/.codex/config.toml`) — 프로필 블록

Codex 는 **프로필 기반**으로 관리한다. 글로벌 기본값(top-level `model` / `reasoning_effort`)은 사용하지 않는다. 다음 블록을 추가/유지하면 `codex --profile xhigh ...` 또는 MCP `--profile xhigh` 호출 시 적용된다.

```toml
# (top-level 키들은 기존 값 유지: personality 등)

[profiles.xhigh]
model = "gpt-5.5"
reasoning_effort = "xhigh"      # low | medium | high | xhigh
```

| 키 (프로필 블록 내) | 설명 | 기본값 |
|---|---|---|
| `model` | 사용할 모델 | `o3` |
| `reasoning_effort` | 추론 수준 | `medium` |
| `sandbox_permissions` | 샌드박스 권한 | `[]` |
| `shell_environment_policy.inherit` | 셸 환경변수 상속 | - |

> 프로필 이름(`xhigh`)은 위 "최신 모델 정보" 표의 **프로필 이름** 컬럼과 반드시 일치시킨다.

### 2. Gemini CLI (Google)

#### 설치

```bash
sudo npm install -g @google/gemini-cli
```

#### 인증 (최초 1회)

```bash
gemini
```

### 3. 설치 검증

```bash
codex --version
gemini --version
```

두 바이너리가 정상 응답하면 기본 동작 완료. MCP 연동이 필요하면 `/set_subAgents mcp` 를 안내한다.

---

## MCP 등록 (옵션, `mcp` 인자)

사용자가 `/set_subAgents mcp` 로 명시 요청했을 때만 수행한다.

### 사전 조건

- `codex`, `gemini` 바이너리가 PATH 에 있어야 한다. 다음으로 확인:

  ```bash
  command -v codex && command -v gemini
  ```

- 둘 중 하나라도 없으면 **MCP 등록을 중단**하고 사용자에게 다음 안내 후 종료:

  > Codex/Gemini CLI 가 설치돼 있지 않습니다. 먼저 `/set_subAgents` 로 기본 설치를 마친 뒤 `/set_subAgents mcp` 를 다시 실행하세요.

### 1. Codex MCP 등록 — `--profile xhigh` 로 고정

`~/.codex/config.toml` 의 `[profiles.xhigh]` 블록을 사용하도록 MCP 서버를 등록한다:

```bash
claude mcp add -s user --transport stdio codex -- codex --profile xhigh mcp-server
```

> 프로필 이름은 위 "최신 모델 정보" 표의 **프로필 이름** 컬럼을 그대로 사용한다.
> `-c` 플래그(인라인 오버라이드)나 top-level config 키는 사용하지 않는다 — 프로필이 단일 진실의 원천.

#### 제공 도구

| 도구 | 설명 |
|---|---|
| `codex` | 새 코딩 세션 시작 (prompt 전달) |
| `codex-reply` | 기존 세션에 후속 지시 (threadId로 이어서 대화) |

#### 주요 파라미터

| 파라미터 | 설명 | 예시 |
|---|---|---|
| `model` | 모델 선택 | `gpt-5.2`, `gpt-5.2-codex` |
| `prompt` | 초기 프롬프트 (필수) | 자유 텍스트 |
| `approval-policy` | 명령어 실행 승인 정책 | `untrusted`, `on-failure`, `on-request`, `never` |
| `sandbox` | 샌드박스 모드 | `read-only`, `workspace-write`, `danger-full-access` |
| `cwd` | 작업 디렉토리 | 경로 |

### 2. Gemini MCP 등록

Gemini CLI 는 자체 MCP 서버 모드가 없으므로 서드파티 래퍼 사용:

```bash
npm install -g gemini-mcp-tool
claude mcp add -s user --transport stdio gemini -- gemini-mcp
```

> 패키지명은 `gemini-mcp-tool` 이지만 실행 바이너리는 `gemini-mcp` 이다.
> Codex 와 달리 등록 시 모델을 고정하지 않고, 도구 호출 시 `model` 파라미터로 선택한다.

#### 제공 도구

| 도구 | 설명 |
|---|---|
| `ask-gemini` | Gemini 에 질문/작업 요청 (`model` 파라미터로 모델 선택) |
| `brainstorm` | 브레인스토밍 (창의적 프레임워크 자동 적용) |
| `fetch-chunk` | 대용량 콘텐츠 청크 단위 조회 |

#### 주요 파라미터 (`ask-gemini`)

| 파라미터 | 설명 | 예시 |
|---|---|---|
| `prompt` | 분석 요청 (필수). `@file` 구문으로 파일 포함 가능 | `@main.py 이 코드 설명해줘` |
| `model` | 모델 선택 (기본: `gemini-2.5-pro`) | **`gemini-3.1-pro`**, `gemini-2.5-flash` |
| `sandbox` | 샌드박스 모드에서 코드 실행 | `true` / `false` |
| `changeMode` | 구조화된 편집 제안 반환 | `true` / `false` |

### 3. 검증

```bash
claude mcp list
```

Codex / Gemini 가 목록에 등록돼 있는지 확인.

---

## update 모드 (`update` 인자)

인자가 `update` 일 때 수행하는 동작. CLI 및/또는 MCP 등록이 이미 돼 있다고 가정하고, **이미 등록된 엔진**에 대해 웹검색으로 최신 모델 후보를 조사하고 사용자 선택을 받아 **"최신 모델 정보" 표를 갱신**한 뒤, 그 값으로 `~/.codex/config.toml` 의 프로필과 MCP 서버 등록을 동기화한다. 미등록 엔진은 스킵.

### 표에서 가져오는 값 (단일 출처)

- `MODEL` ← "최신 모델 정보" 표의 **최신 모델** (예: `gpt-5.5`)
- `PROFILE` ← 표의 **프로필 이름** (예: `xhigh`)
- `EFFORT` ← 표의 **보조 설정** 의 `reasoning_effort` 값 (예: `xhigh`)
- `GEMINI_MODEL_VAL` ← 표의 Gemini 최신 모델 (예: `gemini-3.1-pro`)

> 단계 0 에서 표가 갱신되면 위 변수들은 **갱신된 값**을 가리키게 된다. 이후 단계는 항상 "최신 모델 정보" 표의 현재 값을 다시 읽어 진행한다.

### 동작 순서

0. **최신 모델 후보 조사 (웹검색) — `update` 호출 시 가장 먼저 수행**

   0-1. **대상 엔진 결정**
   - `claude mcp list` 결과를 파싱해 등록된 MCP 서버 식별.
   - "최신 모델 정보" 표에 정의된 엔진(`codex`, `gemini`) 중 **현재 등록된 것만** 대상.
   - 등록되지 않은 엔진은 "미설치 — 스킵"으로 보고하고 다음 엔진으로 진행.
   - 사용자가 인자나 후속 메시지에서 "전체 강제", "codex만" 등 범위를 명시했으면 그에 따른다.

   0-2. **엔진별 웹검색 (`WebSearch`)**
   - 각 대상 엔진에 대해 다음 쿼리 패턴으로 검색:
     - **Codex**: `latest OpenAI Codex model <올해> release availability`, `gpt-5 codex model version site:openai.com`
     - **Gemini**: `latest Gemini model <올해> release`, `gemini latest model site:ai.google.dev OR site:cloud.google.com`
   - `<올해>` 는 현재 날짜에서 추출 (CLAUDE.md `currentDate` 또는 `date +%Y`).
   - 공식 출처(OpenAI/Google 블로그, OpenAI Platform 문서, Vertex AI 문서) 우선. 비공식 블로그·뉴스는 보조 검증용.
   - 검색 결과에서 **GA(generally available)** 상태의 최신 모델 ID를 1차 후보로, **preview/experimental** 은 2차 후보로 분리.
   - 필요 시 `WebFetch` 로 공식 release notes 페이지를 가져와 정확한 모델 ID/출시일/상태를 확정한다.

   0-3. **후보 비교 + 사용자 선택**
   - 각 엔진별로 다음 형식으로 요약을 출력:

     ```
     [Codex]
     - 현재 표 값:   gpt-5.5
     - 검색 최신값:  gpt-5.5 (GA, 2026-XX-XX)  → 변경 없음
     - 추가 후보:    gpt-5.6 (preview, 2026-XX-XX)
     출처: <URL>, <URL>
     ```

   - 검색 결과가 현재 표 값과 일치하면 "변경 없음"으로 표시하고 추가 확인 없이 다음 엔진으로 진행.
   - 다르면 `AskUserQuestion` 으로 선택지 제시:
     - `(a)` 현재 값 유지 (변경하지 않음)
     - `(b)` 검색된 GA 최신값으로 갱신
     - `(c)` 다른 후보(검색 결과의 preview/대안)로 갱신
     - `(d)` 직접 모델 ID 입력
   - 사용자가 선택할 때까지 다음 엔진/단계로 가지 않는다.

   0-4. **"최신 모델 정보" 표 자동 갱신**
   - 사용자가 (b)·(c)·(d) 를 선택해 새 모델 ID 가 결정됐으면 본 문서의 "최신 모델 정보" 표 해당 엔진 행의 **최신 모델** 컬럼을 `Edit` 으로 덮어쓴다.
   - **프로필 이름** / **보조 설정** 컬럼은 사용자가 명시적으로 변경을 요청한 경우에만 수정. 기본은 그대로 유지.
   - 동일 모델 ID 가 본 문서 내 다른 위치(예: "참고: 설정 파일 직접 편집" 의 JSON/TOML 예시, "Codex MCP 등록" 섹션의 예시 등) 에도 등장하면 동일 값으로 함께 갱신한다 (`replace_all` 또는 추가 Edit 호출).
   - 갱신 후 사용자에게 "표를 `<이전값>` → `<새값>` 으로 갱신했습니다" 를 보고하고 단계 1 로 진행.

   0-5. **비대화 모드 / 검색 실패 처리**
   - 사용자가 `--auto` 등 비대화 옵션을 명시했거나 환경 제약으로 질문이 불가능하면: 검색된 GA 최신값을 자동 선택 (preview 는 자동 채택 금지). 변경 내역은 출력 로그에 명시.
   - 웹검색이 실패하거나 신뢰할 만한 후보를 찾지 못한 경우: 표 갱신을 스킵하고 **현재 표 값**으로 단계 1 진행. 사용자에게 "웹검색 실패 — 표 값 유지" 안내.

1. **현재 상태 확인**
   - `claude mcp list` 로 등록된 MCP 서버 목록 확인.
   - `~/.codex/config.toml` 존재 여부, 그리고 `[profiles.<PROFILE>]` 블록의 현재 `model` / `reasoning_effort` 값 읽기.
   - top-level `model` / `reasoning_effort` 키가 남아 있으면 함께 기록 (3단계에서 정리).
   - `claude mcp get codex` 와 `claude mcp get gemini` 로 현재 args/env 확인 (있으면).

2. **Codex 프로필 블록 갱신** (`~/.codex/config.toml`)
   - 파일이 없으면 `mkdir -p ~/.codex && touch ~/.codex/config.toml` 후 생성.
   - `[profiles.<PROFILE>]` 블록이 없으면 **파일 끝**에 다음을 추가:

     ```toml
     [profiles.<PROFILE>]
     model = "<MODEL>"
     reasoning_effort = "<EFFORT>"
     ```

   - 블록이 이미 있으면 그 블록 **내부의** `model` / `reasoning_effort` 라인만 덮어쓰고, 같은 블록 내 다른 키와 다른 섹션(`[profiles.*]` 포함)은 그대로 보존.
   - 표의 **프로필 이름이 바뀐 경우** (예: `xhigh` → `xxhigh`): 기존 블록을 그대로 두고 새 블록을 추가한다. 옛 블록의 자동 삭제는 하지 않는다 (의도치 않은 사용자 설정 손실 방지). 사용자에게 "이전 프로필 `xhigh` 블록은 보존했습니다. 수동 정리가 필요하면 알려주세요" 안내.

3. **top-level Codex 키 정리**
   - `~/.codex/config.toml` 의 **top-level** `model` / `reasoning_effort` 키가 존재하면 사용자에게 확인 후 제거 (단일 진실의 원천을 프로필 블록으로 통일).
   - 사용자가 거부하면 그대로 두되, "프로필 호출 시 top-level 키와 충돌할 수 있음" 경고만 출력.

4. **Codex MCP 재등록** (`--profile` 고정)
   - `claude mcp get codex` 결과의 args 가 `["--profile", "<PROFILE>", "mcp-server"]` 와 정확히 일치하면 **재등록 불필요**.
   - 일치하지 않으면 (예: `["mcp-server"]` 만 있거나, 다른 프로필이거나, `-c` 인라인 오버라이드가 섞여 있는 경우) 재등록:

     ```bash
     claude mcp remove codex -s user
     claude mcp add -s user --transport stdio codex -- codex --profile <PROFILE> mcp-server
     ```

     기존 등록 스코프(`-s user` / `-s project`)는 그대로 유지. 다른 스코프로 옮기지 않는다.

5. **Gemini 갱신**
   - Gemini 는 등록 시점에 모델을 고정하지 않지만, **`GEMINI_MODEL` 환경변수**나 `ask-gemini` 의 기본 `model` 파라미터로 제어 가능.
   - `claude mcp get gemini` 의 env 에 `GEMINI_MODEL` 이 설정돼 있으면 `<GEMINI_MODEL_VAL>` 로 덮어쓰기 위해 재등록:

     ```bash
     claude mcp remove gemini -s user
     GEMINI_MODEL="<GEMINI_MODEL_VAL>" claude mcp add -s user --transport stdio gemini --env GEMINI_MODEL="<GEMINI_MODEL_VAL>" -- gemini-mcp
     ```

   - `GEMINI_MODEL` 이 설정돼 있지 않았다면 사용자에게 "등록 시 고정하시겠습니까? (기본은 호출 시 `model` 파라미터로 지정)" 확인 후 선택.

6. **검증 및 보고**
   - `claude mcp list` 로 재확인.
   - `cat ~/.codex/config.toml` 로 최종 프로필 블록 확인.
   - `codex --profile <PROFILE> --version` (또는 가능한 경량 호출)로 프로필이 인식되는지 확인.
   - 결과 리포트 형식: `엔진 | 항목 | 이전 값 → 새 값 | 재등록 여부`.

### 주의

- **재등록은 파괴적**이 아니라 메타데이터만 바꾸지만, `-s user` / `-s project` 스코프가 섞여 있으면 의도치 않은 스코프로 옮겨질 수 있다. 먼저 스코프를 명시 확인한 뒤 동일 스코프로 재등록할 것.
- config.toml 의 **다른 사용자 설정**(예: 다른 `[profiles.*]` 블록, `sandbox_permissions`, `shell_environment_policy`, `personality` 등)은 절대 건드리지 않는다. 해당 프로필 블록의 `model` / `reasoning_effort` 만 수정.
- 프로필 블록과 MCP args 가 모두 표와 일치하면 "변경 없음"으로 보고하고 아무 것도 재등록하지 않는다.

---

## 참고: 설정 파일 직접 편집

`~/.claude/settings.json` 을 직접 수정하는 방법 (Codex 는 `--profile xhigh` 로 프로필 고정):

```json
{
  "mcpServers": {
    "codex": {
      "command": "codex",
      "args": ["--profile", "xhigh", "mcp-server"]
    },
    "gemini": {
      "command": "gemini-mcp",
      "args": [],
      "env": {
        "GEMINI_MODEL": "gemini-3.1-pro"
      }
    }
  }
}
```

이때 `~/.codex/config.toml` 에는 다음 블록이 반드시 존재해야 한다:

```toml
[profiles.xhigh]
model = "gpt-5.5"
reasoning_effort = "xhigh"
```
