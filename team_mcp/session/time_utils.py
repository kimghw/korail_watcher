"""
시간대 처리 유틸리티
UTC와 로컬 시간 변환을 담당
"""

from datetime import datetime, timezone, timedelta
from typing import Optional


def utc_now() -> datetime:
    """현재 UTC 시간 반환"""
    return datetime.now(timezone.utc)


def to_utc(dt: datetime) -> datetime:
    """
    datetime을 UTC로 변환

    Args:
        dt: 변환할 datetime (timezone aware or naive)

    Returns:
        UTC datetime
    """
    if dt.tzinfo is None:
        # naive datetime은 UTC로 가정
        return dt.replace(tzinfo=timezone.utc)
    else:
        # timezone aware는 UTC로 변환
        return dt.astimezone(timezone.utc)


def to_local(dt: datetime) -> datetime:
    """
    UTC datetime을 로컬 시간으로 변환

    Args:
        dt: UTC datetime

    Returns:
        로컬 시간대 datetime
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone()


def format_local_time(dt: datetime, format_str: str = "%Y-%m-%d %H:%M:%S %Z") -> str:
    """
    UTC datetime을 로컬 시간 문자열로 포맷

    Args:
        dt: UTC datetime
        format_str: 시간 포맷 문자열

    Returns:
        포맷된 로컬 시간 문자열
    """
    local_dt = to_local(dt)
    return local_dt.strftime(format_str)


def parse_iso_to_utc(iso_string: str) -> datetime:
    """
    ISO 형식 문자열을 UTC datetime으로 파싱

    Args:
        iso_string: ISO 형식 시간 문자열

    Returns:
        UTC datetime
    """
    dt = datetime.fromisoformat(iso_string)
    return to_utc(dt)


def time_until_expiry(expires_at: datetime) -> str:
    """
    만료까지 남은 시간을 사람이 읽기 쉬운 형태로 반환

    Args:
        expires_at: 만료 시간 (UTC)

    Returns:
        남은 시간 문자열 (예: "2 hours 30 minutes")
    """
    if isinstance(expires_at, str):
        expires_at = parse_iso_to_utc(expires_at)

    remaining = expires_at - utc_now()

    if remaining.total_seconds() <= 0:
        return "Expired"

    days = remaining.days
    hours, remainder = divmod(remaining.seconds, 3600)
    minutes, _ = divmod(remainder, 60)

    parts = []
    if days > 0:
        parts.append(f"{days} day{'s' if days != 1 else ''}")
    if hours > 0:
        parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
    if minutes > 0 and days == 0:  # 날짜가 있으면 분은 생략
        parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")

    return " ".join(parts) if parts else "Less than a minute"


def is_expired(expires_at: datetime, buffer_seconds: int = 300) -> bool:
    """
    만료 여부 확인 (선택적 버퍼 시간 포함)

    Args:
        expires_at: 만료 시간
        buffer_seconds: 버퍼 시간 (기본 5분)

    Returns:
        만료 여부
    """
    if isinstance(expires_at, str):
        expires_at = parse_iso_to_utc(expires_at)

    # 버퍼 시간을 뺀 시점에서 만료 체크
    return utc_now() >= (expires_at - timedelta(seconds=buffer_seconds))


# 사용 예시
if __name__ == "__main__":
    from datetime import timedelta

    # UTC 시간 생성
    now = utc_now()
    expires = now + timedelta(hours=1)

    print(f"Current UTC: {now}")
    print(f"Current Local: {to_local(now)}")
    print(f"Expires at (UTC): {expires}")
    print(f"Expires at (Local): {format_local_time(expires)}")
    print(f"Time remaining: {time_until_expiry(expires)}")

    # ISO 문자열 파싱
    iso_str = "2024-12-05T10:30:00+09:00"  # 한국 시간
    utc_dt = parse_iso_to_utc(iso_str)
    print(f"\nKST {iso_str} → UTC {utc_dt}")