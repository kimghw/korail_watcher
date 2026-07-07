"""chrome_binding.py — 크롬 바인딩 SSOT(chrome_binding.yaml) 로더 (스킬 chrome-bind 연동부).

자동화 러너는 포트/프로필을 하드코딩하지 않고 resolve(channel) 로 얻는다.

  from krs_watcher.chrome_binding import resolve
  b = resolve("krs")   # {"port", "user_data_dir", "shortcut", "account", "source"}

바인딩 파일 위치: .claude/skills/chrome-bind/chrome_binding.yaml (구위치 <루트>/chrome_binding.yaml 폴백).
파일이 없으면 기존 하드코딩과 동일한 폴백(krs=9333 · KRS_ECLASS_CACHE/krs_chrome_profile) — 하위호환.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_SKILL_BINDING = ROOT / ".claude" / "skills" / "chrome-bind" / "chrome_binding.yaml"
_LEGACY_BINDING = ROOT / "chrome_binding.yaml"
BINDING_FILE = _SKILL_BINDING if _SKILL_BINDING.exists() or not _LEGACY_BINDING.exists() else _LEGACY_BINDING

FALLBACKS = {
    "krs": {
        "port": 9333,
        "user_data_dir": str(ROOT / "KRS_ECLASS_CACHE" / "krs_chrome_profile"),
    },
    "second": {
        "port": 9555,
        "user_data_dir": str(ROOT / "KRS_ECLASS_CACHE" / "krs_chrome_profile_2nd"),
    },
}


def _load_channels() -> dict:
    if not BINDING_FILE.exists():
        return {}
    import yaml
    data = yaml.safe_load(BINDING_FILE.read_text(encoding="utf-8")) or {}
    return data.get("channels") or {}


def resolve(channel: str = "krs") -> dict:
    """채널의 바인딩값 반환. 바인딩 파일에 없으면 FALLBACKS — 러너 하위호환."""
    b = _load_channels().get(channel)
    if b and b.get("port") and b.get("user_data_dir"):
        return {
            "port": int(b["port"]),
            "user_data_dir": str(b["user_data_dir"]),
            "shortcut": b.get("shortcut"),
            "account": b.get("account"),
            "source": "binding",
        }
    fb = FALLBACKS.get(channel, FALLBACKS["krs"])
    return {**fb, "shortcut": None, "account": None, "source": "fallback"}
