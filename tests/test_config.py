from datetime import time

import pytest

from srt_watcher.config import ConfigError, SRTConfig, load_config


REQUIRED_ENV = {
    "SRT_USER": "user1234",
    "SRT_PASS": "pass1234",
    "SRT_ORIGIN": "SUSEO",
    "SRT_DEST": "BUSAN",
    "SRT_DATE": "2025-12-24",
    "SRT_TIMES": "08:05,17:00",
    "TG_BOT_TOKEN": "token:abc",
    "TG_CHAT_ID": "12345",
}


def _apply_env(monkeypatch, env):
    for key in REQUIRED_ENV:
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)


def test_load_config_success(monkeypatch):
    _apply_env(monkeypatch, REQUIRED_ENV)
    cfg = load_config()
    assert cfg.srt_user == REQUIRED_ENV["SRT_USER"]
    assert cfg.srt_times[0] == time(8, 5)


def test_load_config_missing(monkeypatch):
    env = REQUIRED_ENV.copy()
    env.pop("SRT_PASS")
    _apply_env(monkeypatch, env)
    with pytest.raises(ConfigError):
        load_config()


def test_invalid_time(monkeypatch):
    env = REQUIRED_ENV | {"SRT_TIMES": "invalid"}
    _apply_env(monkeypatch, env)
    with pytest.raises(ConfigError):
        load_config()


def test_is_candidate(monkeypatch):
    env = REQUIRED_ENV | {"SRT_TOLERANCE_MIN": "5"}
    _apply_env(monkeypatch, env)
    cfg = load_config()
    assert cfg.is_candidate(time(8, 7))
    assert not cfg.is_candidate(time(9, 30))
