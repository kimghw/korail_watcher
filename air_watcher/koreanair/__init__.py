"""Korean Air SPA driver — CDP-only."""


class AirError(RuntimeError):
    """Base error."""


class BotGuardDetected(AirError):
    """Akamai/Datadome 류 봇 가드 감지."""


class LoginError(AirError):
    """로그인 실패."""


class SiteLayoutChanged(AirError):
    """예상 selector 가 매치되지 않음."""


class UserActionRequired(AirError):
    """사용자 개입 필요 (예: 2FA / 본인인증)."""


__all__ = [
    "AirError",
    "BotGuardDetected",
    "LoginError",
    "SiteLayoutChanged",
    "UserActionRequired",
]
