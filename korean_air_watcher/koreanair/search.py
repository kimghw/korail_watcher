"""KE 항공편 검색 — air-bounds API 직접 호출.

로그인 / 쿠키 세션은 위젯(외부 또는 사용자 수동)에서 채워 두고,
조회 폴링은 `/api/rp/dx/search/air-bounds` POST + `credentials:include` 로
페이지 컨텍스트 fetch 를 사용한다 (`runs/cdp_search_flights.py` 패턴).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, time as time_cls
from typing import Dict, List, Optional

from ..config import KoreanAirConfig
from .client import KoreanAirSPAClient, human_pause

LOGGER = logging.getLogger("korean_air_watcher.koreanair.search")


# 국내선 IATA (DOM* fare family 선택용)
_DOMESTIC_CODES = {
    "GMP", "ICN", "CJU", "PUS", "TAE", "CJJ", "KWJ",
    "USN", "RSU", "YNY", "KPO", "HIN",
}

_DOM_FAMILIES = {
    "":         ["DOMEY1", "DOMEY2", "DOMPR1"],
    "economy":  ["DOMEY1", "DOMEY2"],
    "prestige": ["DOMPR1"],
    "first":    ["DOMPR1"],
}
_INT_FAMILIES = {
    "":         ["INTEY", "INTPR", "INTFS"],
    "economy":  ["INTEY"],
    "prestige": ["INTPR"],
    "first":    ["INTFS"],
}


def _fare_families(cfg: KoreanAirConfig) -> List[str]:
    dom = cfg.korean_air_origin in _DOMESTIC_CODES and cfg.korean_air_dest in _DOMESTIC_CODES
    table = _DOM_FAMILIES if dom else _INT_FAMILIES
    return table.get(cfg.korean_air_cabin, table[""])


def _build_payload(cfg: KoreanAirConfig) -> Dict:
    families = _fare_families(cfg)
    itineraries = [{
        "departureDateTime": f"{cfg.korean_air_depart_date.isoformat()}T00:00:00.000",
        "destinationLocationCode": cfg.korean_air_dest,
        "originLocationCode": cfg.korean_air_origin,
        "commercialFareFamilies": families,
        "isRequestedBound": True,
    }]
    if cfg.korean_air_trip_type == "roundtrip" and cfg.korean_air_return_date:
        itineraries.append({
            "departureDateTime": f"{cfg.korean_air_return_date.isoformat()}T00:00:00.000",
            "destinationLocationCode": cfg.korean_air_origin,
            "originLocationCode": cfg.korean_air_dest,
            "commercialFareFamilies": families,
            "isRequestedBound": False,
        })
    travelers: List[Dict] = []
    for _ in range(cfg.korean_air_pax_adult):
        travelers.append({"passengerTypeCode": "ADT"})
    for _ in range(cfg.korean_air_pax_child):
        travelers.append({"passengerTypeCode": "CHD"})
    for _ in range(cfg.korean_air_pax_infant):
        travelers.append({"passengerTypeCode": "INF"})
    return {
        "currencyCode": "KRW",
        "itineraries": itineraries,
        "travelers": travelers,
        "searchPreferences": {"showSoldOut": True},
    }


_CABIN_URL = {
    "":         "ECONOMY",
    "economy":  "ECONOMY",
    "prestige": "PRESTIGE",
    "first":    "FIRST",
}


def _select_flight_url(cfg: KoreanAirConfig) -> str:
    booking_type = "A" if cfg.korean_air_fare_type == "miles" else "R"
    trip_type = "RT" if cfg.korean_air_trip_type == "roundtrip" else "OW"
    parts = [
        f"bookingType={booking_type}",
        f"origin={cfg.korean_air_origin}",
        f"destination={cfg.korean_air_dest}",
        f"departureDate={cfg.korean_air_depart_date.strftime('%Y%m%d')}",
        f"adult={cfg.korean_air_pax_adult}",
        f"child={cfg.korean_air_pax_child}",
        f"infant={cfg.korean_air_pax_infant}",
        f"cabinClass={_CABIN_URL.get(cfg.korean_air_cabin, 'ECONOMY')}",
        f"tripType={trip_type}",
    ]
    if cfg.korean_air_trip_type == "roundtrip" and cfg.korean_air_return_date:
        parts.append(f"returnDate={cfg.korean_air_return_date.strftime('%Y%m%d')}")
    return "https://www.koreanair.com/booking/select-flight/departure?" + "&".join(parts)


def _ensure_select_flight_referer(client: KoreanAirSPAClient, cfg: KoreanAirConfig,
                                   force_warmup: bool = False) -> None:
    """fetch 전에 select-flight 페이지에 있는지 확인. drift 했으면 warm-up 재호출.

    Akamai 는 /booking/select-flight 직접 navigate 를 / 로 redirect 시키므로
    page.goto 로는 절대 도달할 수 없다. 홈 위젯 클릭 경로(warm-up)만 통한다.
    """
    import time as _t
    # circular import 회피 — search 호출 시점에 lazy import.
    from . import reserve as _reserve

    page = client.page
    try:
        cur = page.evaluate("location.href") or ""
    except Exception:
        cur = page.url or ""
    want_path = ("/booking/select-award-flight" if cfg.korean_air_fare_type == "miles"
                 else "/booking/select-flight")
    if force_warmup:
        LOGGER.info("force_warmup=True — warm-up 강제 (leg 전환 시점)")
        _reserve.warm_up_select_flight(client, cfg, force=True)
    elif want_path in cur:
        # 이미 검색 결과 페이지 — 그냥 reload (warm-up 함정 회피)
        LOGGER.info("새로고침: %s", cur)
        try:
            page.reload(wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            LOGGER.warning("reload 실패: %s", e)
        try:
            new_url = page.evaluate("location.href") or ""
        except Exception:
            new_url = page.url or ""
        if want_path not in new_url:
            LOGGER.info("reload 후 검색 페이지 이탈 (%s) — warm-up 1회 시도", new_url)
            _reserve.warm_up_select_flight(client, cfg)
    else:
        LOGGER.info("검색 페이지 아님 (%s) — warm-up 1회 시도", cur)
        _reserve.warm_up_select_flight(client, cfg)
    # KE 자체 air-bounds 호출이 끝나며 Akamai 쿠키가 안착하길 기다린다 (옵션).
    deadline = _t.time() + 12.0
    while _t.time() < deadline:
        try:
            if page.evaluate(
                "!!document.querySelector('[class*=flight-list], "
                "[class*=FlightList], [data-testid*=flight]')"
            ):
                break
        except Exception:
            pass
        _t.sleep(0.5)
    human_pause(0.8, 1.4)


def _fetch_air_bounds(client: KoreanAirSPAClient, payload: Dict) -> Optional[Dict]:
    # XHR + 최소 헤더 (Angular HttpClient 와 동일) — Akamai bot manager 가 fetch 보다 관대함.
    expr = (
        "((body) => new Promise((resolve) => {\n"
        "  const xhr = new XMLHttpRequest();\n"
        "  xhr.open('POST', '/api/rp/dx/search/air-bounds', true);\n"
        "  xhr.setRequestHeader('Accept', 'application/json');\n"
        "  xhr.setRequestHeader('Content-Type', 'application/json');\n"
        "  xhr.withCredentials = true;\n"
        "  xhr.timeout = 30000;\n"
        "  xhr.onload = () => resolve({status: xhr.status, body: (xhr.responseText||'').slice(0, 300000)});\n"
        "  xhr.onerror = () => resolve({status: 0, body: 'xhr error'});\n"
        "  xhr.ontimeout = () => resolve({status: 0, body: 'xhr timeout'});\n"
        "  xhr.send(JSON.stringify(body));\n"
        "}))(" + json.dumps(payload, ensure_ascii=False) + ")"
    )
    result = client.page.evaluate(expr)
    status = (result or {}).get("status")
    body = (result or {}).get("body") or ""
    if status != 200:
        LOGGER.warning("air-bounds status=%s body[:300]=%s", status, body[:300])
        return None
    try:
        return json.loads(body)
    except json.JSONDecodeError as e:
        LOGGER.warning("air-bounds non-JSON: %s body[:300]=%s", e, body[:300])
        return None


def _within_window(t: time_cls, cfg: KoreanAirConfig, leg: str = "depart") -> bool:
    win = cfg.korean_air_depart_time_window if leg == "depart" else cfg.korean_air_return_time_window
    if not win:
        return True
    s, e = win
    return s <= t <= e


def _parse_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    s = s.replace("Z", "")
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _segments(bound: Dict) -> List[Dict]:
    details = bound.get("boundDetails") or bound.get("bound") or bound
    segs = details.get("segments") or details.get("flightSegments") or []
    return segs if isinstance(segs, list) else []


def _seg_to_candidate(seg: Dict, fare_type: str) -> Dict:
    dep = seg.get("departure") or seg.get("originAirport") or {}
    arr = seg.get("arrival") or seg.get("destinationAirport") or {}
    flight = seg.get("marketingFlightInfo") or seg.get("flightInfo") or {}
    airline = flight.get("airlineCode") or seg.get("marketingAirlineCode") or "KE"
    flight_no = str(flight.get("flightNumber") or seg.get("flightNumber") or "")
    dep_dt = _parse_dt(dep.get("dateTime") or dep.get("scheduledDateTime"))
    arr_dt = _parse_dt(arr.get("dateTime") or arr.get("scheduledDateTime"))
    cabin = seg.get("cabinClass") or seg.get("bookingClass") or ""
    return {
        "flight_no": f"{airline}{flight_no}".strip(),
        "origin": dep.get("locationCode") or "",
        "dest": arr.get("locationCode") or "",
        "depart": dep_dt.strftime("%H:%M") if dep_dt else "",
        "arrive": arr_dt.strftime("%H:%M") if arr_dt else "",
        "depart_dt": dep_dt,
        "cabin": cabin,
        "fare_type": fare_type,
        "status": "available",
        "raw": (
            f"{airline}{flight_no} {dep.get('locationCode')}→{arr.get('locationCode')} "
            f"{dep_dt.strftime('%H:%M') if dep_dt else '?'}→"
            f"{arr_dt.strftime('%H:%M') if arr_dt else '?'} {cabin}"
        ),
    }


def _extract_candidates(data: Dict, cfg: KoreanAirConfig) -> List[Dict]:
    groups = data.get("airBoundGroups") or []
    out: List[Dict] = []
    for grp in groups:
        segs = _segments({"boundDetails": grp.get("boundDetails") or grp.get("bound") or grp})
        if not segs:
            continue
        cand = _seg_to_candidate(segs[0], cfg.korean_air_fare_type)
        dt = cand.get("depart_dt")
        if dt and not _within_window(dt.time(), cfg, "depart"):
            continue
        if cfg.korean_air_flight_no:
            wants = [w.strip().replace(" ", "").upper()
                     for w in cfg.korean_air_flight_no.split(",") if w.strip()]
            got = cand["flight_no"].replace(" ", "").upper()
            if not any(w in got for w in wants):
                continue
        out.append(cand)
    return out


def _dom_scrape_candidates(client: KoreanAirSPAClient, cfg: KoreanAirConfig) -> List[Dict]:
    """Akamai 가 air-bounds API 를 403 으로 막을 때의 fallback.

    KE 가 결과 페이지 렌더링은 허용한다는 점을 이용 — `[class*='itinerary']` 카드에서
    편명 / 시간 / 매진여부 / 마일 표시를 텍스트로 긁어 candidate 를 만든다.
    매진(`매진`) 또는 미운영(`미운영`) 만 있고 가격(`마일`/`원`) 없는 카드는 skip.
    """
    import re
    import time as _t
    from datetime import datetime

    page = client.page

    # KE편명이 한 번이라도 나올 때까지 최대 20s 대기 (로딩 끝 신호)
    deadline = _t.time() + 20
    body = ""
    while _t.time() < deadline:
        try:
            body = page.locator("body").inner_text(timeout=1500)
        except Exception:
            body = ""
        if "찾고 있어요" not in body and re.search(r"KE\d{4,5}", body):
            break
        _t.sleep(0.7)
    if not re.search(r"KE\d{4,5}", body):
        LOGGER.warning("DOM scrape: KE 편명 미발견 (body_len=%d)", len(body))
        return []

    # 카드 단위로 텍스트 — itinerary 자체에는 fare(매진/마일) 정보가 없으므로
    # 매진/마일/원 단어를 포함하는 최소 ancestor 의 inner_text 를 가져온다.
    cards = []
    try:
        cards = page.evaluate(
            "Array.from(document.querySelectorAll(\"[class*='itinerary']\"))"
            "  .filter(el => /KE\\d{4,5}/.test(el.innerText))"
            "  .map(el => {"
            "    let cur = el;"
            "    for (let i=0; i<8 && cur; i++) {"
            "      const t = cur.innerText || '';"
            "      if (/매진|미운영|마일|\\d[\\d,]*\\s*원/.test(t)) return t;"
            "      cur = cur.parentElement;"
            "    }"
            "    return el.innerText;"
            "  })"
            "  .filter(t => t.length > 60)"
        ) or []
    except Exception as e:
        LOGGER.warning("DOM scrape evaluate 실패: %s", e)

    LOGGER.info("DOM scrape: %d cards", len(cards))
    if cards:
        # 첫 카드 raw 출력 (매진 판정 디버깅)
        LOGGER.info("DOM scrape sample card[0]: %r", cards[0][:600])

    out: List[Dict] = []
    seen_flight_cabin = set()
    miles_mode = (cfg.korean_air_fare_type == "miles")
    cabin_pref = (cfg.korean_air_cabin or "").lower()  # "" = ANY
    unit = "마일" if miles_mode else "원"

    # 검사할 cabin 후보
    cabin_targets = []
    if cabin_pref in ("", "economy"):
        cabin_targets.append(("economy", "일반석"))
    if cabin_pref in ("", "prestige"):
        cabin_targets.append(("prestige", "프레스티지석"))
    if cabin_pref in ("", "first"):
        cabin_targets.append(("first", "퍼스트"))

    for raw in cards:
        m_flight = re.search(r"KE\d{4,5}", raw)
        if not m_flight:
            continue
        flight_no = m_flight.group(0)
        times = re.findall(r"\b(\d{2}:\d{2})\b", raw)
        if len(times) < 2:
            continue
        dep_str, arr_str = times[0], times[1]
        try:
            h, mn = dep_str.split(":")
            dep_time = time_cls(int(h), int(mn))
        except ValueError:
            continue
        if not _within_window(dep_time, cfg, "depart"):
            continue
        if cfg.korean_air_flight_no:
            wants = [w.strip().replace(" ", "").upper()
                     for w in cfg.korean_air_flight_no.split(",") if w.strip()]
            got = flight_no.upper()
            if not any(w in got for w in wants):
                continue

        # cabin 별 박스 텍스트 — "일반석" 라벨 다음 60자 안의 청크에서 매진/가격 검사
        for ckey, klabel in cabin_targets:
            key = (flight_no, ckey)
            if key in seen_flight_cabin:
                continue
            chunk_m = re.search(klabel + r"[\s\S]{0,80}", raw)
            if not chunk_m:
                continue
            chunk = chunk_m.group(0)
            if "매진" in chunk or "미운영" in chunk:
                continue
            if unit not in chunk:
                continue
            seen_flight_cabin.add(key)
            out.append({
                "flight_no": flight_no,
                "origin": cfg.korean_air_origin,
                "dest": cfg.korean_air_dest,
                "depart": dep_str,
                "arrive": arr_str,
                "depart_dt": datetime.combine(cfg.korean_air_depart_date, dep_time),
                "cabin": ckey,
                "cabin_label": klabel,
                "fare_type": cfg.korean_air_fare_type,
                "status": "available",
                "raw": f"{flight_no} {cfg.korean_air_origin}→{cfg.korean_air_dest} "
                       f"{dep_str}→{arr_str} {klabel}"
                       + (" [miles]" if miles_mode else " [cash]"),
            })
    return out


def perform_search(client: KoreanAirSPAClient, cfg: KoreanAirConfig,
                    force_warmup: bool = False) -> List[Dict]:
    _ensure_select_flight_referer(client, cfg, force_warmup=force_warmup)
    payload = _build_payload(cfg)
    LOGGER.info("air-bounds payload (head): %s",
                json.dumps(payload, ensure_ascii=False)[:300])
    data = _fetch_air_bounds(client, payload)
    if isinstance(data, dict):
        LOGGER.info("air-bounds top keys: %s", list(data.keys())[:10])
        total_groups = len(data.get("airBoundGroups") or [])
        candidates = _extract_candidates(data, cfg)
        LOGGER.info("후보 추출 (API): %d 건 (airBoundGroups=%d)", len(candidates), total_groups)
        if candidates:
            return candidates
    # API 가 403/empty → DOM fallback (Akamai 차단 시).
    LOGGER.info("air-bounds API 응답 없음 → DOM scrape fallback")
    candidates = _dom_scrape_candidates(client, cfg)
    LOGGER.info("후보 추출 (DOM): %d 건", len(candidates))
    return candidates


__all__ = ["perform_search"]
