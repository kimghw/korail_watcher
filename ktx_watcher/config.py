"""KTX-A watcher config (CDP-only)."""

from __future__ import annotations

import os
from datetime import date, datetime, time
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


ENV_FILES = (Path(".env.ktx"), Path("env") / ".env", Path(".env"))


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


class KTXAConfig(BaseModel):
    """CDP-only Korail watcher 설정."""

    # ─ Required (CDP 강제) ─
    ktxa_cdp_port: int = Field(9222, alias="KTXA_CDP_PORT")
    ktxa_chrome_exe: Optional[str] = Field(None, alias="KTXA_CHROME_EXE")
    ktxa_cdp_user_data_dir: Optional[str] = Field(
        None, alias="KTXA_CDP_USER_DATA_DIR"
    )
    ktxa_cdp_startup_timeout: float = Field(15.0, alias="KTXA_CDP_STARTUP_TIMEOUT")

    # ─ Trip ─
    ktxa_origin: str = Field(alias="KTXA_ORIGIN")
    ktxa_dest: str = Field(alias="KTXA_DEST")
    ktxa_date: date = Field(alias="KTXA_DATE")
    ktxa_times: List[time] = Field(alias="KTXA_TIMES")
    ktxa_passengers: int = Field(1, alias="KTXA_PASSENGERS")
    ktxa_seat_class: str = Field("", alias="KTXA_SEAT_CLASS")
    ktxa_train_type: str = Field("KTX", alias="KTXA_TRAIN_TYPE")
    ktxa_tolerance_min: int = Field(0, alias="KTXA_TOLERANCE_MIN")
    ktxa_time_window: Optional[Tuple[time, time]] = Field(
        None, alias="KTXA_TIME_WINDOW"
    )

    # ─ Credentials (reserve 모드에서만 필수) ─
    ktxa_user: str = Field("", alias="KTXA_USER")
    ktxa_pass: str = Field("", alias="KTXA_PASS")

    # ─ Polling ─
    ktxa_poll_min: int = Field(3, alias="KTXA_POLL_MIN")
    ktxa_poll_max: int = Field(10, alias="KTXA_POLL_MAX")
    ktxa_once: bool = Field(False, alias="KTXA_ONCE")

    # ─ Misc ─
    ktxa_mode: str = Field("search", alias="KTXA_MODE")
    ktxa_log_dir: Path = Field(Path("./runs"), alias="KTXA_LOG_DIR")
    ktxa_log_level: str = Field("INFO", alias="KTXA_LOG_LEVEL")

    # ─ Payment (reserve mode 끝나면 자동 결제까지) ─
    # KTXA_PAYMENT_MODE=true 면 결제 페이지에서 카드 정보 입력 + 결제/발권 클릭까지.
    # 카드 정보는 .env 의 PAY_* 변수 (SRT 와 공유).
    ktxa_payment_mode: bool = Field(False, alias="KTXA_PAYMENT_MODE")
    pay_card_num: str = Field("", alias="PAY_CARD_NUM")
    pay_card_mm: str = Field("", alias="PAY_CARD_MM")
    pay_card_yy: str = Field("", alias="PAY_CARD_YY")
    pay_card_pw2: str = Field("", alias="PAY_CARD_PW2")
    pay_id6: str = Field("", alias="PAY_ID6")

    # ─ Notifier (선택) ─
    teams_enabled: bool = Field(False, alias="TEAMS_ENABLED")
    teams_user_email: Optional[str] = Field(None, alias="TEAMS_USER_EMAIL")
    teams_chat_id: Optional[str] = Field(None, alias="TEAMS_CHAT_ID")
    teams_recipient_name: Optional[str] = Field(None, alias="TEAMS_RECIPIENT_NAME")
    teams_prefix: str = Field("[KTX-A WATCHER]", alias="TEAMS_PREFIX")

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    # ─ validators ─
    @field_validator("ktxa_date", mode="before")
    @classmethod
    def _parse_date(cls, v):
        if isinstance(v, date):
            return v
        try:
            return datetime.strptime(v, "%Y-%m-%d").date()
        except (TypeError, ValueError) as e:
            raise ValueError("KTXA_DATE must be YYYY-MM-DD") from e

    @field_validator("ktxa_times", mode="before")
    @classmethod
    def _parse_times(cls, v):
        if isinstance(v, str):
            entries = [x.strip() for x in v.split(",") if x.strip()]
        else:
            entries = list(v or [])
        if not entries:
            raise ValueError("KTXA_TIMES must include at least one HH:MM")
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

    @field_validator("ktxa_time_window", mode="before")
    @classmethod
    def _parse_window(cls, v):
        if v in ("", None):
            return None
        if isinstance(v, tuple):
            return v
        parts = [p.strip() for p in str(v).split(",") if p.strip()]
        if len(parts) != 2:
            raise ValueError("KTXA_TIME_WINDOW must be 'HH:MM,HH:MM'")
        try:
            s = datetime.strptime(parts[0], "%H:%M").time()
            e = datetime.strptime(parts[1], "%H:%M").time()
        except Exception as exc:
            raise ValueError("invalid KTXA_TIME_WINDOW") from exc
        if s > e:
            raise ValueError("KTXA_TIME_WINDOW start must be <= end")
        return s, e

    @field_validator("ktxa_once", "teams_enabled", "ktxa_payment_mode", mode="before")
    @classmethod
    def _parse_bool(cls, v):
        return _boolify(v)

    @field_validator("ktxa_log_dir", mode="before")
    @classmethod
    def _parse_log_dir(cls, v):
        return v if isinstance(v, Path) else Path(str(v))

    @field_validator("ktxa_log_level")
    @classmethod
    def _upper(cls, v):
        return v.upper()

    @field_validator("ktxa_origin", "ktxa_dest", "ktxa_train_type", mode="after")
    @classmethod
    def _non_empty(cls, v):
        if not v or not v.strip():
            raise ValueError("required value cannot be empty")
        return v.strip()

    @field_validator("ktxa_seat_class", mode="after")
    @classmethod
    def _seat_class_opt(cls, v):
        return (v or "").strip()

    @field_validator("ktxa_user", "ktxa_pass", mode="after")
    @classmethod
    def _strip_opt(cls, v):
        return (v or "").strip()

    @model_validator(mode="after")
    def _final(cls, values: "KTXAConfig"):
        if values.ktxa_poll_min <= 0:
            raise ValueError("KTXA_POLL_MIN must be > 0")
        if values.ktxa_poll_max < values.ktxa_poll_min:
            raise ValueError("KTXA_POLL_MAX must be >= KTXA_POLL_MIN")
        if values.ktxa_cdp_port <= 0 or values.ktxa_cdp_port > 65535:
            raise ValueError("KTXA_CDP_PORT out of range")
        if values.ktxa_mode not in {"search", "reserve"}:
            raise ValueError("KTXA_MODE must be 'search' or 'reserve'")
        if values.ktxa_mode == "reserve":
            if not values.ktxa_user:
                raise ValueError("KTXA_USER required for reserve mode")
            if not values.ktxa_pass:
                raise ValueError("KTXA_PASS required for reserve mode")
        return values


