---
name: korail_alarm
description: Korail/SRT 워처의 Teams 알림 인증 셋업. `korail` 스킬 7단계에서 알림 받기 선택 시 자격증명 미설정이면 자동 invoke. 또는 사용자가 "알림 설정", "Teams 인증", "korail 알림", "알림 인증" 등을 말하면 시작. 절차 — (1) Azure AD OAuth 4가지 (client_id, secret, tenant_id, 회사계정 이메일) 수집 (2) DB_PATH 의 auth.db 에 토큰 있는지 확인 (3) 없으면 `python -m team_mcp.login` 으로 OAuth flow 실행.
---

# korail_alarm — Teams 알림 인증 셋업

`korail` 스킬이 7단계에서 호출하거나, 사용자가 직접 알림 셋업을 요청하면 시작. 출력: 인증 성공/실패. 성공이면 호출자(korail 스킬) 가 워크플로우를 계속할 수 있고, 실패면 사용자에게 알림 없이 진행할지 묻는다.

`.env` 위치: `c:\Users\kimghw\KORAIL_WATCHER\.env`. 인증 DB: `.env` 의 `DB_PATH` 가 가리키는 경로 (기본 `team_mcp/database/auth.db`).

## 핵심 규칙
- AZURE_* 와 TEAMS_USER_EMAIL 만 수정. 그 외 키 (AZURE_REDIRECT_URI, AZURE_AUTHORITY, AZURE_SCOPES, DB_PATH) 는 절대 건드리지 않음 — 기본값을 그대로 쓴다.
- 토큰 / 시크릿 값은 stdout 으로 echo 금지. 마스킹해서만 보여줌.
- OAuth flow 는 브라우저 띄우는 외부 명령 — 사용자가 직접 로그인해야 함.

---

## 1단계 — Azure AD 자격증명 수집

`.env` 에서 다음 4가지 키 읽고, 비어 있는 것마다 사용자에게 묻기.

| 키 | 의미 | 사용자 안내 |
|---|---|---|
| `AZURE_CLIENT_ID` | Azure 앱 등록 클라이언트 ID | "Azure Portal → App registrations → 앱 → Application (client) ID" |
| `AZURE_CLIENT_SECRET` | 클라이언트 시크릿 (만료 주의) | "같은 앱 → Certificates & secrets → Client secrets 의 Value" |
| `AZURE_TENANT_ID` | 테넌트 ID | "같은 앱 → Overview → Directory (tenant) ID" |
| `TEAMS_USER_EMAIL` | **회사 계정 이메일** — 알림 받는 사람 | "예: `name@krs.co.kr`. 이 사람으로 OAuth 로그인하게 됨" |

수집 방식:
- 키마다 따로 한 번씩 묻기 (한 번에 다 묻지 않기). 한 줄 입력으로 받기.
- 이미 채워져 있는 키는 마스킹해서 보여주고 `AskUserQuestion`:
  - 질문: "현재 저장된 AZURE_CLIENT_ID (8801**...**6b) 그대로 사용?"
  - 옵션: `그대로 사용` / `새 값 입력`

> `AZURE_CLIENT_SECRET` 은 마스킹 시 앞 4자만 보여줌. 다른 값은 앞 4 + 뒤 4 형식.

---

## 2단계 — auth.db 토큰 확인

`.env` 의 `DB_PATH` 가 가리키는 sqlite 파일에서 `TEAMS_USER_EMAIL` 의 access_token 이 있는지 확인.

확인용 한 줄 (Bash):
```bash
python -c "
import os, sqlite3
from dotenv import load_dotenv
load_dotenv()
db = os.environ['DB_PATH']; email = os.environ['TEAMS_USER_EMAIL']
if not os.path.isfile(db):
    print('NO_DB'); raise SystemExit
con = sqlite3.connect(db)
tables = [r[0] for r in con.execute(\"SELECT name FROM sqlite_master WHERE type='table'\")]
print('tables:', tables)
# 토큰 테이블 이름은 환경마다 다를 수 있음 — 가능한 후보 시도
for t in ('tokens', 'auth', 'user_tokens'):
    if t in tables:
        try:
            row = con.execute(f'SELECT * FROM {t} WHERE user_email=? OR email=? LIMIT 1', (email, email)).fetchone()
            print(t, '→', 'HAS_TOKEN' if row else 'NO_TOKEN_FOR_USER')
            break
        except sqlite3.OperationalError as e:
            print(t, 'schema mismatch:', e)
"
```

분기:
- `NO_DB` 또는 `NO_TOKEN_FOR_USER` → **3단계로**.
- 토큰 있음 → 호출자에게 OK 반환하고 종료.

스키마가 예상과 다르면 (`schema mismatch`) 일단 3단계로 진행 — `python -m team_mcp.login` 이 알아서 처리.

---

## 3단계 — OAuth 로그인 실행

```bash
python -m team_mcp.login
```

- 명령이 브라우저를 띄움 → Microsoft 로그인 페이지.
- 사용자가 `TEAMS_USER_EMAIL` 계정으로 로그인.
- Azure 가 `AZURE_REDIRECT_URI` (기본 `http://localhost:5000/callback`) 로 코드 콜백.
- `team_mcp.login` 이 access/refresh 토큰을 `DB_PATH` 의 auth.db 에 저장.

명령 실행 전 사용자에게 한 줄 안내:
> "잠시 후 브라우저가 열립니다. 회사 계정 `TEAMS_USER_EMAIL` 로 로그인해주세요. 콜백 받으면 자동으로 토큰이 저장됩니다."

실행은 background 없이 (foreground) — 사용자가 로그인 완료할 때까지 대기. 타임아웃은 명령 자체가 관리.

완료 후 2단계 확인 다시 한 번 → 통과하면 호출자에게 OK 반환.

---

## 결과 보고

호출자(보통 `korail` 스킬 7단계) 에게 한 줄로 반환:

- 성공: `[korail_alarm] 인증 완료 (user=name@krs.co.kr)`
- 실패: `[korail_alarm] 인증 실패: <사유>` — 호출자가 "알림 없이 진행?" 사용자에게 묻도록 함.

실패 사유 분류:
- Azure 자격증명 미입력 (사용자 취소)
- `python -m team_mcp.login` 실행 오류 (모듈 import 실패 등)
- OAuth flow 사용자 취소 (브라우저 닫음, 거부)
- 콜백 타임아웃

---

## 직접 호출 시 (사용자가 "알림 인증" 같은 발언으로 시작)

호출자 없이 단독으로 진입했으면 — 위 1~3단계 그대로 진행 + 마지막에 한 줄:
> "Teams 알림 인증이 완료되었습니다. `korail` 스킬 7단계에서 '알림 받기' 선택 시 자동 활성화됩니다."

---

## 하지 말 것

- 토큰 값 / `AZURE_CLIENT_SECRET` 전체를 stdout 으로 출력 금지.
- `DB_PATH` 의 auth.db 를 직접 INSERT/UPDATE 금지 — 인증은 무조건 `team_mcp.login` 통해서.
- `AZURE_REDIRECT_URI`, `AZURE_AUTHORITY`, `AZURE_SCOPES`, `DB_PATH` 는 사용자 동의 없이 수정 금지.
- 사용자가 입력한 secret 을 echo 하거나 git 에 푸시 금지 (`.env` 는 gitignore 되어 있어 OK).
