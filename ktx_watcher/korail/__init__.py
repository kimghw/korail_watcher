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


class ReservationFailed(KorailError):
    """예매 클릭 후 예약이 실제로 성립하지 않음 (잔여석 소진 등) — 다음 iteration 재시도."""


__all__ = [
    "KorailError",
    "CaptchaDetected",
    "LoginError",
    "SiteLayoutChanged",
    "UserActionRequired",
    "ReservationFailed",
]
