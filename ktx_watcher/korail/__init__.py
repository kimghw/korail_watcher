"""Korail SPA driver — CDP-only."""


class KorailError(RuntimeError):
    """Base error."""


class CaptchaDetected(KorailError):
    """매크로/봇 가드(-8002/-8003) 감지 및 dismiss 실패."""


class LoginError(KorailError):
    """로그인 실패."""


class SiteLayoutChanged(KorailError):
    """예상 selector 가 매치되지 않음."""


class UserActionRequired(KorailError):
    """사용자 개입 필요 (예: 추가 본인인증)."""


__all__ = [
    "KorailError",
    "CaptchaDetected",
    "LoginError",
    "SiteLayoutChanged",
    "UserActionRequired",
]
