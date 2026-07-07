"""Microsoft Teams notifier (team_mcp 사용)."""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import Optional

from .base import Notifier

LOGGER = logging.getLogger(__name__)

# team_mcp 패키지가 srt_watcher 루트에 있으므로 sys.path 추가
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


class TeamsNotifier(Notifier):
    """Teams 채팅에 메시지를 전송한다.

    - chat_id 가 주어지면 해당 채팅으로 전송
    - chat_id 가 없고 recipient_name 이 주어지면 DB 에서 채팅 검색 후 전송
    - 둘 다 없으면 "나의 Notes" 채팅(self)으로 전송
    """

    def __init__(
        self,
        user_email: Optional[str] = None,
        chat_id: Optional[str] = None,
        recipient_name: Optional[str] = None,
        prefix: str = "[binjari SRT]",
    ) -> None:
        self.user_email = user_email
        self.chat_id = chat_id
        self.recipient_name = recipient_name
        self.prefix = prefix
        self._resolved_chat_id: Optional[str] = chat_id

    async def _send_async(self, message: str) -> None:
        from team_mcp import TeamsService

        service = TeamsService()
        try:
            ok = await service.initialize()
            if not ok:
                LOGGER.warning("TeamsService 초기화 실패")
                return

            chat_id = self._resolved_chat_id
            if not chat_id and self.recipient_name:
                found = await service.find_chat_by_name(
                    recipient_name=self.recipient_name,
                    user_email=self.user_email,
                )
                if found.get("success"):
                    chat_id = found.get("chat_id")
                    self._resolved_chat_id = chat_id
                else:
                    LOGGER.warning(
                        "Teams 채팅 검색 실패(recipient_name=%s): %s",
                        self.recipient_name,
                        found.get("message"),
                    )

            result = await service.send_chat_message(
                content=message,
                chat_id=chat_id,
                prefix=self.prefix,
                content_type="text",
                user_email=self.user_email,
            )
            if not result.get("success"):
                LOGGER.warning(
                    "Teams 메시지 전송 실패: %s",
                    result.get("error") or result,
                )
        finally:
            await service.close()

    def notify(self, message: str) -> None:
        try:
            asyncio.run(self._send_async(message))
        except RuntimeError as exc:
            # 이미 동작 중인 event loop 가 있을 때의 폴백
            LOGGER.warning("asyncio.run 실패, 새 루프로 재시도: %s", exc)
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(self._send_async(message))
            finally:
                loop.close()
        except Exception as exc:
            LOGGER.exception("Teams notify 예외: %s", exc)
