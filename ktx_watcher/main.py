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
from .korail import CaptchaDetected, LoginError, ReservationFailed, SiteLayoutChanged, UserActionRequired
from .korail import payment as payment_mod
from .korail import reserve as reserve_mod
from .korail import search as search_mod
from .korail import transfer as transfer_mod
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
        prefix=getattr(config, "teams_prefix", "[binjari KTX]"),
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


def _maybe_transfer(
    client: KorailSPAClient,
    config: KTXAConfig,
    notifier: TeamsNotifier | None,
) -> None:
    """발권 후 승차권 전달 (KTXA_TRANSFER_ENABLED=true 일 때). 실패해도 발권 결과는 유지."""
    if not config.ktxa_transfer_enabled:
        return
    try:
        result = transfer_mod.perform_transfer(client, config)
        if result == "sent":
            _notify(notifier, f"✅ 승차권 전달 완료 → {config.ktxa_transfer_name}")
        else:
            LOGGER.info("승차권 전달 dry-run 완료 (전송 안 함)")
            _notify(notifier, "ℹ 승차권 전달 dry-run — 입력까지 확인, 전송은 KTXA_TRANSFER_SEND=true 필요")
    except Exception as e:
        LOGGER.error("승차권 전달 실패 (%s: %s) — 발권은 완료 상태", type(e).__name__, e)
        _notify(notifier, f"⚠ 승차권 전달 실패 — 수동 전달 필요\n{e}")


# SRT 빈자리 알림 중복 방지 (프로세스 생존 동안 유지)
_SRT_NOTIFIED: set = set()

# 이번 실행에서 이미 예약(hold/발권/예약대기)을 확보한 출발시각.
# KTXA_TIMES 가 여러 개면 전부 확보할 때까지 감시를 계속하고,
# 확보 건수가 감시 대상 수(len(ktxa_times)) 에 도달하면 종료한다.
_RESERVED_DEPARTS: set = set()


def _mark_reserved(config: KTXAConfig, depart: str, notifier) -> bool:
    """확보 기록 후, 목표 도달 여부(=종료 여부) 반환.

    목표는 KTXA_RESERVE_LIMIT (기본 1 = 여러 대 중 아무거나 1건 잡으면 종료,
    0 = 선택한 열차 전부).
    """
    _RESERVED_DEPARTS.add(depart)
    n_times = len(config.ktxa_times)
    limit = config.ktxa_reserve_limit
    total = n_times if limit <= 0 else min(limit, n_times)
    got = len(_RESERVED_DEPARTS)
    if got < total:
        remaining = total - got
        LOGGER.info("확보 %d/%d — 목표까지 %d건, 계속 감시", got, total, remaining)
        _notify(notifier, f"📊 진행 상황: {got}/{total}건 확보 — 목표까지 {remaining}건, 계속 감시")
        return False
    LOGGER.info("목표 %d건 확보 — 감시 종료", total)
    return True


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

    # 이미 확보한 출발시각은 재시도하지 않는다 (다중 감시)
    candidates = [c for c in candidates if c.get("depart") not in _RESERVED_DEPARTS]
    if not candidates:
        LOGGER.info("남은 후보 없음 (전부 확보했거나 좌석 없음). 다음 iteration 진행")
        return False

    # SRT 후보는 코레일 자동결제 불가 — Teams 알림만 보내고 예약 대상에서 제외
    for c in [c for c in candidates if c.get("status_kind") == "srt_link"]:
        key = (c["date"], c["depart"], c["seat_class"])
        if key not in _SRT_NOTIFIED:
            _SRT_NOTIFIED.add(key)
            line = f"{c['origin']}→{c['dest']} {c['date']} {c['depart']} [{c['seat_class']}] {c['status']}"
            LOGGER.info("SRT 빈자리 감지 (코레일 자동결제 불가 — 알림만): %s", line)
            _notify(notifier, f"🔔 SRT 빈자리 감지 — SRT 앱/사이트에서 직접 예매하세요\n{line}")
    candidates = [c for c in candidates if c.get("status_kind") != "srt_link"]
    if not candidates:
        return False

    best = candidates[0]
    kind = (best.get("status_kind") or "reserve")
    info_line = (
        f"{best['origin']}→{best['dest']} {best['date']} {best['depart']} "
        f"[{best['seat_class']}] {best['status']} (kind={kind})"
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
    except ReservationFailed as e:
        LOGGER.warning("예약 미성립 — 다음 iteration 재시도: %s", e)
        _notify(notifier, f"⚠ 예약 미성립 (잔여석 소진 추정) — 다음 iteration 재시도\n{e}")
        return False
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

    # 예약대기는 결제 단계 없음 — kind=waitlist 면 PAYMENT_MODE 와 무관하게 skip.
    if kind == "waitlist":
        LOGGER.info("kind=waitlist — 결제 단계 없음, 예약대기 신청 완료 상태")
        _notify(notifier, "ℹ 예약대기 신청 완료 — 빈자리 생기면 코레일에서 알림. 후속은 수동 결제.")
        return _mark_reserved(config, best["depart"], notifier)

    # 예약 단계 OK — 결제까지 연속 진행 (config 가 허용한 경우만)
    if not config.ktxa_payment_mode:
        LOGGER.info("KTXA_PAYMENT_MODE=false — 결제 단계 skip, 예약만 hold 상태")
        _notify(notifier, "ℹ KTXA_PAYMENT_MODE=false — 결제는 수동으로 진행하세요 (10분 timer)")
        return _mark_reserved(config, best["depart"], notifier)

    try:
        payment_mod.perform_payment(client, config)
        LOGGER.info("✅✅ 결제/발권 완료")
        _notify(notifier, f"✅✅ 결제/발권 완료\n{info_line}")
        _maybe_transfer(client, config, notifier)
        return _mark_reserved(config, best["depart"], notifier)
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
    seat_label = config.ktxa_seat_class or "일반실+특실"
    LOGGER.info(
        "Watcher booting: %s→%s on %s times=%s seat=%s train=%s mode=%s",
        config.ktxa_origin, config.ktxa_dest, config.ktxa_date, times_str,
        seat_label, config.ktxa_train_type, config.ktxa_mode,
    )

    notifier = _build_teams_notifier(config)
    _notify(
        notifier,
        f"🚄 KTX 워처 부팅\n{config.ktxa_origin}→{config.ktxa_dest} {config.ktxa_date} "
        f"times={times_str} seat={seat_label} mode={config.ktxa_mode} "
        f"payment={'on' if config.ktxa_payment_mode else 'off'}",
    )

    # 1) Chrome 디버그 인스턴스 확보
    launcher = ChromeLauncher(
        port=config.ktxa_cdp_port,
        user_data_dir=config.ktxa_cdp_user_data_dir,
        exe_path=config.ktxa_chrome_exe,
        startup_timeout=config.ktxa_cdp_startup_timeout,
        vdesk=config.ktxa_vdesk,
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
                except Exception as e:
                    LOGGER.warning("iteration 일시 예외 (%s: %s) — backoff 후 재시도", type(e).__name__, e)
                    _sleep_with_jitter(5.0, 12.0)
    finally:
        launcher.shutdown_if_owned()

    LOGGER.info("Watcher stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
