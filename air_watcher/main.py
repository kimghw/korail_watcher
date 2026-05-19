"""Korean Air (KE) watcher main loop (CDP-only).

ktx_watcher.main 과 동일한 구조. ChromeLauncher / TeamsNotifier 는 ktx_watcher 의
구현을 재사용한다 (재구현 가치 없음).
"""

from __future__ import annotations

import logging
import random
import signal
import sys
import time
from typing import Dict, List

from ktx_watcher.chrome_launcher import ChromeLauncher
from ktx_watcher.notifier.teams import TeamsNotifier

from .config import AirConfig, ConfigError, load_config
from .koreanair import BotGuardDetected, LoginError, SiteLayoutChanged, UserActionRequired
from .koreanair import reserve as reserve_mod
from .koreanair import search as search_mod
from .koreanair.client import KoreanAirSPAClient

LOGGER = logging.getLogger("air_watcher")
_STOP = False


def _build_notifier(cfg: AirConfig) -> TeamsNotifier | None:
    if not cfg.teams_enabled:
        LOGGER.info("Teams notifier disabled (TEAMS_ENABLED=false)")
        return None
    return TeamsNotifier(
        user_email=cfg.teams_user_email,
        chat_id=cfg.teams_chat_id,
        recipient_name=cfg.teams_recipient_name,
        prefix=cfg.teams_prefix,
    )


def _notify(notifier: TeamsNotifier | None, msg: str) -> None:
    if not notifier:
        return
    try:
        notifier.notify(msg)
    except Exception as e:
        LOGGER.warning("Teams notify 실패: %s", e)


def _on_signal(signum, frame):
    global _STOP
    LOGGER.info("Signal %s received → stop", signum)
    _STOP = True


def _setup_signals() -> None:
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _on_signal)
        except Exception:
            pass


def _sleep_with_jitter(min_s: float, max_s: float) -> None:
    if max_s < min_s:
        max_s = min_s
    delay = min_s + random.uniform(0, max(0.0, max_s - min_s))
    LOGGER.info("다음 검색까지 %.2fs 대기", delay)
    time.sleep(delay)


def run_once(
    client: KoreanAirSPAClient,
    cfg: AirConfig,
    notifier: TeamsNotifier | None = None,
) -> bool:
    """Return True 면 main loop 종료."""
    candidates: List[Dict] = search_mod.perform_search(client, cfg)
    if not candidates:
        LOGGER.info("후보 없음. 다음 iteration 진행")
        return False

    LOGGER.info("후보 발견: %d 건", len(candidates))
    for i, c in enumerate(candidates[:5]):
        LOGGER.info("  [%d] %s", i, c.get("raw", "")[:200])

    summary = "\n".join(c.get("raw", "")[:120] for c in candidates[:5])
    _notify(notifier, f"후보 발견 ({len(candidates)}건)\n{summary}")

    if cfg.air_mode == "search":
        LOGGER.info("MODE=search — 예약 시도 안 함")
        return False

    # MODE=reserve — 현재 미구현 (NotImplementedError 던짐)
    best = candidates[0]
    try:
        reserve_mod.attempt_reservation(client, cfg, best)
        LOGGER.info("✅ 좌석 hold 통과")
        _notify(notifier, "✅ 좌석 hold 통과 — 10분 안에 수동 결제")
        return True
    except NotImplementedError as e:
        LOGGER.error("reserve 미구현: %s", e)
        _notify(notifier, f"⚠ 예약 자동화 미구현 — search 모드로 사용하세요\n{e}")
        return True
    except BotGuardDetected as e:
        LOGGER.warning("BotGuard: %s — backoff", e)
        _notify(notifier, f"⚠ 봇 가드 감지 — 다음 iteration 재시도\n{e}")
        return False
    except UserActionRequired as e:
        LOGGER.error("user action required: %s", e)
        _notify(notifier, f"❌ 예약 단계 사용자 개입 필요\n{e}")
        return True
    except SiteLayoutChanged as e:
        LOGGER.error("layout changed: %s", e)
        _notify(notifier, f"❌ 사이트 구조 변경\n{e}")
        return True
    except LoginError as e:
        LOGGER.error("login error: %s", e)
        _notify(notifier, f"❌ 로그인 오류\n{e}")
        return True


