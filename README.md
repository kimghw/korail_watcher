# 🪑 빈자리 (binjari)

**기차(KTX)의 빈자리를 감시하다가 잡아주는 예매 워처.**
조회 → 예약 → (옵션) 결제/발권 → (옵션) 승차권 전달까지 자동 처리하고, 성공하면 Teams 알림으로 알려줍니다.

## 구성

| 모듈 | 역할 | 실행 |
|---|---|---|
| `ktx_watcher` | 코레일 KTX 감시·예매 워처 (경로 등 승객유형·승차권 전달 지원) | `python -m ktx_watcher.main` |
| `web_server` | 출발·도착·시간 조회 웹 UI (FastAPI) | `python -m uvicorn web_server:app --host 0.0.0.0 --port 8001` |
| `team_mcp` | Teams 알림 (Azure AD OAuth / Graph API) | `python -m team_mcp.login` (최초 인증) |

## 설치

- **자동**: Claude Code에서 `binjari_setup` 스킬 실행 — 의존성 설치, 실행 런처(`launch_binjari.bat`), 바탕화면 아이콘까지 셋업.
- **수동**: Python 3.12+ 에서

  ```bash
  uv sync            # 또는: pip install -e .
  playwright install chromium
  ```

## 설정

- `.env.ktx.example` 을 `.env.ktx` 로 복사해 `<...>` 자리에 실값(로그인·카드·Azure)을 채웁니다.
  **실값 파일은 커밋 금지** — `.gitignore` 가 `.env.*` 전체를 차단하며 양식(`*.example`)만 커밋됩니다.
- Teams 알림을 쓰려면 Azure AD OAuth 값을 채우고 `python -m team_mcp.login` 으로 최초 1회 인증합니다.
- Azure 설정만 별도 파일로 뽑을 때는 `azure_env_export` 스킬 사용 (`.env.ktx` → `.env.azure`).

---

## ⚠️ 주의 사항

- 본 도구는 학습/개인 편의 목적이며, **사이트 약관 및 관련 법령 준수**가 필요합니다.
- 사이트 구조 변경 시 일부 동작이 중단될 수 있습니다(로그/캡쳐로 원인 추적 가능).
