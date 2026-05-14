"""신규 OAuth 로그인 진입점.

브라우저를 열어 Azure AD 로그인 → 콜백 받아 access/refresh token 을 team_mcp/database/auth.db 에 저장.

실행:
    python team_mcp/login.py
    # 또는
    python -m team_mcp.login

필요한 환경변수 (team_mcp/.env 또는 프로젝트 루트 .env 어느 쪽이든 OK):
    AZURE_CLIENT_ID, AZURE_CLIENT_SECRET, AZURE_TENANT_ID, AZURE_REDIRECT_URI,
    AZURE_SCOPES, DB_PATH
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

# 패키지 초기화 (sys.path 등록 + .env 로드)
_PKG_DIR = Path(__file__).resolve().parent
if str(_PKG_DIR) not in sys.path:
    sys.path.insert(0, str(_PKG_DIR))

# 패키지 __init__ 가 처리하는 것과 동일하게 .env 로드
try:
    from dotenv import load_dotenv

    for env_path in (_PKG_DIR / ".env", _PKG_DIR.parent / ".env"):
        if env_path.is_file():
            load_dotenv(env_path, encoding="utf-8-sig", override=False)
except Exception:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
)
LOGGER = logging.getLogger("team_mcp.login")


async def run(timeout: int = 300, port: int = 5000) -> int:
    from session.auth_manager import AuthManager

    manager = AuthManager()
    try:
        existing = manager.list_users()
        if existing:
            print("\n[INFO] 이미 등록된 사용자:")
            for u in existing:
                status = "valid" if not u.get("token_expired", True) else "expired"
                refresh = "yes" if u.get("has_refresh_token") else "no"
                print(f"  - {u.get('email')}  (access={status}, refresh_token={refresh})")
            print()

        print(f"[INFO] 브라우저로 Azure AD 로그인 진행 (콜백 포트 {port}, 타임아웃 {timeout}s)")
        result = await manager.authenticate_with_browser(timeout=timeout, port=port)
        print(f"[RESULT] {result}")

        if result.get("status") == "success":
            print(f"\n[OK] 로그인 성공: {result.get('email')}")
            return 0
        elif result.get("status") == "timeout":
            print("\n[FAIL] 로그인 타임아웃")
            return 2
        else:
            print(f"\n[FAIL] {result.get('error')}")
            return 1
    finally:
        await manager.close()


def main() -> int:
    try:
        return asyncio.run(run())
    except KeyboardInterrupt:
        print("\n[CANCEL] 사용자 중단")
        return 130


if __name__ == "__main__":
    sys.exit(main())
