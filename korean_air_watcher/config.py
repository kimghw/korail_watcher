"""Korean Air (KE) watcher config (CDP-only)."""

from __future__ import annotations

import os
from datetime import date, datetime, time
from pathlib import Path
from typing import List, Optional, Tuple

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


ENV_FILES = (Path(".env.korean_air"), Path("env") / ".env", Path(".env"))


class ConfigError(RuntimeError):
    """Raised when configuration validation fails."""


def _load_env_files() -> None:
    """`.env.korean_air` (또는 KOREAN_AIR_ENV_FILE 로 override 한 파일) → `.env` 순으로 로드.

    roundtrip 을 두 워처로 운영할 때 둘째 워처는
    `KOREAN_AIR_ENV_FILE=.env.korean_air.return python -m korean_air_watcher.main` 처럼 띄운다.
    """
    extra = os.getenv("KOREAN_AIR_ENV_FILE")
    files: list[Path] = []
    if extra:
        files.append(Path(extra))
    else:
        files.append(Path(".env.korean_air"))
    files.append(Path("env") / ".env")
    files.append(Path(".env"))
    for f in files:
        if f.is_file():
            load_dotenv(f, override=False)


def _boolify(v) -> bool:
    if isinstance(v, bool):
        return v
    if v is None:
        return False
    return str(v).strip().lower() in {"1", "true", "yes", "y", "on"}


TRIP_TYPES = {"oneway", "roundtrip"}
FARE_TYPES = {"cash", "miles", "both"}
CABIN_TYPES = {"", "economy", "prestige", "first"}


