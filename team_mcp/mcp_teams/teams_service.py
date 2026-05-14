"""
Teams Service - GraphTeamsClient Facade
인자를 그대로 위임하고, 필요시 일부 값만 조정하는 서비스 레이어
(mcp_outlook/outlook_service.py 구조 참조)
"""

from typing import Dict, Any, Optional, List

from .graph_teams_client import GraphTeamsClient
from .teams_db_manager import TeamsDBManager
from .teams_types import (
    ChatType,
    MessageImportance,
)
from session.auth_database import AuthDatabase

# mcp_service decorator is only needed for registry scanning, not runtime
try:
    from mcp_editor.mcp_service_registry.mcp_service_decorator import mcp_service
except ImportError:
    # Define a no-op decorator for runtime when mcp_editor is not available
    def mcp_service(**kwargs):
        def decorator(func):
            return func
        return decorator


def _get_default_user_email() -> Optional[str]:
    """
    auth.db의 azure_user_info 테이블에서 첫 번째 user_email을 가져옴

    Returns:
        첫 번째 등록된 사용자의 이메일 또는 None
    """
    db = AuthDatabase()
    users = db.list_users()
    if users:
        return users[0].get('user_email') or users[0].get('email')
    return None


class TeamsService:
    """
    GraphTeamsClient의 Facade

    - 동일 시그니처로 위임
    - 일부 값만 조정/하드코딩
    - DB 연동으로 한글 이름 저장/조회 지원
    """

    def __init__(self):
        self._client: Optional[GraphTeamsClient] = None
        self._db_manager: Optional[TeamsDBManager] = None
        self._initialized = False

    async def initialize(self) -> bool:
        """서비스 초기화"""
        if self._initialized:
            return True

        self._client = GraphTeamsClient()
        self._db_manager = TeamsDBManager()

        if await self._client.initialize():
            self._initialized = True
            return True
        return False

    def _ensure_initialized(self):
        """초기화 확인"""
        if not self._initialized or not self._client:
            raise RuntimeError("TeamsService not initialized. Call initialize() first.")

    async def close(self):
        """리소스 정리"""
        if self._client:
            await self._client.close()
            self._client = None
        self._initialized = False

    # ========================================================================
    # 채팅 관련 메서드
    # ========================================================================

    @mcp_service(
        tool_name="handler_teams_list_chats",
        server_name="teams",
        service_name="list_chats",
        category="teams_chat",
        tags=["query", "chat"],
        priority=5,
        description="Teams 채팅 목록 조회",
    )
    async def list_chats(
        self,
        user_email: Optional[str] = None,
        limit: int = 50,
    ) -> Dict[str, Any]:
        """채팅 목록 조회"""
        self._ensure_initialized()
        if not user_email:
            user_email = _get_default_user_email()
        if not user_email:
            return {"success": False, "error": "사용자 이메일이 필요합니다. 로그인이 필요합니다."}
        return await self._client.list_chats(user_email, limit)

    @mcp_service(
        tool_name="handler_teams_get_chat",
        server_name="teams",
        service_name="get_chat",
        category="teams_chat",
        tags=["query", "chat"],
        priority=5,
        description="Teams 특정 채팅 정보 조회",
    )
    async def get_chat(
        self,
        chat_id: str,
        user_email: Optional[str] = None,
    ) -> Dict[str, Any]:
        """특정 채팅 정보 조회"""
        self._ensure_initialized()
        if not user_email:
            user_email = _get_default_user_email()
        if not user_email:
            return {"success": False, "error": "사용자 이메일이 필요합니다. 로그인이 필요합니다."}
        return await self._client.get_chat(user_email, chat_id)

    # ========================================================================
    # 메시지 관련 메서드
    # ========================================================================

    @mcp_service(
        tool_name="handler_teams_get_chat_messages",
        server_name="teams",
        service_name="get_chat_messages",
        category="teams_message",
        tags=["query", "message"],
        priority=5,
        description="Teams 채팅 메시지 목록 조회",
    )
    async def get_chat_messages(
        self,
        chat_id: Optional[str] = None,
        limit: int = 50,
        user_email: Optional[str] = None,
    ) -> Dict[str, Any]:
        """채팅 메시지 목록 조회"""
        self._ensure_initialized()
        if not user_email:
            user_email = _get_default_user_email()
        if not user_email:
            return {"success": False, "error": "사용자 이메일이 필요합니다. 로그인이 필요합니다."}
        return await self._client.get_chat_messages(user_email, chat_id, limit)

    @mcp_service(
        tool_name="handler_teams_send_chat_message",
        server_name="teams",
        service_name="send_chat_message",
        category="teams_message",
        tags=["send", "message"],
        priority=5,
        description="Teams 채팅에 메시지 전송",
    )
    async def send_chat_message(
        self,
        content: str,
        chat_id: Optional[str] = None,
        prefix: str = "[claude]",
        content_type: str = "text",
        user_email: Optional[str] = None,
    ) -> Dict[str, Any]:
        """채팅에 메시지 전송"""
        self._ensure_initialized()
        if not user_email:
            user_email = _get_default_user_email()
        if not user_email:
            return {"success": False, "error": "사용자 이메일이 필요합니다. 로그인이 필요합니다."}
        return await self._client.send_chat_message(
            user_email=user_email,
            content=content,
            chat_id=chat_id,
            prefix=prefix,
            content_type=content_type,
        )

    # ========================================================================
    # 팀 관련 메서드
    # ========================================================================

    @mcp_service(
        tool_name="handler_teams_list_teams",
        server_name="teams",
        service_name="list_teams",
        category="teams_team",
        tags=["query", "team"],
        priority=5,
        description="사용자가 속한 팀 목록 조회",
    )
    async def list_teams(
        self,
        user_email: Optional[str] = None,
    ) -> Dict[str, Any]:
        """팀 목록 조회"""
        self._ensure_initialized()
        if not user_email:
            user_email = _get_default_user_email()
        if not user_email:
            return {"success": False, "error": "사용자 이메일이 필요합니다. 로그인이 필요합니다."}
        return await self._client.list_teams(user_email)

    @mcp_service(
        tool_name="handler_teams_list_channels",
        server_name="teams",
        service_name="list_channels",
        category="teams_channel",
        tags=["query", "channel"],
        priority=5,
        description="팀의 채널 목록 조회",
    )
    async def list_channels(
        self,
        team_id: str,
        user_email: Optional[str] = None,
    ) -> Dict[str, Any]:
        """채널 목록 조회"""
        self._ensure_initialized()
        if not user_email:
            user_email = _get_default_user_email()
        if not user_email:
            return {"success": False, "error": "사용자 이메일이 필요합니다. 로그인이 필요합니다."}
        return await self._client.list_channels(user_email, team_id)

    @mcp_service(
        tool_name="handler_teams_get_channel_messages",
        server_name="teams",
        service_name="get_channel_messages",
        category="teams_message",
        tags=["query", "channel", "message"],
        priority=5,
        description="채널 메시지 목록 조회",
    )
    async def get_channel_messages(
        self,
        team_id: str,
        channel_id: str,
        limit: int = 50,
        user_email: Optional[str] = None,
    ) -> Dict[str, Any]:
        """채널 메시지 목록 조회"""
        self._ensure_initialized()
        if not user_email:
            user_email = _get_default_user_email()
        if not user_email:
            return {"success": False, "error": "사용자 이메일이 필요합니다. 로그인이 필요합니다."}
        return await self._client.get_channel_messages(user_email, team_id, channel_id, limit)

    @mcp_service(
        tool_name="handler_teams_send_channel_message",
        server_name="teams",
        service_name="send_channel_message",
        category="teams_message",
        tags=["send", "channel", "message"],
        priority=5,
        description="채널에 메시지 전송",
    )
    async def send_channel_message(
        self,
        team_id: str,
        channel_id: str,
        content: str,
        content_type: str = "text",
        user_email: Optional[str] = None,
    ) -> Dict[str, Any]:
        """채널에 메시지 전송"""
        self._ensure_initialized()
        if not user_email:
            user_email = _get_default_user_email()
        if not user_email:
            return {"success": False, "error": "사용자 이메일이 필요합니다. 로그인이 필요합니다."}
        return await self._client.send_channel_message(
            user_email=user_email,
            team_id=team_id,
            channel_id=channel_id,
            content=content,
            content_type=content_type,
        )

    @mcp_service(
        tool_name="handler_teams_get_message_replies",
        server_name="teams",
        service_name="get_message_replies",
        category="teams_message",
        tags=["query", "reply"],
        priority=5,
        description="메시지 답글 목록 조회",
    )
    async def get_message_replies(
        self,
        team_id: str,
        channel_id: str,
        message_id: str,
        user_email: Optional[str] = None,
    ) -> Dict[str, Any]:
        """메시지 답글 목록 조회"""
        self._ensure_initialized()
        if not user_email:
            user_email = _get_default_user_email()
        if not user_email:
            return {"success": False, "error": "사용자 이메일이 필요합니다. 로그인이 필요합니다."}
        return await self._client.get_message_replies(user_email, team_id, channel_id, message_id)

    # ========================================================================
    # 한글 이름 관련 메서드 (DB 연동)
    # ========================================================================

    @mcp_service(
        tool_name="handler_teams_save_korean_name",
        server_name="teams",
        service_name="save_korean_name",
        category="teams_chat",
        tags=["update", "korean"],
        priority=5,
        description="채팅방의 한글 이름을 DB에 저장 (단일 저장)",
    )
    async def save_korean_name(
        self,
        topic_kr: str,
        chat_id: Optional[str] = None,
        topic_en: Optional[str] = None,
        user_email: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        채팅의 한글 이름을 저장

        Args:
            topic_kr: 한글 이름
            chat_id: 채팅 ID (선택)
            topic_en: 영문 이름 (선택, chat_id가 없을 때 검색용)
            user_email: 사용자 이메일 (선택, 없으면 기본 사용자)

        Returns:
            저장 결과
        """
        self._ensure_initialized()
        if not user_email:
            user_email = _get_default_user_email()
        if not user_email:
            return {"success": False, "error": "사용자 이메일이 필요합니다. 로그인이 필요합니다."}
        return await self._db_manager.save_korean_name(
            user_id=user_email,
            topic_kr=topic_kr,
            chat_id=chat_id,
            topic_en=topic_en,
        )

    @mcp_service(
        tool_name="handler_teams_save_korean_names_batch",
        server_name="teams",
        service_name="save_korean_names_batch",
        category="teams_chat",
        tags=["update", "korean", "batch"],
        priority=5,
        description="여러 채팅방의 한글 이름을 한 번에 DB에 저장",
    )
    async def save_korean_names_batch(
        self,
        names: List[Dict[str, str]],
        user_email: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        여러 채팅의 한글 이름을 한 번에 저장

        Args:
            names: [{"topic_en": "영문", "topic_kr": "한글"}, ...] 형식의 리스트
            user_email: 사용자 이메일 (선택, 없으면 기본 사용자)

        Returns:
            배치 저장 결과
        """
        self._ensure_initialized()
        if not user_email:
            user_email = _get_default_user_email()
        if not user_email:
            return {"success": False, "error": "사용자 이메일이 필요합니다. 로그인이 필요합니다."}
        return await self._db_manager.save_korean_names_batch(
            user_id=user_email,
            names=names,
        )

    @mcp_service(
        tool_name="handler_teams_find_chat_by_name",
        server_name="teams",
        service_name="find_chat_by_name",
        category="teams_chat",
        tags=["query", "search"],
        priority=5,
        description="사용자 이름으로 채팅 검색 (한글/영문 모두 지원)",
    )
    async def find_chat_by_name(
        self,
        recipient_name: str,
        user_email: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        사용자 이름으로 채팅 검색

        Args:
            recipient_name: 검색할 상대방 이름 (한글 또는 영문)
            user_email: 사용자 이메일 (선택, 없으면 기본 사용자)

        Returns:
            검색된 chat_id
        """
        self._ensure_initialized()
        if not user_email:
            user_email = _get_default_user_email()
        if not user_email:
            return {"success": False, "error": "사용자 이메일이 필요합니다. 로그인이 필요합니다."}
        chat_id = await self._db_manager.find_chat_by_name(
            user_id=user_email,
            recipient_name=recipient_name,
        )
        if chat_id:
            return {"success": True, "chat_id": chat_id}
        return {"success": False, "message": f"'{recipient_name}' 채팅을 찾을 수 없습니다"}

    @mcp_service(
        tool_name="handler_teams_sync_chats",
        server_name="teams",
        service_name="sync_chats",
        category="teams_chat",
        tags=["sync", "db"],
        priority=5,
        description="채팅 목록을 DB에 동기화",
    )
    async def sync_chats(
        self,
        limit: int = 50,
        user_email: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        채팅 목록을 조회하고 DB에 동기화

        Args:
            limit: 조회할 채팅 개수
            user_email: 사용자 이메일 (선택, 없으면 기본 사용자)

        Returns:
            동기화 결과
        """
        self._ensure_initialized()

        if not user_email:
            user_email = _get_default_user_email()
        if not user_email:
            return {"success": False, "error": "사용자 이메일이 필요합니다. 로그인이 필요합니다."}

        # Graph API에서 채팅 목록 조회
        result = await self._client.list_chats(user_email, limit)
        if not result.get("success"):
            return result

        # DB에 동기화
        chats = result.get("chats", [])
        sync_result = await self._db_manager.sync_chats_to_db(user_email, chats)

        return {
            "success": True,
            "chats_count": len(chats),
            "synced": sync_result.get("synced", 0),
            "deactivated": sync_result.get("deactivated", 0),
        }

    @mcp_service(
        tool_name="handler_teams_get_chats_without_korean",
        server_name="teams",
        service_name="get_chats_without_korean",
        category="teams_chat",
        tags=["query", "korean"],
        priority=5,
        description="한글 이름이 없는 채팅 목록 조회",
    )
    async def get_chats_without_korean(
        self,
        user_email: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        한글 이름이 없는 채팅 목록 조회

        Args:
            user_email: 사용자 이메일 (선택, 없으면 기본 사용자)

        Returns:
            한글 이름이 없는 채팅 목록
        """
        self._ensure_initialized()
        if not user_email:
            user_email = _get_default_user_email()
        if not user_email:
            return {"success": False, "error": "사용자 이메일이 필요합니다. 로그인이 필요합니다."}
        chats = await self._db_manager.get_chats_without_korean_names(user_email)
        return {
            "success": True,
            "chats": chats,
            "count": len(chats),
        }
