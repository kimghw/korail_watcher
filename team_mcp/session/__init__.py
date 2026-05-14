"""
Azure Authentication Module
Azure AD OAuth 2.0 인증을 처리하는 모듈입니다.
"""

from .auth_service import AuthService
from .auth_manager import AuthManager
from .azure_config import AzureConfig
from .auth_database import AuthDatabase

# 메인 인터페이스
__all__ = [
    # 클래스
    'AuthManager',           # 메인 매니저 - 다중 사용자 관리
    'AuthService',           # 인증 서비스 - OAuth 플로우
    'AzureConfig',           # Azure 설정 관리
    'AuthDatabase',          # 인증 데이터베이스 관리
]

__version__ = '1.0.0'