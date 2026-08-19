"""
team_mcp 패키지

워처들이 Microsoft Teams 알림을 보내기 위한 패키지.
session/ 와 mcp_teams/ 를 자체 포함한다.

이 패키지를 임포트하면 내부의 `session` 과 `mcp_teams` 가 최상위 모듈처럼
sys.path에 노출된다 (mcp_teams 코드가 `from session import ...` 형태로
임포트하기 때문).
"""

import os
import sys
from pathlib import Path

# team_mcp/ 디렉토리를 sys.path 에 추가 → `session`, `mcp_teams` 가 임포트 가능
_PKG_DIR = Path(__file__).resolve().parent
if str(_PKG_DIR) not in sys.path:
    sys.path.insert(0, str(_PKG_DIR))

# team_mcp/.env 가 있으면 우선 로드 (Azure 인증 정보)
try:
    from dotenv import load_dotenv

    _env_path = _PKG_DIR / ".env"
    if _env_path.is_file():
        load_dotenv(_env_path, encoding="utf-8-sig", override=False)
except Exception:
    pass

# 외부에서 사용할 핵심 객체 노출
from mcp_teams import TeamsService  # noqa: E402

__all__ = ["TeamsService"]
