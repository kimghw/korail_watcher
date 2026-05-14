"""KTX-A watcher main loop (CDP-only)."""

from __future__ import annotations

import logging
import random
import signal
import sys
import time
from typing import Dict, List

from .chrome_launcher import ChromeLauncher
from .config import ConfigError, KTXAConfig, load_config
from .korail import CaptchaDetected, LoginError, SiteLayoutChanged, UserActionRequired
from .korail import payment as payment_mod
from .korail import reserve as reserve_mod
from .korail import search as search_mod
from .korail.client import KorailSPAClient
from .notifier.teams import TeamsNotifier

LOGGER = logging.getLogger("ktx_watcher_spa")
_STOP = False


def _build_teams_notifier(config: KTXAConfig) -> TeamsNotifier | None:
    if not getattr(config, "teams_enabled", False):
        LOGGER.info("Teams notifier disabled (TEAMS_ENABLED=false)")
        return None
    return TeamsNotifier(
        user_email=getattr(config, "teams_user_email", None),
        chat_id=getattr(config, "teams_chat_id", None),
        recipient_name=getattr(config, "teams_recipient_name", None),
        prefix=getattr(config, "teams_prefix", "[KTX-A WATCHER]"),
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
    client: KorailSPAClient,
    config: KTXAConfig,
    notifier: TeamsNotifier | None = None,
) -> bool:
    """Return True 면 main loop 종료."""
    candidates: List[Dict] = search_mod.perform_search(client, config)
    if not candidates:
        LOGGER.info("후보 없음 (-8002 dismiss 됐을 수 있음). 다음 iteration 진행")
        return False

    best = candidates[0]
    info_line = (
        f"{best['origin']}→{best['dest']} {best['date']} {best['depart']} "
        f"[{best['seat_class']}] {best['status']}"
    )
    LOGGER.info("후보 발견: %s", info_line)
    _notify(notifier, f"후보 발견\n{info_line}")

    if config.ktxa_mode == "search":
        LOGGER.info("MODE=search — 예약 시도 안 함")
        return False

    # MODE=reserve — 예약 단계 통과 후 (KTXA_PAYMENT_MODE=true 면) 결제까지 연속
    try:
        reserve_mod.attempt_reservation(client, config, best)
        LOGGER.info("✅ 예약 단계 통과 (좌석 hold)")
        _notify(notifier, f"✅ 예약 성공 (좌석 hold)\n{info_line}")
    except CaptchaDetected as e:
        LOGGER.warning("Captcha during reservation: %s", e)
        _notify(notifier, f"⚠ 캡차/대기열 감지 — 다음 iteration 재시도\n{e}")
        return False
    except UserActionRequired as e:
        LOGGER.error("User action required during reservation: %s", e)
        _notify(notifier, f"❌ 예약 단계 사용자 개입 필요\n{e}")
        return True
    except SiteLayoutChanged as e:
        LOGGER.error("Site layout changed during reservation: %s", e)
        _notify(notifier, f"❌ 사이트 구조 변경 감지 (예약 단계)\n{e}")
        return True
    except LoginError as e:
        LOGGER.error("Login error during reservation: %s", e)
        _notify(notifier, f"❌ 로그인 오류 (예약 단계)\n{e}")
        return True

    # 예약 단계 OK — 결제까지 연속 진행 (config 가 허용한 경우만)
    if not config.ktxa_payment_mode:
        LOGGER.info("KTXA_PAYMENT_MODE=false — 결제 단계 skip, 예약만 hold 상태")
        _notify(notifier, "ℹ KTXA_PAYMENT_MODE=false — 결제는 수동으로 진행하세요 (10분 timer)")
        return True

    try:
        payment_mod.perform_payment(client, config)
        LOGGER.info("✅✅ 결제/발권 완료")
        _notify(notifier, f"✅✅ 결제/발권 완료\n{info_line}")
        return True
    except UserActionRequired as e:
        LOGGER.error("결제 단계에서 사용자 개입 필요: %s", e)
        _notify(notifier, f"❌ 결제 단계 사용자 개입 필요\n{e}")
        return True
    except SiteLayoutChanged as e:
        LOGGER.error("결제 단계 site layout: %s", e)
        _notify(notifier, f"❌ 결제 단계 사이트 구조 변경\n{e}")
        return True
    except ValueError as e:
        # 카드 config 오류
        LOGGER.error("결제 config 오류: %s", e)
        _notify(notifier, f"❌ 결제 config 오류 (.env PAY_* 확인)\n{e}")
        return True


def main() -> int:
    global _STOP
    try:
        config = load_config()
    except ConfigError as e:
        print(f"Config error: {e}", file=sys.stderr)
        return 1

    logging.basicConfig(level=config.ktxa_log_level, format="%(asctime)s | %(message)s")
    _setup_signals()

    config.ktxa_log_dir.mkdir(parents=True, exist_ok=True)

    times_str = ",".join(t.strftime("%H:%M") for t in config.ktxa_times)
    LOGGER.info(
        "Watcher booting: %s→%s on %s times=%s seat=%s train=%s mode=%s",
        config.ktxa_origin, config.ktxa_dest, config.ktxa_date, times_str,
        config.ktxa_seat_class, config.ktxa_train_type, config.ktxa_mode,
    )

    notifier = _build_teams_notifier(config)
    _notify(
        notifier,
        f"🚄 KTX 워처 부팅\n{config.ktxa_origin}→{config.ktxa_dest} {config.ktxa_date} "
        f"times={times_str} seat={config.ktxa_seat_class} mode={config.ktxa_mode} "
        f"payment={'on' if config.ktxa_payment_mode else 'off'}",
    )

    # 1) Chrome 디버그 인스턴스 확보
    launcher = ChromeLauncher(
        port=config.ktxa_cdp_port,
        user_data_dir=config.ktxa_cdp_user_data_dir,
        exe_path=config.ktxa_chrome_exe,
        startup_timeout=config.ktxa_cdp_startup_timeout,
    )
    try:
        cdp_url = launcher.ensure_running()
    except Exception as e:
        LOGGER.error("Chrome 디버그 기동 실패: %s", e)
        return 1

    # 2) Korail SPA 클라이언트
    try:
        with KorailSPAClient(cdp_url) as client:
            if config.ktxa_mode == "reserve":
                try:
                    reserve_mod.ensure_logged_in(client, config)
                except LoginError as e:
                    LOGGER.error("로그인 실패: %s", e)
                    return 1

            while not _STOP:
                try:
                    done = run_once(client, config, notifier)
                    if done:
                        return 0
                    if config.ktxa_once:
                        LOGGER.info("KTXA_ONCE=true → 종료")
                        return 1
                    _sleep_with_jitter(
                        float(config.ktxa_poll_min),
                        float(config.ktxa_poll_max),
                    )
                except CaptchaDetected as e:
                    LOGGER.warning("Captcha: %s — backoff", e)
                    _sleep_with_jitter(5.0, 12.0)
                except SiteLayoutChanged as e:
                    LOGGER.error("Site layout changed: %s", e)
                    return 1
    finally:
        launcher.shutdown_if_owned()

    LOGGER.info("Watcher stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
