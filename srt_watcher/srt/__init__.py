from __future__ import annotations


class SiteLayoutChanged(RuntimeError):
    """Raised when selectors no longer match expected layout."""


class CaptchaDetected(RuntimeError):
    """Raised when captcha or additional authentication is detected."""


class UserActionRequired(RuntimeError):
    """Raised when manual user interaction is required to continue."""


__all__ = ["SiteLayoutChanged", "CaptchaDetected", "UserActionRequired"]
