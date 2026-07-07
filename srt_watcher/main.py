from __future__ import annotations

import logging
import os
import random
import signal
import sys
import time
from pathlib import Path
from typing import Dict, List

from srt_watcher.config import SRTConfig, load_config, ConfigError
from srt_watcher.srt.client import SRTClient
from srt_watcher.srt import search, reserve
from srt_watcher.srt import CaptchaDetected, SiteLayoutChanged
# ⬇️ 결제 모듈 추가
from srt_watcher.srt.payment import perform_payment, payment_enabled

# Microsoft Teams Notifier (team_mcp 사용)
from .notifier.teams import TeamsNotifier

LOGGER = logging.getLogger("srt_watcher")
STOP_EVENT = False

# ========== Signal Handling ==========

def _handle_signal(signum, frame):
    global STOP_EVENT
    LOGGER.info("Signal %s received. Stopping...", signum)
    STOP_EVENT = True

def _setup_signals():
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _handle_signal)
        except Exception:
            # 일부 환경(docker on windows 등)에서 실패 가능
            pass

# ========== Teams Notifier ==========

def build_teams_notifier(config: SRTConfig) -> TeamsNotifier | None:
    if not getattr(config, "teams_enabled", False):
        LOGGER.info("Teams notifier disabled (TEAMS_ENABLED=false).")
        return None
    return TeamsNotifier(
        user_email=getattr(config, "teams_user_email", None),
        chat_id=getattr(config, "teams_chat_id", None),
        recipient_name=getattr(config, "teams_recipient_name", None),
        prefix=getattr(config, "teams_prefix", "[binjari SRT]"),
    )

# ========== Sleep / Backoff ==========

def _sleep_with_jitter(base_seconds: float, max_seconds: float) -> None:
    if max_seconds < base_seconds:
        max_seconds = base_seconds
    delay = min(max_seconds, base_seconds + random.uniform(0, base_seconds))
    LOGGER.info("Waiting %.2f seconds before next search (human-like delay)", delay)
    time.sleep(delay)

# ========== Core Loop Helpers ==========

def run_once(
    client: SRTClient,
    config: SRTConfig,
    artifact_root: Path,
    notifier: TeamsNotifier | None,
) -> bool:
    """
    단일 iteration 수행.

    반환값:
      - True  : 성공(예약만 or 결제까지) → 루프 종료
      - False : 다음 iteration 계속 시도
    """
    global STOP_EVENT

    mode = config.srt_mode  # 'search' or 'reserve'

    # 1) 검색
    candidates: List[Dict] = search.perform_search(
        client=client,
        config=config,
        artifact_root=artifact_root,
    )

    if not candidates:
        LOGGER.info("No viable options found in this iteration.")
        return False

    LOGGER.info("Found %d viable options", len(candidates))

    # 2) 최적 후보 (search.py에서 score 정렬된 상태라고 가정)
    best = candidates[0]
    base_msg = (
        f"{best['date']} {best['origin']}→{best['dest']}\n"
        f"출발 {best['depart']} / {best['seat_class']} / {best['status']}"
    )

    # 후보 발견 알림
    if notifier:
        notifier.notify(f"[binjari SRT]\n후보 발견:\n{base_msg}")

    # MODE=search 이면 여기서 종료 (watcher는 계속 돈다)
    if mode == "search":
        LOGGER.info("MODE=search; skipping reservation attempt.")
        return False

    # 3) MODE=reserve: 예약 시도
    try:
        reserve.attempt_reservation(
            client=client,
            config=config,
            target=best,
            artifact_root=artifact_root,
        )
        # 예외 없이 왔다 = 예약 성공
        LOGGER.info("예약 성공!")
        if notifier:
            notifier.notify(f"[binjari SRT]\n✅ 예약 성공!\n{base_msg}")

        # ⬇️ 결제 모드면 결제까지 진행
        if payment_enabled(config):
            try:
                page = client.context.pages[-1]
            except Exception:
                page = None
            if not page:
                raise RuntimeError("No active page available for payment step")

            perform_payment(page, cfg=config)

            LOGGER.info("결제 성공!")
            if notifier:
                notifier.notify(f"[binjari SRT]\n💳 결제 성공!\n{base_msg}")

        # 결제 비활성화면 예약 성공 시점에서 종료 / 활성화면 결제 성공 후 종료
        STOP_EVENT = True
        return True

    except CaptchaDetected as e:
        LOGGER.warning("Captcha / Queue detected during reservation: %s", e)
        if notifier:
            notifier.notify("[binjari SRT]\n캡차/대기열 감지됨. 잠시 후 자동 재시도합니다.")
        _sleep_with_jitter(base_seconds=float(config.srt_poll_min), max_seconds=float(config.srt_poll_max))
        return False

    except SiteLayoutChanged as e:
        LOGGER.error("Site layout changed during reservation: %s", e)
        if notifier:
            notifier.notify("[binjari SRT]\n❌ SRT 사이트 구조 변경 감지. selectors.py / reserve.py / search.py 점검 필요.")
        # 사이트 구조 변경은 즉시 종료(외부 업데이트 필요)
        STOP_EVENT = True
        return True

    except Exception as e:
        LOGGER.error("Unhandled reservation/payment error: %s", e, exc_info=True)
        if notifier:
            notifier.notify("[binjari SRT]\n❌ 예약/결제 단계 에러. artifacts를 확인하세요.")
        # 정책상: 다음 루프에서 다시 시도
        return False

