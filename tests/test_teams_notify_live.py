"""Teams 알림 실전 테스트 (live).

기본 사용자의 "나의 Notes" 채팅으로 메시지를 실제로 보낸다.
team_mcp/database/auth.db 의 refresh_token 을 사용해 access_token 을 갱신한 뒤
Graph API 호출.

실행:
    python tests/test_teams_notify_live.py
또는
    pytest tests/test_teams_notify_live.py -s
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

# 프로젝트 루트 추가
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env", override=True, encoding="utf-8-sig")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s | %(message)s")

import team_mcp  # noqa: E402,F401 (team_mcp/__init__.py 가 sys.path 등록)
from team_mcp import TeamsService  # noqa: E402

TARGET_EMAIL = os.getenv("TEAMS_USER_EMAIL", "kimghw@krs.co.kr")


async def send_to_self() -> int:
    service = TeamsService()
    ok = await service.initialize()
    print(f"[INIT] initialized={ok}")
    if not ok:
        return 1

    try:
        # chat_id 비우면 "48:notes" (나의 Notes) 로 자동 전송 → 자기 자신에게 도착
        result = await service.send_chat_message(
            content="✅ team_mcp 알림 테스트 (tests/) — srt_watcher → kimghw@krs.co.kr",
            chat_id=None,
            prefix="[SRT WATCHER]",
            content_type="text",
            user_email=TARGET_EMAIL,
        )
        print("[SEND RESULT]")
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        return 0 if result.get("success") else 2
    finally:
        await service.close()


def test_send_to_self_live():
    """pytest 진입점 — 실제 전송하는 라이브 테스트."""
    rc = asyncio.run(send_to_self())
    assert rc == 0, f"send failed (rc={rc})"


if __name__ == "__main__":
    sys.exit(asyncio.run(send_to_self()))
