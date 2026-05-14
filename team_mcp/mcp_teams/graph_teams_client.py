"""
Teams Graph API Client
Microsoft Graph API를 사용한 Teams 작업 처리
session 모듈을 통한 인증 관리
"""

import logging
from typing import Optional, List, Dict, Any
import aiohttp

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from session import AuthManager
from .teams_types import (
    ChatInfo,
    MessageInfo,
    TeamInfo,
    ChannelInfo,
    ChatType,
    MessageImportance,
)

logger = logging.getLogger(__name__)


class GraphTeamsClient:
    """Teams Graph API 클라이언트"""

    GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
    NOTES_CHAT_ID = "48:notes"  # 나의 Notes 특수 채팅

    def __init__(self, auth_manager: Optional[AuthManager] = None):
        """
        클라이언트 초기화

        Args:
            auth_manager: 인증 매니저 인스턴스 (없으면 새로 생성)
        """
        self.auth_manager = auth_manager or AuthManager()
        self._session: Optional[aiohttp.ClientSession] = None
        self._initialized = False

    async def initialize(self) -> bool:
        """클라이언트 초기화"""
        if self._initialized:
            return True

        self._session = aiohttp.ClientSession()
        self._initialized = True
        logger.info("GraphTeamsClient initialized")
        return True

    async def close(self):
        """리소스 정리"""
        if self._session:
            await self._session.close()
            self._session = None
        self._initialized = False

    async def _get_access_token(self, user_email: str) -> Optional[str]:
        """
        사용자 이메일로 유효한 액세스 토큰 조회 (자동 갱신 포함)

        Args:
            user_email: 사용자 이메일

        Returns:
            유효한 액세스 토큰 또는 None
        """
        try:
            token = await self.auth_manager.validate_and_refresh_token(user_email)
            return token
        except Exception as e:
            logger.error(f"토큰 조회 실패: {str(e)}")
            return None

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        user_email: str,
        json_data: Optional[Dict[str, Any]] = None,
        timeout: int = 30,
    ) -> Dict[str, Any]:
        """
        Graph API 요청 수행

        Args:
            method: HTTP 메서드 (GET, POST, PATCH, DELETE)
            endpoint: API 엔드포인트
            user_email: 사용자 이메일
            json_data: JSON 데이터
            timeout: 타임아웃 (초)

        Returns:
            API 응답
        """
        if not self._initialized:
            await self.initialize()

        access_token = await self._get_access_token(user_email)
        if not access_token:
            return {"success": False, "error": "액세스 토큰이 없습니다. 로그인이 필요합니다."}

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

        url = f"{self.GRAPH_BASE_URL}{endpoint}"

        try:
            async with self._session.request(
                method,
                url,
                headers=headers,
                json=json_data if json_data else None,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as response:
                if response.status in (200, 201, 204):
                    if response.status == 204:
                        return {"success": True}
                    result = await response.json()
                    return {"success": True, "data": result}
                else:
                    error_text = await response.text()
                    logger.error(f"API 요청 실패: {response.status} - {error_text}")
                    return {
                        "success": False,
                        "error": f"API 요청 실패: {response.status}",
                        "details": error_text,
                    }
        except Exception as e:
            logger.error(f"API 요청 오류: {str(e)}")
            return {"success": False, "error": str(e)}

    # ========================================================================
    # 채팅 관련 메서드
    # ========================================================================

    async def list_chats(
        self,
        user_email: str,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """
        사용자의 채팅 목록 조회

        Args:
            user_email: 사용자 이메일
            limit: 조회할 채팅 개수

        Returns:
            채팅 목록
        """
        endpoint = f"/me/chats?$top={limit}"
        result = await self._make_request("GET", endpoint, user_email)

        if result.get("success"):
            chats_data = result.get("data", {}).get("value", [])
            chats = [ChatInfo.from_dict(c) for c in chats_data]
            return {
                "success": True,
                "chats": [c.__dict__ for c in chats],
                "count": len(chats),
            }

        return result

    async def get_chat(
        self,
        user_email: str,
        chat_id: str,
    ) -> Dict[str, Any]:
        """
        특정 채팅 정보 조회

        Args:
            user_email: 사용자 이메일
            chat_id: 채팅 ID

        Returns:
            채팅 정보
        """
        endpoint = f"/me/chats/{chat_id}"
        result = await self._make_request("GET", endpoint, user_email)

        if result.get("success"):
            chat = ChatInfo.from_dict(result.get("data", {}))
            return {"success": True, "chat": chat.__dict__}

        return result

    # ========================================================================
    # 메시지 관련 메서드
    # ========================================================================

    async def get_chat_messages(
        self,
        user_email: str,
        chat_id: Optional[str] = None,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """
        채팅 메시지 목록 조회

        Args:
            user_email: 사용자 이메일
            chat_id: 채팅 ID (없으면 Notes 채팅 사용)
            limit: 조회할 메시지 개수

        Returns:
            메시지 목록
        """
        chat_id = chat_id or self.NOTES_CHAT_ID
        endpoint = f"/me/chats/{chat_id}/messages?$top={limit}&$orderby=createdDateTime desc"
        result = await self._make_request("GET", endpoint, user_email)

        if result.get("success"):
            messages_data = result.get("data", {}).get("value", [])
            messages = [MessageInfo.from_dict(m) for m in messages_data]
            return {
                "success": True,
                "messages": [m.__dict__ for m in messages],
                "count": len(messages),
            }

        return result

    async def send_chat_message(
        self,
        user_email: str,
        content: str,
        chat_id: Optional[str] = None,
        prefix: str = "[claude]",
        content_type: str = "text",
    ) -> Dict[str, Any]:
        """
        채팅에 메시지 전송

        Args:
            user_email: 사용자 이메일
            content: 메시지 내용
            chat_id: 채팅 ID (없으면 Notes 채팅 사용)
            prefix: 메시지 프리픽스
            content_type: 콘텐츠 타입 (text 또는 html)

        Returns:
            전송된 메시지 정보
        """
        chat_id = chat_id or self.NOTES_CHAT_ID

        # 프리픽스 추가
        if prefix:
            full_content = f"{prefix} {content}"
        else:
            full_content = content

        endpoint = f"/me/chats/{chat_id}/messages"
        json_data = {
            "body": {
                "contentType": content_type,
                "content": full_content,
            }
        }

        result = await self._make_request("POST", endpoint, user_email, json_data)

        if result.get("success"):
            message = MessageInfo.from_dict(result.get("data", {}))
            return {
                "success": True,
                "message_id": message.id,
                "message": message.__dict__,
            }

        return result

    # ========================================================================
    # 팀 관련 메서드
    # ========================================================================

    async def list_teams(
        self,
        user_email: str,
    ) -> Dict[str, Any]:
        """
        사용자가 속한 팀 목록 조회

        Args:
            user_email: 사용자 이메일

        Returns:
            팀 목록
        """
        endpoint = "/me/joinedTeams"
        result = await self._make_request("GET", endpoint, user_email)

        if result.get("success"):
            teams_data = result.get("data", {}).get("value", [])
            teams = [TeamInfo.from_dict(t) for t in teams_data]
            return {
                "success": True,
                "teams": [t.__dict__ for t in teams],
                "count": len(teams),
            }

        return result

    async def list_channels(
        self,
        user_email: str,
        team_id: str,
    ) -> Dict[str, Any]:
        """
        팀의 채널 목록 조회

        Args:
            user_email: 사용자 이메일
            team_id: 팀 ID

        Returns:
            채널 목록
        """
        endpoint = f"/teams/{team_id}/channels"
        result = await self._make_request("GET", endpoint, user_email)

        if result.get("success"):
            channels_data = result.get("data", {}).get("value", [])
            channels = [ChannelInfo.from_dict(c) for c in channels_data]
            return {
                "success": True,
                "channels": [c.__dict__ for c in channels],
                "count": len(channels),
            }

        return result

    async def get_channel_messages(
        self,
        user_email: str,
        team_id: str,
        channel_id: str,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """
        채널 메시지 목록 조회

        Args:
            user_email: 사용자 이메일
            team_id: 팀 ID
            channel_id: 채널 ID
            limit: 조회할 메시지 개수

        Returns:
            메시지 목록
        """
        endpoint = f"/teams/{team_id}/channels/{channel_id}/messages?$top={limit}"
        result = await self._make_request("GET", endpoint, user_email)

        if result.get("success"):
            messages_data = result.get("data", {}).get("value", [])
            messages = [MessageInfo.from_dict(m) for m in messages_data]
            return {
                "success": True,
                "messages": [m.__dict__ for m in messages],
                "count": len(messages),
            }

        return result

    async def send_channel_message(
        self,
        user_email: str,
        team_id: str,
        channel_id: str,
        content: str,
        content_type: str = "text",
    ) -> Dict[str, Any]:
        """
        채널에 메시지 전송

        Args:
            user_email: 사용자 이메일
            team_id: 팀 ID
            channel_id: 채널 ID
            content: 메시지 내용
            content_type: 콘텐츠 타입 (text 또는 html)

        Returns:
            전송된 메시지 정보
        """
        endpoint = f"/teams/{team_id}/channels/{channel_id}/messages"
        json_data = {
            "body": {
                "contentType": content_type,
                "content": content,
            }
        }

        result = await self._make_request("POST", endpoint, user_email, json_data)

        if result.get("success"):
            message = MessageInfo.from_dict(result.get("data", {}))
            return {
                "success": True,
                "message_id": message.id,
                "message": message.__dict__,
            }

        return result

    async def get_message_replies(
        self,
        user_email: str,
        team_id: str,
        channel_id: str,
        message_id: str,
    ) -> Dict[str, Any]:
        """
        메시지 답글 목록 조회

        Args:
            user_email: 사용자 이메일
            team_id: 팀 ID
            channel_id: 채널 ID
            message_id: 메시지 ID

        Returns:
            답글 목록
        """
        endpoint = f"/teams/{team_id}/channels/{channel_id}/messages/{message_id}/replies"
        result = await self._make_request("GET", endpoint, user_email)

        if result.get("success"):
            replies_data = result.get("data", {}).get("value", [])
            replies = [MessageInfo.from_dict(r) for r in replies_data]
            return {
                "success": True,
                "replies": [r.__dict__ for r in replies],
                "count": len(replies),
            }

        return result
