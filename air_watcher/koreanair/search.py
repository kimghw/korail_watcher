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

from ..config import AirConfig
from .client import KoreanAirSPAClient, human_pause

LOGGER = logging.getLogger("air_watcher.koreanair.search")


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


def _fare_families(cfg: AirConfig) -> List[str]:
    dom = cfg.air_origin in _DOMESTIC_CODES and cfg.air_dest in _DOMESTIC_CODES
    table = _DOM_FAMILIES if dom else _INT_FAMILIES
    return table.get(cfg.air_cabin, table[""])


def _build_payload(cfg: AirConfig) -> Dict:
    families = _fare_families(cfg)
    itineraries = [{
        "departureDateTime": f"{cfg.air_depart_date.isoformat()}T00:00:00.000",
        "destinationLocationCode": cfg.air_dest,
        "originLocationCode": cfg.air_origin,
        "commercialFareFamilies": families,
        "isRequestedBound": True,
    }]
    if cfg.air_trip_type == "roundtrip" and cfg.air_return_date:
        itineraries.append({
            "departureDateTime": f"{cfg.air_return_date.isoformat()}T00:00:00.000",
            "destinationLocationCode": cfg.air_origin,
            "originLocationCode": cfg.air_dest,
            "commercialFareFamilies": families,
            "isRequestedBound": False,
        })
    travelers: List[Dict] = []
    for _ in range(cfg.air_pax_adult):
        travelers.append({"passengerTypeCode": "ADT"})
    for _ in range(cfg.air_pax_child):
        travelers.append({"passengerTypeCode": "CHD"})
    for _ in range(cfg.air_pax_infant):
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


def _select_flight_url(cfg: AirConfig) -> str:
    booking_type = "A" if cfg.air_fare_type == "miles" else "R"
    trip_type = "RT" if cfg.air_trip_type == "roundtrip" else "OW"
    parts = [
        f"bookingType={booking_type}",
        f"origin={cfg.air_origin}",
        f"destination={cfg.air_dest}",
        f"departureDate={cfg.air_depart_date.strftime('%Y%m%d')}",
        f"adult={cfg.air_pax_adult}",
        f"child={cfg.air_pax_child}",
        f"infant={cfg.air_pax_infant}",
        f"cabinClass={_CABIN_URL.get(cfg.air_cabin, 'ECONOMY')}",
        f"tripType={trip_type}",
    ]
    if cfg.air_trip_type == "roundtrip" and cfg.air_return_date:
        parts.append(f"returnDate={cfg.air_return_date.strftime('%Y%m%d')}")
    return "https://www.koreanair.com/booking/select-flight/departure?" + "&".join(parts)


def _ensure_select_flight_referer(client: KoreanAirSPAClient, cfg: AirConfig) -> None:
    """fetch 전에 select-flight 페이지에 있는지 확인. drift 했으면 warm-up 재호출.

    Akamai 는 /booking/select-flight 직접 navigate 를 / 로 redirect 시키므로
    page.goto 로는 절대 도달할 수 없다. 홈 위젯 클릭 경로(warm-up)만 통한다.
    """
    import time as _t
    # circular import 회피 — search 호출 시점에 lazy import.
    from . import reserve as _reserve

    page = client.page
    cur = page.url or ""
    depart_str = cfg.air_depart_date.strftime("%Y%m%d")
    on_target = (
        "/booking/select-flight" in cur
        and f"origin={cfg.air_origin}" in cur
        and f"destination={cfg.air_dest}" in cur
        and f"departureDate={depart_str}" in cur
    )
    if not on_target:
        LOGGER.info("select-flight 페이지 이탈 (url=%s) — warm-up 재호출", cur)
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


def _within_window(t: time_cls, cfg: AirConfig, leg: str = "depart") -> bool:
    win = cfg.air_depart_time_window if leg == "depart" else cfg.air_return_time_window
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


def _extract_candidates(data: Dict, cfg: AirConfig) -> List[Dict]:
    groups = data.get("airBoundGroups") or []
    out: List[Dict] = []
    for grp in groups:
        segs = _segments({"boundDetails": grp.get("boundDetails") or grp.get("bound") or grp})
        if not segs:
            continue
        cand = _seg_to_candidate(segs[0], cfg.air_fare_type)
        dt = cand.get("depart_dt")
        if dt and not _within_window(dt.time(), cfg, "depart"):
            continue
        if cfg.air_flight_no:
            want = cfg.air_flight_no.replace(" ", "").upper()
            got = cand["flight_no"].replace(" ", "").upper()
            if want not in got:
                continue
        out.append(cand)
    return out


def perform_search(client: KoreanAirSPAClient, cfg: AirConfig) -> List[Dict]:
    _ensure_select_flight_referer(client, cfg)
    payload = _build_payload(cfg)
    LOGGER.info("air-bounds payload (head): %s",
                json.dumps(payload, ensure_ascii=False)[:300])
    data = _fetch_air_bounds(client, payload)
    if data is None:
        # 세션 만료(Akamai 쿠키 timeout) 일 가능성 — warm-up 으로 재진입 후 1 회 재시도.
        from . import reserve as _reserve
        LOGGER.info("air-bounds 실패 — warm-up 재호출 후 1 회 재시도")
        try:
            _reserve.warm_up_select_flight(client, cfg)
            data = _fetch_air_bounds(client, payload)
        except Exception as e:
            LOGGER.warning("warm-up 재호출 실패: %s", e)
    if not isinstance(data, dict):
        return []
    LOGGER.info("air-bounds top keys: %s", list(data.keys())[:10])
    total_groups = len(data.get("airBoundGroups") or [])
    candidates = _extract_candidates(data, cfg)
    LOGGER.info("후보 추출: %d 건 (airBoundGroups=%d)", len(candidates), total_groups)
    return candidates


__all__ = ["perform_search"]