class KoreanAirConfig(BaseModel):
    """CDP-only Korean Air watcher 설정."""

    # ─ CDP ─
    korean_air_cdp_port: int = Field(9446, alias="KOREAN_AIR_CDP_PORT")
    korean_air_chrome_exe: Optional[str] = Field(None, alias="KOREAN_AIR_CHROME_EXE")
    korean_air_cdp_user_data_dir: Optional[str] = Field(None, alias="KOREAN_AIR_CDP_USER_DATA_DIR")
    korean_air_cdp_startup_timeout: float = Field(15.0, alias="KOREAN_AIR_CDP_STARTUP_TIMEOUT")

    # ─ Trip shape ─
    korean_air_trip_type: str = Field("oneway", alias="KOREAN_AIR_TRIP_TYPE")
    korean_air_fare_type: str = Field("cash", alias="KOREAN_AIR_FARE_TYPE")

    # ─ Route / date ─
    korean_air_origin: str = Field(alias="KOREAN_AIR_ORIGIN")
    korean_air_dest: str = Field(alias="KOREAN_AIR_DEST")
    korean_air_depart_date: date = Field(alias="KOREAN_AIR_DEPART_DATE")
    korean_air_return_date: Optional[date] = Field(None, alias="KOREAN_AIR_RETURN_DATE")

    # ─ Times ─
    korean_air_depart_times: List[time] = Field(alias="KOREAN_AIR_DEPART_TIMES")
    korean_air_depart_time_window: Optional[Tuple[time, time]] = Field(
        None, alias="KOREAN_AIR_DEPART_TIME_WINDOW"
    )
    korean_air_return_times: List[time] = Field(default_factory=list, alias="KOREAN_AIR_RETURN_TIMES")
    korean_air_return_time_window: Optional[Tuple[time, time]] = Field(
        None, alias="KOREAN_AIR_RETURN_TIME_WINDOW"
    )

    # ─ Cabin / pax ─
    korean_air_cabin: str = Field("", alias="KOREAN_AIR_CABIN")
    korean_air_pax_adult: int = Field(1, alias="KOREAN_AIR_PAX_ADULT")
    korean_air_pax_child: int = Field(0, alias="KOREAN_AIR_PAX_CHILD")
    korean_air_pax_infant: int = Field(0, alias="KOREAN_AIR_PAX_INFANT")
    korean_air_tolerance_min: int = Field(30, alias="KOREAN_AIR_TOLERANCE_MIN")
    korean_air_flight_no: str = Field("", alias="KOREAN_AIR_FLIGHT_NO")

    # ─ Credentials (search/reserve 모두 필수 — 익명 모드 미지원) ─
    korean_air_user: str = Field("", alias="KOREAN_AIR_USER")
    korean_air_pass: str = Field("", alias="KOREAN_AIR_PASS")

    # ─ Polling / mode ─
    korean_air_poll_min: int = Field(5, alias="KOREAN_AIR_POLL_MIN")
    korean_air_poll_max: int = Field(15, alias="KOREAN_AIR_POLL_MAX")
    korean_air_once: bool = Field(False, alias="KOREAN_AIR_ONCE")
    korean_air_mode: str = Field("search", alias="KOREAN_AIR_MODE")

    # ─ Misc ─
    korean_air_log_dir: Path = Field(Path("./runs"), alias="KOREAN_AIR_LOG_DIR")
    korean_air_log_level: str = Field("INFO", alias="KOREAN_AIR_LOG_LEVEL")

    # ─ Notifier ─
    teams_enabled: bool = Field(False, alias="TEAMS_ENABLED")
    teams_user_email: Optional[str] = Field(None, alias="TEAMS_USER_EMAIL")
    teams_chat_id: Optional[str] = Field(None, alias="TEAMS_CHAT_ID")
    teams_recipient_name: Optional[str] = Field(None, alias="TEAMS_RECIPIENT_NAME")
    teams_prefix: str = Field("[AIR WATCHER]", alias="TEAMS_PREFIX")

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    def as_oneway_outbound(self) -> "KoreanAirConfig":
        """warm-up·검색 호출용 — trip_type 만 oneway 로 강제한 cfg view.

        워처는 roundtrip 도 내부적으로 outbound/return 두 oneway 검색으로 처리.
        reserve.py 의 warm_up_select_flight 는 trip_type=roundtrip 이면 NotImplementedError
        를 던지므로 진입 전 view 변환이 필요하다.
        """
        return self.model_copy(update={
            "korean_air_trip_type": "oneway",
            "korean_air_return_date": None,
            "korean_air_return_times": [],
            "korean_air_return_time_window": None,
        })

    def swap_for_return(self) -> "KoreanAirConfig":
        """roundtrip 의 return leg view — origin/dest swap + return date/times/window 로 교체."""
        if not self.korean_air_return_date:
            raise ValueError("KOREAN_AIR_RETURN_DATE 가 비어있어 return view 를 만들 수 없음")
        return self.model_copy(update={
            "korean_air_trip_type": "oneway",
            "korean_air_origin": self.korean_air_dest,
            "korean_air_dest": self.korean_air_origin,
            "korean_air_depart_date": self.korean_air_return_date,
            "korean_air_depart_times": list(self.korean_air_return_times) or list(self.korean_air_depart_times),
            "korean_air_depart_time_window": self.korean_air_return_time_window or self.korean_air_depart_time_window,
            "korean_air_return_date": None,
            "korean_air_return_times": [],
            "korean_air_return_time_window": None,
        })

    # ─ validators ─
    @field_validator("korean_air_depart_date", mode="before")
    @classmethod
    def _parse_depart_date(cls, v):
        if isinstance(v, date):
            return v
        try:
            return datetime.strptime(v, "%Y-%m-%d").date()
        except (TypeError, ValueError) as e:
            raise ValueError("KOREAN_AIR_DEPART_DATE must be YYYY-MM-DD") from e

    @field_validator("korean_air_return_date", mode="before")
    @classmethod
    def _parse_return_date(cls, v):
        if v in (None, ""):
            return None
        if isinstance(v, date):
            return v
        try:
            return datetime.strptime(v, "%Y-%m-%d").date()
        except (TypeError, ValueError) as e:
            raise ValueError("KOREAN_AIR_RETURN_DATE must be YYYY-MM-DD") from e

    @field_validator("korean_air_depart_times", "korean_air_return_times", mode="before")
    @classmethod
    def _parse_times(cls, v):
        if isinstance(v, str):
            entries = [x.strip() for x in v.split(",") if x.strip()]
        else:
            entries = list(v or [])
        out = []
        for item in entries:
            if isinstance(item, time):
                out.append(item)
                continue
            try:
                out.append(datetime.strptime(item, "%H:%M").time())
            except Exception as e:
                raise ValueError(f"Invalid time: {item!r}") from e
        return out

    @field_validator("korean_air_depart_time_window", "korean_air_return_time_window", mode="before")
    @classmethod
    def _parse_window(cls, v):
        if v in ("", None):
            return None
        if isinstance(v, tuple):
            return v
        parts = [p.strip() for p in str(v).split(",") if p.strip()]
        if len(parts) != 2:
            raise ValueError("time window must be 'HH:MM,HH:MM'")
        try:
            s = datetime.strptime(parts[0], "%H:%M").time()
            e = datetime.strptime(parts[1], "%H:%M").time()
        except Exception as exc:
            raise ValueError("invalid time window") from exc
        if s > e:
            raise ValueError("time window start must be <= end")
        return s, e

    @field_validator("korean_air_once", "teams_enabled", mode="before")
    @classmethod
    def _parse_bool(cls, v):
        return _boolify(v)

    @field_validator("korean_air_log_dir", mode="before")
    @classmethod
    def _parse_log_dir(cls, v):
        return v if isinstance(v, Path) else Path(str(v))

    @field_validator("korean_air_log_level")
    @classmethod
    def _upper(cls, v):
        return v.upper()

    @field_validator("korean_air_origin", "korean_air_dest", mode="after")
    @classmethod
    def _iata(cls, v):
        v = (v or "").strip().upper()
        if not v:
            raise ValueError("required value cannot be empty")
        if len(v) != 3 or not v.isalpha():
            raise ValueError(f"airport code must be IATA 3-letter (got {v!r})")
        return v

    @field_validator("korean_air_trip_type", mode="after")
    @classmethod
    def _trip(cls, v):
        v = (v or "").strip().lower()
        if v not in TRIP_TYPES:
            raise ValueError(f"KOREAN_AIR_TRIP_TYPE must be one of {sorted(TRIP_TYPES)}")
        return v

    @field_validator("korean_air_fare_type", mode="after")
    @classmethod
    def _fare(cls, v):
        v = (v or "").strip().lower()
        if v not in FARE_TYPES:
            raise ValueError(f"KOREAN_AIR_FARE_TYPE must be one of {sorted(FARE_TYPES)}")
        return v

    @field_validator("korean_air_cabin", mode="after")
    @classmethod
    def _cabin(cls, v):
        v = (v or "").strip().lower()
        if v not in CABIN_TYPES:
            raise ValueError(f"KOREAN_AIR_CABIN must be one of {sorted(CABIN_TYPES - {''})} or empty")
        return v

    @field_validator("korean_air_user", "korean_air_pass", "korean_air_flight_no", mode="after")
    @classmethod
    def _strip_opt(cls, v):
        return (v or "").strip()

    @model_validator(mode="after")
    def _final(cls, values: "KoreanAirConfig"):
        if values.korean_air_poll_min <= 0:
            raise ValueError("KOREAN_AIR_POLL_MIN must be > 0")
        if values.korean_air_poll_max < values.korean_air_poll_min:
            raise ValueError("KOREAN_AIR_POLL_MAX must be >= KOREAN_AIR_POLL_MIN")
        if values.korean_air_cdp_port <= 0 or values.korean_air_cdp_port > 65535:
            raise ValueError("KOREAN_AIR_CDP_PORT out of range")
        if values.korean_air_mode not in {"search", "reserve"}:
            raise ValueError("KOREAN_AIR_MODE must be 'search' or 'reserve'")
        if not values.korean_air_depart_times:
            raise ValueError("KOREAN_AIR_DEPART_TIMES must include at least one HH:MM")
        if values.korean_air_origin == values.korean_air_dest:
            raise ValueError("KOREAN_AIR_ORIGIN and KOREAN_AIR_DEST must differ")
        if values.korean_air_pax_adult < 1:
            raise ValueError("KOREAN_AIR_PAX_ADULT must be >= 1")
        if values.korean_air_trip_type == "roundtrip":
            if not values.korean_air_return_date:
                raise ValueError("KOREAN_AIR_RETURN_DATE required for roundtrip")
            if not values.korean_air_return_times:
                raise ValueError("KOREAN_AIR_RETURN_TIMES required for roundtrip")
            if values.korean_air_return_date < values.korean_air_depart_date:
                raise ValueError("KOREAN_AIR_RETURN_DATE must be >= KOREAN_AIR_DEPART_DATE")
        if not values.korean_air_user:
            raise ValueError("KOREAN_AIR_USER required — 익명 모드 미지원, 로그인 필수")
        if not values.korean_air_pass:
            raise ValueError("KOREAN_AIR_PASS required — 익명 모드 미지원, 로그인 필수")
        return values


def load_config() -> KoreanAirConfig:
    _load_env_files()
    data = {k: os.environ.get(k, "") for k in os.environ}
    try:
        return KoreanAirConfig.model_validate(data)
    except ValidationError as e:
        raise ConfigError(str(e)) from e


__all__ = ["KoreanAirConfig", "ConfigError", "load_config"]
