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

from .config import KoreanAirConfig, ConfigError, load_config
from .koreanair import BotGuardDetected, LoginError, SiteLayoutChanged, UserActionRequired
from .koreanair import reserve as reserve_mod
from .koreanair import search as search_mod
from .koreanair.client import KoreanAirSPAClient

LOGGER = logging.getLogger("korean_air_watcher")
_STOP = False


def _build_notifier(cfg: KoreanAirConfig) -> TeamsNotifier | None:
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
    cfg: KoreanAirConfig,
    notifier: TeamsNotifier | None = None,
    seen_flights: set[str] | None = None,
    leg: str = "out",
    force_warmup: bool = False,
) -> bool:
    """leg 별 검색 1회. 새 후보 알림 발송 시 True 반환 (해당 leg `found`)."""
    LOGGER.info("scan leg=%s force_warmup=%s %s→%s %s",
                leg, force_warmup, cfg.korean_air_origin, cfg.korean_air_dest,
                cfg.korean_air_depart_date.isoformat())
    candidates: List[Dict] = search_mod.perform_search(client, cfg, force_warmup=force_warmup)
    if not candidates:
        LOGGER.info("후보 없음 (leg=%s)", leg)
        return False

    LOGGER.info("후보 발견 (leg=%s): %d 건", leg, len(candidates))
    for i, c in enumerate(candidates[:5]):
        LOGGER.info("  [%d] %s", i, c.get("raw", "")[:200])

    if seen_flights is None:
        seen_flights = set()
    def _key(c: Dict) -> str:
        return f"{leg}/{c.get('flight_no', '')}/{c.get('cabin', '')}"
    new_candidates = [c for c in candidates if _key(c) not in seen_flights]
    if not new_candidates:
        LOGGER.info("새 후보 없음 (모두 알림 완료, leg=%s) — notify skip", leg)
        return False

    leg_label = "갈때" if leg == "out" else "올때"
    summary = "\n".join(c.get("raw", "")[:120] for c in new_candidates[:5])
    _notify(notifier,
            f"[{leg_label}] 후보 발견 ({len(new_candidates)}건)\n{summary}")
    for c in new_candidates:
        seen_flights.add(_key(c))
    LOGGER.info("seen_flights 누적: %s", sorted(seen_flights))
    return True


def main() -> int:
    global _STOP
    try:
        cfg = load_config()
    except ConfigError as e:
        print(f"Config error: {e}", file=sys.stderr)
        return 1

    logging.basicConfig(level=cfg.korean_air_log_level, format="%(asctime)s | %(message)s")
    _setup_signals()

    cfg.korean_air_log_dir.mkdir(parents=True, exist_ok=True)

    times_str = ",".join(t.strftime("%H:%M") for t in cfg.korean_air_depart_times)
    cabin_label = cfg.korean_air_cabin or "ANY"
    LOGGER.info(
        "Watcher booting: %s→%s %s times=%s cabin=%s fare=%s trip=%s mode=%s",
        cfg.korean_air_origin, cfg.korean_air_dest, cfg.korean_air_depart_date, times_str,
        cabin_label, cfg.korean_air_fare_type, cfg.korean_air_trip_type, cfg.korean_air_mode,
    )

    notifier = _build_notifier(cfg)
    _notify(notifier,
            f"✈ 부팅 {cfg.korean_air_origin}→{cfg.korean_air_dest} {cfg.korean_air_depart_date} {times_str}")

    launcher = ChromeLauncher(
        port=cfg.korean_air_cdp_port,
        user_data_dir=cfg.korean_air_cdp_user_data_dir,
        exe_path=cfg.korean_air_chrome_exe,
        startup_timeout=cfg.korean_air_cdp_startup_timeout,
    )
    try:
        cdp_url = launcher.ensure_running()
    except Exception as e:
        LOGGER.error("Chrome 디버그 기동 실패: %s", e)
        return 1

    try:
        with KoreanAirSPAClient(cdp_url) as client:
            # 로그인 필수 — search/reserve 모두 KE 세션이 있는 상태에서 동작한다.
            # 익명 진행은 지원하지 않음 (skill 워크플로우 2단계와 일치).
            try:
                reserve_mod.ensure_logged_in(client, cfg)
            except LoginError as e:
                LOGGER.error("로그인 실패: %s", e)
                _notify(notifier, f"❌ KE 로그인 실패\n{e}")
                return 1

            # 위젯 워밍업 — Akamai 가 /booking/select-flight 직접 진입을 차단하므로
            # 홈 위젯 클릭 경로로 한 번 들어가 줘야 air-bounds XHR 가 200 을 준다.
            # roundtrip 은 워처 내부에서 outbound/return 두 oneway 검색으로 처리하므로
            # warm-up 도 oneway view 로 호출.
            warmup_cfg = cfg.as_oneway_outbound()
            try:
                reserve_mod.warm_up_select_flight(client, warmup_cfg)
            except NotImplementedError as e:
                LOGGER.error("warm-up 미지원: %s", e)
                _notify(notifier, f"❌ warm-up 미지원\n{e}")
                return 1
            except LoginError as e:
                LOGGER.warning(
                    "초기 warm-up 실패 (%s) — main loop 에서 재시도", e
                )

            # 좌석은 풀렸다 닫혔다 반복하므로 한 번 잡았다고 끝낼 일이 아니다.
            # 양쪽 leg 매 iteration 모두 폴링. 중복 알림은 seen_flights dedup 으로 차단.
            # 종료는 오직 사용자 신호(SIGINT) — KOREAN_AIR_ONCE 는 검증/디버그 전용.
            seen_flights: set[str] = set()
            is_roundtrip = (cfg.korean_air_trip_type == "roundtrip"
                            and cfg.korean_air_return_date is not None)
            last_leg: str | None = None
            any_found = False
            while not _STOP:
                try:
                    # ── outbound (갈때) ──
                    out_cfg = cfg.as_oneway_outbound()
                    force = (last_leg == "return")
                    if run_once(client, out_cfg, notifier, seen_flights,
                                 leg="out", force_warmup=force):
                        any_found = True
                    last_leg = "out"

                    # ── return (올때) ──
                    if is_roundtrip:
                        ret_cfg = cfg.swap_for_return()
                        force = (last_leg == "out")  # leg 전환 → 위젯 재셋업
                        if run_once(client, ret_cfg, notifier, seen_flights,
                                     leg="return", force_warmup=force):
                            any_found = True
                        last_leg = "return"

                    if cfg.korean_air_once:
                        LOGGER.info("KOREAN_AIR_ONCE=true → 1회만 실행 후 종료 (debug)")
                        return 0 if any_found else 1
                    _sleep_with_jitter(float(cfg.korean_air_poll_min), float(cfg.korean_air_poll_max))
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
