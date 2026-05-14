from __future__ import annotations

import logging
import math
import random
import re
import signal
import string
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Iterable, Optional, Sequence, Tuple

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential
from zoneinfo import ZoneInfo

SEOUL_TZ = ZoneInfo("Asia/Seoul")
_LOGGER = logging.getLogger("srt_watcher.utils")

SUSPICIOUS_KEYWORDS: Sequence[str] = (
    "자동화",
    "봇",
    "추가 인증",
    "captcha",
    "bot",
    "automation",
    # SRT NetFunnel / 대기열 관련
    "netfunnel",
    "NetFunnel_Loading_Popup",
    "접속대기 중입니다",
    "현재 접속 사용자가 많아 대기 중이며",
)



def seoul_now() -> datetime:
    return datetime.now(tz=SEOUL_TZ)


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def mask_sensitive(text: str, keep: int = 2) -> str:
    if not text:
        return text
    if len(text) <= keep:
        return "*" * len(text)
    hidden = "*" * (len(text) - keep)
    return hidden + text[-keep:]


def safe_filename(seed: str) -> str:
    valid = string.ascii_letters + string.digits + "-_"
    filtered = [ch if ch in valid else "-" for ch in seed]
    collapsed = re.sub("-+", "-", "".join(filtered)).strip("-")
    return collapsed or "artifact"


def timestamped_path(base: Path, prefix: str, suffix: str = "") -> Path:
    now = seoul_now()
    stamp = now.strftime("%Y%m%d-%H%M%S")
    name = f"{prefix}-{stamp}{suffix}"
    return base / safe_filename(name)


def detect_suspicious(text: str) -> bool:
    """페이지가 진짜 캡차/자동접속 차단 페이지로 보일 때만 True 반환.

    - 일반 JS 코드나 설명에 등장할 수 있는 'bot', 'automation', '자동화' 등은 제외.
    - 사용자에게 노출되는 경고/보안 문구 위주로 판단.
    """
    if not text:
        return False

    lowered = text.lower()

    suspicious_phrases = [
        # 한글 안내 문구들 (예시는 상황 맞게 조정 가능)
        "자동입력 방지",
        "보안문자를 입력",
        "보안 문자를 입력",
        "비정상적인 접근",
        "비정상 적인 접근",
        "비정상적인 접속",
        "비정상 적인 접속",
        "자동 접속이 감지되었습니다",
        "자동 접속이 감지 되었습니다",
        "자동화된 프로그램으로 인한 접속",
        "자동화 프로그램에 의한 접속",

        # 전형적인 캡차/로봇 체크 문구
        "i am not a robot",
        "i'm not a robot",
        "select all images with",
        "verify you are human",
        "please verify you are human",
        "captcha",  # 진짜 캡차 페이지 텍스트에 자주 포함
    ]

    return any(phrase in lowered for phrase in suspicious_phrases)


def minutes_difference(lhs: time, rhs: time) -> int:
    today = date.today()
    dt_l = datetime.combine(today, lhs)
    dt_r = datetime.combine(today, rhs)
    diff = dt_l - dt_r
    return int(abs(diff.total_seconds()) // 60)


def is_candidate(
    candidate_time: time,
    preferred_times: Sequence[time],
    tolerance_min: int,
    time_window: Optional[Tuple[time, time]],
) -> bool:
    """열차 출발시간이 조건에 맞는 후보인지 판단.

    우선순위:
    1. SRT_TIME_WINDOW 설정 시 → 창 안에 있으면 무조건 후보
    2. SRT_TOLERANCE_MIN > 0  → preferred_times 각각에 대해 ±N분 이내면 후보
    3. SRT_TOLERANCE_MIN = 0  → preferred_times와 정확히 일치하는 열차만 후보
    """
    if time_window:
        start, end = time_window
        if candidate_time < start or candidate_time > end:
            return False
        return True  # window 안이면 즉시 True, 아래 검사 불필요

    if not preferred_times:
        return True  # 선호 시각 없으면 모두 후보

    if tolerance_min <= 0:
        # exact match — preferred 시각과 정확히 같은 열차만 후보
        return candidate_time in preferred_times

    for preferred in preferred_times:
        if minutes_difference(candidate_time, preferred) <= tolerance_min:
            return True

    return False


def graceful_shutdown(handler):
    signal.signal(signal.SIGTERM, handler)
    signal.signal(signal.SIGINT, handler)


def retry_async_exceptions(exc_types: Iterable[type[BaseException]] = (Exception,), attempts: int = 3):
    return retry(
        retry=retry_if_exception_type(tuple(exc_types)),
        stop=stop_after_attempt(attempts),
        wait=wait_exponential(multiplier=1, min=1, max=5),
        reraise=True,
    )


__all__ = [
    "SEOUL_TZ",
    "seoul_now",
    "ensure_dir",
    "mask_sensitive",
    "safe_filename",
    "timestamped_path",
    "detect_suspicious",
    "is_candidate",
    "graceful_shutdown",
    "retry_async_exceptions",
]