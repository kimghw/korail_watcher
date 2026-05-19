"""Korean Air (KE) watcher config (CDP-only)."""

from __future__ import annotations

import os
from datetime import date, datetime, time
from pathlib import Path
from typing import List, Optional, Tuple

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


ENV_FILES = (Path(".env.air"), Path("env") / ".env", Path(".env"))


class ConfigError(RuntimeError):
    """Raised when configuration validation fails."""


def _load_env_files() -> None:
    for f in ENV_FILES:
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


class AirConfig(BaseModel):
    """CDP-only Korean Air watcher 설정."""

    # ─ CDP ─
    air_cdp_port: int = Field(9446, alias="AIR_CDP_PORT")
    air_chrome_exe: Optional[str] = Field(None, alias="AIR_CHROME_EXE")
    air_cdp_user_data_dir: Optional[str] = Field(None, alias="AIR_CDP_USER_DATA_DIR")
    air_cdp_startup_timeout: float = Field(15.0, alias="AIR_CDP_STARTUP_TIMEOUT")

    # ─ Trip shape ─
    air_trip_type: str = Field("oneway", alias="AIR_TRIP_TYPE")
    air_fare_type: str = Field("cash", alias="AIR_FARE_TYPE")

    # ─ Route / date ─
    air_origin: str = Field(alias="AIR_ORIGIN")
    air_dest: str = Field(alias="AIR_DEST")
    air_depart_date: date = Field(alias="AIR_DEPART_DATE")
    air_return_date: Optional[date] = Field(None, alias="AIR_RETURN_DATE")

    # ─ Times ─
    air_depart_times: List[time] = Field(alias="AIR_DEPART_TIMES")
    air_depart_time_window: Optional[Tuple[time, time]] = Field(
        None, alias="AIR_DEPART_TIME_WINDOW"
    )
    air_return_times: List[time] = Field(default_factory=list, alias="AIR_RETURN_TIMES")
    air_return_time_window: Optional[Tuple[time, time]] = Field(
        None, alias="AIR_RETURN_TIME_WINDOW"
    )

    # ─ Cabin / pax ─
    air_cabin: str = Field("", alias="AIR_CABIN")
    air_pax_adult: int = Field(1, alias="AIR_PAX_ADULT")
    air_pax_child: int = Field(0, alias="AIR_PAX_CHILD")
    air_pax_infant: int = Field(0, alias="AIR_PAX_INFANT")
    air_tolerance_min: int = Field(30, alias="AIR_TOLERANCE_MIN")
    air_flight_no: str = Field("", alias="AIR_FLIGHT_NO")

    # ─ Credentials (reserve 모드에서만 필수) ─
    air_user: str = Field("", alias="AIR_USER")
    air_pass: str = Field("", alias="AIR_PASS")

    # ─ Polling / mode ─
    air_poll_min: int = Field(5, alias="AIR_POLL_MIN")
    air_poll_max: int = Field(15, alias="AIR_POLL_MAX")
    air_once: bool = Field(False, alias="AIR_ONCE")
    air_mode: str = Field("search", alias="AIR_MODE")

    # ─ Misc ─
    air_log_dir: Path = Field(Path("./runs"), alias="AIR_LOG_DIR")
    air_log_level: str = Field("INFO", alias="AIR_LOG_LEVEL")

    # ─ Notifier ─
    teams_enabled: bool = Field(False, alias="TEAMS_ENABLED")
    teams_user_email: Optional[str] = Field(None, alias="TEAMS_USER_EMAIL")
    teams_chat_id: Optional[str] = Field(None, alias="TEAMS_CHAT_ID")
    teams_recipient_name: Optional[str] = Field(None, alias="TEAMS_RECIPIENT_NAME")
    teams_prefix: str = Field("[AIR WATCHER]", alias="TEAMS_PREFIX")

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    # ─ validators ─
    @field_validator("air_depart_date", mode="before")
    @classmethod
    def _parse_depart_date(cls, v):
        if isinstance(v, date):
            return v
        try:
            return datetime.strptime(v, "%Y-%m-%d").date()
        except (TypeError, ValueError) as e:
            raise ValueError("AIR_DEPART_DATE must be YYYY-MM-DD") from e

    @field_validator("air_return_date", mode="before")
    @classmethod
    def _parse_return_date(cls, v):
        if v in (None, ""):
            return None
        if isinstance(v, date):
            return v
        try:
            return datetime.strptime(v, "%Y-%m-%d").date()
        except (TypeError, ValueError) as e:
            raise ValueError("AIR_RETURN_DATE must be YYYY-MM-DD") from e

    @field_validator("air_depart_times", "air_return_times", mode="before")
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

    @field_validator("air_depart_time_window", "air_return_time_window", mode="before")
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

    @field_validator("air_once", "teams_enabled", mode="before")
    @classmethod
    def _parse_bool(cls, v):
        return _boolify(v)

    @field_validator("air_log_dir", mode="before")
    @classmethod
    def _parse_log_dir(cls, v):
        return v if isinstance(v, Path) else Path(str(v))

    @field_validator("air_log_level")
    @classmethod
    def _upper(cls, v):
        return v.upper()

    @field_validator("air_origin", "air_dest", mode="after")
    @classmethod
    def _iata(cls, v):
        v = (v or "").strip().upper()
        if not v:
            raise ValueError("required value cannot be empty")
        if len(v) != 3 or not v.isalpha():
            raise ValueError(f"airport code must be IATA 3-letter (got {v!r})")
        return v

    @field_validator("air_trip_type", mode="after")
    @classmethod
    def _trip(cls, v):
        v = (v or "").strip().lower()
        if v not in TRIP_TYPES:
            raise ValueError(f"AIR_TRIP_TYPE must be one of {sorted(TRIP_TYPES)}")
        return v

    @field_validator("air_fare_type", mode="after")
    @classmethod
    def _fare(cls, v):
        v = (v or "").strip().lower()
        if v not in FARE_TYPES:
            raise ValueError(f"AIR_FARE_TYPE must be one of {sorted(FARE_TYPES)}")
        return v

    @field_validator("air_cabin", mode="after")
    @classmethod
    def _cabin(cls, v):
        v = (v or "").strip().lower()
        if v not in CABIN_TYPES:
            raise ValueError(f"AIR_CABIN must be one of {sorted(CABIN_TYPES - {''})} or empty")
        return v

    @field_validator("air_user", "air_pass", "air_flight_no", mode="after")
    @classmethod
    def _strip_opt(cls, v):
        return (v or "").strip()

    @model_validator(mode="after")
    def _final(cls, values: "AirConfig"):
        if values.air_poll_min <= 0:
            raise ValueError("AIR_POLL_MIN must be > 0")
        if values.air_poll_max < values.air_poll_min:
            raise ValueError("AIR_POLL_MAX must be >= AIR_POLL_MIN")
        if values.air_cdp_port <= 0 or values.air_cdp_port > 65535:
            raise ValueError("AIR_CDP_PORT out of range")
        if values.air_mode not in {"search", "reserve"}:
            raise ValueError("AIR_MODE must be 'search' or 'reserve'")
        if not values.air_depart_times:
            raise ValueError("AIR_DEPART_TIMES must include at least one HH:MM")
        if values.air_origin == values.air_dest:
            raise ValueError("AIR_ORIGIN and AIR_DEST must differ")
        if values.air_pax_adult < 1:
            raise ValueError("AIR_PAX_ADULT must be >= 1")
        if values.air_trip_type == "roundtrip":
            if not values.air_return_date:
                raise ValueError("AIR_RETURN_DATE required for roundtrip")
            if not values.air_return_times:
                raise ValueError("AIR_RETURN_TIMES required for roundtrip")
            if values.air_return_date < values.air_depart_date:
                raise ValueError("AIR_RETURN_DATE must be >= AIR_DEPART_DATE")
        if values.air_mode == "reserve":
            if not values.air_user:
                raise ValueError("AIR_USER required for reserve mode")
            if not values.air_pass:
                raise ValueError("AIR_PASS required for reserve mode")
        return values


def load_config() -> AirConfig:
    _load_env_files()
    data = {k: os.environ.get(k, "") for k in os.environ}
    try:
        return AirConfig.model_validate(data)
    except ValidationError as e:
        raise ConfigError(str(e)) from e


__all__ = ["AirConfig", "ConfigError", "load_config"]