def main() -> int:
    global _STOP
    try:
        cfg = load_config()
    except ConfigError as e:
        print(f"Config error: {e}", file=sys.stderr)
        return 1

    logging.basicConfig(level=cfg.air_log_level, format="%(asctime)s | %(message)s")
    _setup_signals()

    cfg.air_log_dir.mkdir(parents=True, exist_ok=True)

    times_str = ",".join(t.strftime("%H:%M") for t in cfg.air_depart_times)
    cabin_label = cfg.air_cabin or "ANY"
    LOGGER.info(
        "Watcher booting: %s→%s %s times=%s cabin=%s fare=%s trip=%s mode=%s",
        cfg.air_origin, cfg.air_dest, cfg.air_depart_date, times_str,
        cabin_label, cfg.air_fare_type, cfg.air_trip_type, cfg.air_mode,
    )

    notifier = _build_notifier(cfg)
    _notify(
        notifier,
        f"✈ KE 워처 부팅\n{cfg.air_origin}→{cfg.air_dest} {cfg.air_depart_date} "
        f"times={times_str} cabin={cabin_label} fare={cfg.air_fare_type} "
        f"trip={cfg.air_trip_type} mode={cfg.air_mode}",
    )

    launcher = ChromeLauncher(
        port=cfg.air_cdp_port,
        user_data_dir=cfg.air_cdp_user_data_dir,
        exe_path=cfg.air_chrome_exe,
        startup_timeout=cfg.air_cdp_startup_timeout,
    )
    try:
        cdp_url = launcher.ensure_running()
    except Exception as e:
        LOGGER.error("Chrome 디버그 기동 실패: %s", e)
        return 1

    try:
        with KoreanAirSPAClient(cdp_url) as client:
            # 로그인은 search/reserve 모두 필요 — air-bounds API 가 익명이면 403.
            try:
                reserve_mod.ensure_logged_in(client, cfg)
            except LoginError as e:
                LOGGER.error("로그인 실패: %s", e)
                _notify(notifier, f"❌ KE 로그인 실패\n{e}")
                return 1

            # 위젯 워밍업 — Akamai 가 /booking/select-flight 직접 진입을 차단하므로
            # 홈 위젯 클릭 경로로 한 번 들어가 줘야 air-bounds XHR 가 200 을 준다.
            try:
                reserve_mod.warm_up_select_flight(client, cfg)
            except NotImplementedError as e:
                LOGGER.error("warm-up 미지원: %s", e)
                _notify(notifier, f"❌ warm-up 미지원\n{e}")
                return 1
            except LoginError as e:
                LOGGER.error("warm-up 실패: %s", e)
                _notify(notifier, f"❌ select-flight warm-up 실패\n{e}")
                return 1

            while not _STOP:
                try:
                    done = run_once(client, cfg, notifier)
                    if done:
                        return 0
                    if cfg.air_once:
                        LOGGER.info("AIR_ONCE=true → 종료")
                        return 1
                    _sleep_with_jitter(float(cfg.air_poll_min), float(cfg.air_poll_max))
                except BotGuardDetected as e:
                    LOGGER.warning("BotGuard: %s — backoff", e)
                    _sleep_with_jitter(15.0, 45.0)
                except SiteLayoutChanged as e:
                    LOGGER.error("Site layout changed: %s", e)
                    return 1
                except Exception as e:
                    LOGGER.warning(
                        "iteration 일시 예외 (%s: %s) — backoff 후 재시도",
                        type(e).__name__, e,
                    )
                    _sleep_with_jitter(10.0, 25.0)
    finally:
        launcher.shutdown_if_owned()

    LOGGER.info("Watcher stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