# ========== Main ==========

def main() -> int:
    """
    Main loop.

    Design goals:
    - Keep a single Playwright browser context alive for many search iterations (avoid re-login every poll).
    - Re-check / re-ensure login only periodically (N iterations) or on demand (errors/redirects handled by reserve.ensure_logged_in).
    - Restart the whole browser session only on captcha/layout/fatal errors.
    """
    global STOP_EVENT

    # 1) 설정 로드 (.env -> SRTConfig)
    try:
        config = load_config()
    except ConfigError as e:
        print(f"Config error: {e}", file=sys.stderr)
        return 1

    # 2) 로깅 설정
    log_level = getattr(config, "srt_log_level", "INFO")
    logging.basicConfig(level=log_level, format="%(asctime)s | %(message)s")

    _setup_signals()

    # 아티팩트 루트
    artifact_root = (config.srt_log_dir / "artifacts").resolve()
    artifact_root.mkdir(parents=True, exist_ok=True)

    notifier = build_teams_notifier(config)

    times_str = ",".join(t.strftime("%H:%M") for t in config.srt_times)
    LOGGER.info(
        "Watcher booting: %s→%s on %s times=%s passengers=%s mode=%s headless=%s payment=%s",
        config.srt_origin, config.srt_dest, config.srt_date, times_str,
        config.srt_passengers, config.srt_mode, config.srt_headless,
        "on" if payment_enabled(config) else "off",
    )

    # ====== 단일 while 루프 (한 번에 한 사이클) ======
    backoff = 5  # seconds
    backoff_max = 60

    while not STOP_EVENT:
        try:
            with SRTClient(headless=config.srt_headless) as client:
                LOGGER.info("Playwright client ready.")

                # Reset backoff after a successful session start
                backoff = 5

                while not STOP_EVENT:
                    if config.srt_mode == "reserve":
                        reserve.ensure_logged_in(client, config, artifact_root)
                    
                    # One search/reserve/payment attempt
                    should_stop = run_once(client, config, artifact_root, notifier)
                    if should_stop:
                        LOGGER.info("Watcher exited cleanly after success.")
                        return 0

                    # One-shot mode: exit after first attempt regardless of outcome
                    if getattr(config, "srt_once", False):
                        LOGGER.info("SRT_ONCE set; single attempt done (no success). Exiting.")
                        return 1

                    # Human-like polling delay
                    _sleep_with_jitter(
                        base_seconds=float(config.srt_poll_min),
                        max_seconds=float(config.srt_poll_max),
                    )

        except SiteLayoutChanged as e:
            LOGGER.error("Site layout changed at top-level: %s", e)
            if notifier:
                notifier.notify("[binjari SRT]\n❌ SRT 사이트 구조 변경 감지. 코드 업데이트 필요.")
            return 1  # 구조 변경은 수동 조치 필요 → 종료

        except CaptchaDetected as e:
            LOGGER.error("Captcha / Queue detected at top-level: %s", e)
            if notifier:
                notifier.notify("[binjari SRT]\n❌ 초기 접속 시 캡차/대기열 감지. 자동 재시작합니다.")
            delay = min(backoff, backoff_max) + random.uniform(0, 2)
            LOGGER.info("Retrying from scratch after %.2fs (top-level captcha)", delay)
            time.sleep(delay)
            backoff = min(int(backoff * 1.5), backoff_max)
            continue

        except Exception as e:
            LOGGER.error("Unhandled fatal error at top-level (will restart): %s", e, exc_info=True)
            if notifier:
                try:
                    notifier.notify("[binjari SRT]\n❌ 식별 되지 않은 오류 발생. 재시작합니다.")
                except Exception:
                    pass
            delay = min(backoff, backoff_max) + random.uniform(0, 2)
            LOGGER.info("Retrying from scratch after %.2fs (top-level error)", delay)
            time.sleep(delay)
            backoff = min(int(backoff * 1.5), backoff_max)
            continue

    LOGGER.info("Watcher stopped by signal.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
