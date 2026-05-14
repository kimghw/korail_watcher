"""
MCP Teams Module
Microsoft Graph API를 사용한 Teams 서비스 (mcp_outlook 구조 참조)
"""

from .teams_service import TeamsService
from .graph_teams_client import GraphTeamsClient
from .teams_db_manager import TeamsDBManager
from .teams_types import (
    ChatInfo,
    MessageInfo,
    TeamInfo,
    ChannelInfo,
    SendMessageRequest,
    GetMessagesRequest,
)

__all__ = [
    # Service
    "TeamsService",
    # Client
    "GraphTeamsClient",
    # DB Manager
    "TeamsDBManager",
    # Types
    "ChatInfo",
    "MessageInfo",
    "TeamInfo",
    "ChannelInfo",
    "SendMessageRequest",
    "GetMessagesRequest",
]

__version__ = "1.0.0"
