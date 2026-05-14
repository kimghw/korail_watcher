"""
Teams Types
Teams 관련 타입 정의 (mcp_outlook/outlook_types.py 구조 참조)
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from enum import Enum


class ChatType(str, Enum):
    """채팅 유형"""
    ONE_ON_ONE = "oneOnOne"
    GROUP = "group"
    MEETING = "meeting"


class MessageImportance(str, Enum):
    """메시지 중요도"""
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class ChannelMembershipType(str, Enum):
    """채널 멤버십 유형"""
    STANDARD = "standard"
    PRIVATE = "private"
    SHARED = "shared"


@dataclass
class UserInfo:
    """사용자 정보"""
    id: str
    display_name: Optional[str] = None
    user_principal_name: Optional[str] = None
    email: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserInfo":
        user = data.get("user", data)
        return cls(
            id=user.get("id", ""),
            display_name=user.get("displayName"),
            user_principal_name=user.get("userPrincipalName"),
            email=user.get("email"),
        )


@dataclass
class ChatInfo:
    """채팅 정보"""
    id: str
    topic: Optional[str] = None
    chat_type: ChatType = ChatType.ONE_ON_ONE
    created_datetime: Optional[str] = None
    last_updated_datetime: Optional[str] = None
    last_message_preview: Optional[str] = None
    members: List[UserInfo] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChatInfo":
        chat_type_str = data.get("chatType", "oneOnOne")
        try:
            chat_type = ChatType(chat_type_str)
        except ValueError:
            chat_type = ChatType.ONE_ON_ONE

        members = []
        for member_data in data.get("members", []):
            members.append(UserInfo.from_dict(member_data))

        return cls(
            id=data.get("id", ""),
            topic=data.get("topic"),
            chat_type=chat_type,
            created_datetime=data.get("createdDateTime"),
            last_updated_datetime=data.get("lastUpdatedDateTime"),
            last_message_preview=data.get("lastMessagePreview", {}).get("body", {}).get("content") if data.get("lastMessagePreview") else None,
            members=members,
        )


@dataclass
class MessageInfo:
    """메시지 정보"""
    id: str
    body_content: str
    body_content_type: str = "text"
    created_datetime: Optional[str] = None
    last_modified_datetime: Optional[str] = None
    from_user: Optional[UserInfo] = None
    importance: MessageImportance = MessageImportance.NORMAL
    mentions: List[Dict[str, Any]] = field(default_factory=list)
    attachments: List[Dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MessageInfo":
        body = data.get("body", {})
        from_data = data.get("from", {})
        importance_str = data.get("importance", "normal")

        try:
            importance = MessageImportance(importance_str)
        except ValueError:
            importance = MessageImportance.NORMAL

        from_user = None
        if from_data:
            from_user = UserInfo.from_dict(from_data)

        return cls(
            id=data.get("id", ""),
            body_content=body.get("content", ""),
            body_content_type=body.get("contentType", "text"),
            created_datetime=data.get("createdDateTime"),
            last_modified_datetime=data.get("lastModifiedDateTime"),
            from_user=from_user,
            importance=importance,
            mentions=data.get("mentions", []),
            attachments=data.get("attachments", []),
        )


@dataclass
class TeamInfo:
    """팀 정보"""
    id: str
    display_name: str
    description: Optional[str] = None
    is_archived: bool = False
    created_datetime: Optional[str] = None
    visibility: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TeamInfo":
        return cls(
            id=data.get("id", ""),
            display_name=data.get("displayName", ""),
            description=data.get("description"),
            is_archived=data.get("isArchived", False),
            created_datetime=data.get("createdDateTime"),
            visibility=data.get("visibility"),
        )


@dataclass
class ChannelInfo:
    """채널 정보"""
    id: str
    display_name: str
    description: Optional[str] = None
    membership_type: ChannelMembershipType = ChannelMembershipType.STANDARD
    is_favorite_by_default: bool = False
    email: Optional[str] = None
    web_url: Optional[str] = None
    created_datetime: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChannelInfo":
        membership_str = data.get("membershipType", "standard")
        try:
            membership_type = ChannelMembershipType(membership_str)
        except ValueError:
            membership_type = ChannelMembershipType.STANDARD

        return cls(
            id=data.get("id", ""),
            display_name=data.get("displayName", ""),
            description=data.get("description"),
            membership_type=membership_type,
            is_favorite_by_default=data.get("isFavoriteByDefault", False),
            email=data.get("email"),
            web_url=data.get("webUrl"),
            created_datetime=data.get("createdDateTime"),
        )


@dataclass
class SendMessageRequest:
    """메시지 전송 요청"""
    chat_id: str
    content: str
    content_type: str = "text"
    importance: MessageImportance = MessageImportance.NORMAL
    prefix: str = "[claude]"


@dataclass
class GetMessagesRequest:
    """메시지 조회 요청"""
    chat_id: str
    limit: int = 50
    order_by: str = "createdDateTime desc"


@dataclass
class ListChatsRequest:
    """채팅 목록 조회 요청"""
    limit: int = 50
    filter_type: Optional[ChatType] = None
