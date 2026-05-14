from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from . import utils

ENV_FILES = (
    Path("env") / ".env",
    Path(".env"),
)

REQUIRED_ENV_KEYS = (
    "SRT_USER",
    "SRT_PASS",
    "SRT_ORIGIN",
    "SRT_DEST",
    "SRT_DATE",
    "SRT_TIMES",
)


class ConfigError(RuntimeError):
    """Raised when configuration validation fails."""


def _load_env_files() -> None:
    for env_file in ENV_FILES:
        if env_file.is_file():
            load_dotenv(env_file, override=False)


def _boolify(value: str | bool | None) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


class SRTConfig(BaseModel):
    srt_user: str = Field(alias="SRT_USER")
    srt_pass: str = Field(alias="SRT_PASS")
    srt_origin: str = Field(alias="SRT_ORIGIN")
    srt_dest: str = Field(alias="SRT_DEST")
    srt_date: date = Field(alias="SRT_DATE")
    srt_times: List[time] = Field(alias="SRT_TIMES")

    # Microsoft Teams 알림 (team_mcp 사용)
    teams_enabled: bool = Field(True, alias="TEAMS_ENABLED")
    teams_user_email: Optional[str] = Field(None, alias="TEAMS_USER_EMAIL")
    teams_chat_id: Optional[str] = Field(None, alias="TEAMS_CHAT_ID")
    teams_recipient_name: Optional[str] = Field(None, alias="TEAMS_RECIPIENT_NAME")
    teams_prefix: str = Field("[SRT WATCHER]", alias="TEAMS_PREFIX")

    srt_passengers: int = Field(1, alias="SRT_PASSENGERS")
    srt_seat_class: str = Field("일반실", alias="SRT_SEAT_CLASS")
    srt_tolerance_min: int = Field(0, alias="SRT_TOLERANCE_MIN")
    srt_time_window: Optional[Tuple[time, time]] = Field(None, alias="SRT_TIME_WINDOW")
    srt_headless: bool = Field(True, alias="SRT_HEADLESS")
    srt_poll_min: int = Field(3, alias="SRT_POLL_MIN")
    srt_poll_max: int = Field(10, alias="SRT_POLL_MAX")
    srt_backoff_cap: int = Field(60, alias="SRT_BACKOFF_CAP")
    srt_backoff_multiplier: float = Field(2.0, alias="SRT_BACKOFF_MULTIPLIER")
    srt_backoff_jitter: float = Field(0.3, alias="SRT_BACKOFF_JITTER")
    srt_once: bool = Field(False, alias="SRT_ONCE")
    srt_log_dir: Path = Field(Path("/app/runs"), alias="SRT_LOG_DIR")
    srt_log_level: str = Field("INFO", alias="SRT_LOG_LEVEL")
    srt_mode: str = Field("reserve", alias="SRT_MODE")

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    @field_validator("srt_date", mode="before")
    @classmethod
    def _parse_date(cls, value: str | date) -> date:
        if isinstance(value, date):
            return value
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except (TypeError, ValueError) as exc:
            raise ValueError("SRT_DATE must be in YYYY-MM-DD format") from exc

    @field_validator("srt_times", mode="before")
    @classmethod
    def _parse_times(cls, value: str | Iterable[str]) -> List[time]:
        if isinstance(value, str):
            entries = [item.strip() for item in value.split(",") if item.strip()]
        else:
            entries = list(value)
        if not entries:
            raise ValueError("SRT_TIMES must include at least one HH:MM entry")

        parsed: List[time] = []
        for item in entries:
            if isinstance(item, time):
                parsed.append(item)
                continue
            try:
                parsed.append(datetime.strptime(item, "%H:%M").time())
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Invalid time value: {item!r}") from exc
        return parsed

    @field_validator("srt_time_window", mode="before")
    @classmethod
    def _parse_time_window(cls, value: str | Tuple[time, time] | None) -> Optional[Tuple[time, time]]:
        if value in ("", None):
            return None
        if isinstance(value, tuple):
            return value
        parts = [part.strip() for part in str(value).split(",") if part.strip()]
        if len(parts) != 2:
            raise ValueError("SRT_TIME_WINDOW must be 'HH:MM,HH:MM'")
        try:
            start = datetime.strptime(parts[0], "%H:%M").time()
            end = datetime.strptime(parts[1], "%H:%M").time()
        except ValueError as exc:
            raise ValueError("SRT_TIME_WINDOW must be 'HH:MM,HH:MM'") from exc
        if start > end:
            raise ValueError("SRT_TIME_WINDOW start must be <= end")
        return start, end

    @field_validator("srt_headless", "srt_once", "teams_enabled", mode="before")
    @classmethod
    def _parse_bool(cls, value: str | bool | None) -> bool:
        return _boolify(value)

    @field_validator("srt_log_dir", mode="before")
    @classmethod
    def _parse_log_dir(cls, value: str | Path) -> Path:
        if isinstance(value, Path):
            return value
        return Path(str(value))

    @field_validator("srt_log_level")
    @classmethod
    def _upper_log_level(cls, value: str) -> str:
        return value.upper()

    @field_validator(
        "srt_user",
        "srt_pass",
        "srt_origin",
        "srt_dest",
        mode="after",
    )
    @classmethod
    def _require_non_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("Required configuration value must not be empty")
        return value.strip()

    @model_validator(mode="after")
    def _validate_polling(cls, values: "SRTConfig") -> "SRTConfig":
        if values.srt_poll_min <= 0:
            raise ValueError("SRT_POLL_MIN must be > 0")
        if values.srt_poll_max < values.srt_poll_min:
            raise ValueError("SRT_POLL_MAX must be >= SRT_POLL_MIN")
        if values.srt_backoff_cap <= 0:
            raise ValueError("SRT_BACKOFF_CAP must be > 0")
        if values.srt_backoff_multiplier < 1:
            raise ValueError("SRT_BACKOFF_MULTIPLIER must be >= 1")
        if not 0 <= values.srt_backoff_jitter < 1:
            raise ValueError("SRT_BACKOFF_JITTER must be in [0, 1)")
        if values.srt_mode not in {"search", "reserve"}:
            raise ValueError("SRT_MODE must be 'search' or 'reserve'")
        return values

    def is_candidate(self, candidate_time: time) -> bool:
        return utils.is_candidate(
            candidate_time,
            self.srt_times,
            self.srt_tolerance_min,
            self.srt_time_window,
        )

    @property
    def timezone(self):
        return utils.SEOUL_TZ


def load_config() -> SRTConfig:
    _load_env_files()
    data: Dict[str, str] = {key: os.environ.get(key, "") for key in os.environ}
    try:
        config = SRTConfig.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(str(exc)) from exc
    return config


__all__ = ["SRTConfig", "ConfigError", "load_config"]