_RAIL_SHARED_MAP = (
    ("RAIL_ORIGIN", "KTXA_ORIGIN"),
    ("RAIL_DEST", "KTXA_DEST"),
    ("RAIL_DATE", "KTXA_DATE"),
    ("RAIL_TIMES", "KTXA_TIMES"),
    ("RAIL_TIME_WINDOW", "KTXA_TIME_WINDOW"),
    ("RAIL_PASSENGERS", "KTXA_PASSENGERS"),
    ("RAIL_SEAT_CLASS", "KTXA_SEAT_CLASS"),
    ("RAIL_TOLERANCE_MIN", "KTXA_TOLERANCE_MIN"),
)


def _apply_rail_fallback(data: dict) -> None:
    """RAIL_* 공통 키가 있고 KTXA_* 가 비어 있으면 RAIL 값으로 채운다."""
    for shared, specific in _RAIL_SHARED_MAP:
        if not (data.get(specific) or "").strip() and (data.get(shared) or "").strip():
            data[specific] = data[shared]


def load_config() -> KTXAConfig:
    _load_env_files()
    data = {k: os.environ.get(k, "") for k in os.environ}
    _apply_rail_fallback(data)
    try:
        return KTXAConfig.model_validate(data)
    except ValidationError as e:
        raise ConfigError(str(e)) from e


__all__ = ["KTXAConfig", "ConfigError", "load_config"]
