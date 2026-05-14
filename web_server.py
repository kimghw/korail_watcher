"""SRT/KTX 출발·도착·시간 조회 웹서버.

실행::

    python3 -m uvicorn web_server:app --host 0.0.0.0 --port 8000

브라우저에서 http://localhost:8000 접속 → 폼 입력 → 조회.

기존 srt_watcher / ktx_watcher_spa 의 Playwright 검색 모듈을 재사용하지만
필터(좌석 잔여/시간 허용) 는 풀어 두어 해당 날짜의 *모든* 스케줄을 반환한다.
"""

from __future__ import annotations

import logging
import threading
from datetime import date as _date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from srt_watcher.config import SRTConfig
from srt_watcher.srt.client import SRTClient, _attach_popup_guard, safe_click
from srt_watcher.srt import search as srt_search
from srt_watcher.srt import selectors as srt_selectors

from ktx_watcher_spa.config import KTXAConfig
from ktx_watcher_spa.korail.client import KorailSPAClient
from ktx_watcher_spa.korail import search as ktx_search


LOGGER = logging.getLogger("web_server")
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(name)s | %(message)s")

app = FastAPI(title="SRT/KTX 조회 웹서버")

ARTIFACT_ROOT = Path("/tmp/srt_ktx_web/artifacts")
ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)

# Playwright sync API 는 동일 프로세스에서 동시 실행이 까다로워 rail 별 잠금.
_SRT_LOCK = threading.Lock()
_KTX_LOCK = threading.Lock()


# ───────────────────────── Request / Response ─────────────────────────

class SearchRequest(BaseModel):
    origin: str = Field(..., description="출발역 (예: 수서, 서울)")
    dest: str = Field(..., description="도착역 (예: 부산)")
    date: str = Field(..., description="YYYY-MM-DD")
    earliest_hour: int = Field(6, ge=0, le=23, description="조회 시작 시각 (시)")
    passengers: int = Field(1, ge=1, le=9)


def _parse_date(s: str) -> _date:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="date 는 YYYY-MM-DD 형식") from exc


# ───────────────────────── SRT ─────────────────────────

def _build_srt_config(req: SearchRequest) -> SRTConfig:
    earliest = f"{req.earliest_hour:02d}:00"
    return SRTConfig.model_validate({
        "SRT_USER": "anonymous",
        "SRT_PASS": "anonymous",
        "SRT_ORIGIN": req.origin,
        "SRT_DEST": req.dest,
        "SRT_DATE": req.date,
        "SRT_TIMES": earliest,
        "SRT_PASSENGERS": str(req.passengers),
        "SRT_TOLERANCE_MIN": "1440",
        "SRT_MODE": "search",
        "SRT_HEADLESS": "true",
        "TEAMS_ENABLED": "false",
    })


def _srt_list_schedules(req: SearchRequest) -> List[Dict[str, Any]]:
    """SRT 시간표 전체 (매진 포함) 반환."""
    config = _build_srt_config(req)

    with _SRT_LOCK:
        with SRTClient(headless=True) as client:
            page = client.new_page()
            _attach_popup_guard(page)

            srt_search._navigate_to_search(page)
            srt_search._check_for_captcha(page)
            srt_search.fill_search_form(page, config)

            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
            try:
                with page.expect_navigation(timeout=15_000, wait_until="domcontentloaded"):
                    safe_click(page, srt_selectors.SEARCH_BUTTON)
            except PlaywrightTimeoutError:
                LOGGER.warning("SRT 검색 후 네비게이션 타임아웃 — 계속 진행")
            except Exception as exc:
                LOGGER.debug("SRT 검색 네비게이션 예외 (무시): %s", exc)

            try:
                page.wait_for_load_state("networkidle", timeout=5_000)
            except PlaywrightTimeoutError:
                pass

            try:
                page.wait_for_selector(
                    f"{srt_selectors.RESULT_ROWS}:has({srt_selectors.COL_DEPART_TIME})",
                    timeout=5_000,
                )
            except PlaywrightTimeoutError:
                pass

            rows = page.query_selector_all(srt_selectors.RESULT_ROWS)
            out: List[Dict[str, Any]] = []
            for row in rows:
                depart_el = row.query_selector(srt_selectors.COL_DEPART_TIME)
                if not depart_el:
                    continue
                type_el = row.query_selector("td:nth-child(2)")
                num_el = row.query_selector("td:nth-child(3)")
                arrive_el = row.query_selector("td:nth-child(5)")
                first_el = row.query_selector("td:nth-child(6)")
                general_el = row.query_selector("td:nth-child(7)")

                def txt(el):
                    if not el:
                        return ""
                    try:
                        return " ".join(el.inner_text().split())
                    except Exception:
                        return ""

                out.append({
                    "train_type": txt(type_el),
                    "train_no": txt(num_el),
                    "depart": txt(depart_el),
                    "arrive": txt(arrive_el),
                    "first": txt(first_el),
                    "general": txt(general_el),
                })
            LOGGER.info("SRT 결과 %d건", len(out))
            return out


# ───────────────────────── KTX ─────────────────────────

def _build_ktxa_config(req: SearchRequest) -> KTXAConfig:
    earliest = f"{req.earliest_hour:02d}:00"
    return KTXAConfig.model_validate({
        "KTXA_ORIGIN": req.origin,
        "KTXA_DEST": req.dest,
        "KTXA_DATE": req.date,
        "KTXA_TIMES": earliest,
        "KTXA_PASSENGERS": str(req.passengers),
        "KTXA_TOLERANCE_MIN": "1440",
        "KTXA_MODE": "search",
        "KTXA_HEADLESS": "true",
        "TEAMS_ENABLED": "false",
    })


def _ktx_list_schedules(req: SearchRequest) -> List[Dict[str, Any]]:
    """KTX(코레일) 시간표 전체 반환."""
    config = _build_ktxa_config(req)

    with _KTX_LOCK:
        with KorailSPAClient(headless=True) as client:
            page = ktx_search.navigate_to_search(client)
            ktx_search.fill_search_form(page, config)
            raw = ktx_search.submit_search(page, ARTIFACT_ROOT)

            out: List[Dict[str, Any]] = []
            for r in raw:
                out.append({
                    "train_type": r.get("train_name", ""),
                    "train_no": "",
                    "depart": r.get("depart", ""),
                    "arrive": "",
                    "first": r.get("first_status", ""),
                    "general": r.get("general_status", ""),
                })
            LOGGER.info("KTX 결과 %d건", len(out))
            return out


# ───────────────────────── HTTP endpoints ─────────────────────────

@app.get("/", response_class=HTMLResponse)
def index() -> str:
    today = _date.today().isoformat()
    return f"""
<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <title>SRT / KTX 시간표 조회</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
           margin: 24px; max-width: 1100px; }}
    h1 {{ font-size: 22px; }}
    form {{ display: grid; grid-template-columns: repeat(6, auto); gap: 8px 12px; align-items: end; }}
    label {{ font-size: 12px; color: #555; }}
    input, select {{ padding: 6px 8px; font-size: 14px; }}
    .btnrow {{ grid-column: 1 / -1; display: flex; gap: 8px; margin-top: 8px; }}
    button {{ padding: 8px 18px; cursor: pointer; }}
    button.srt {{ background: #f5e9ff; }}
    button.ktx {{ background: #e0f0ff; }}
    #status {{ margin: 12px 0; color: #666; font-size: 13px; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 8px; font-size: 13px; }}
    th, td {{ border-bottom: 1px solid #eee; padding: 6px 8px; text-align: left; vertical-align: top; }}
    th {{ background: #fafafa; }}
    tr:hover td {{ background: #f8f8ff; }}
    .empty {{ color: #999; padding: 20px; text-align: center; }}
    .pill {{ display: inline-block; padding: 1px 8px; border-radius: 10px; font-size: 11px; }}
    .pill.srt {{ background: #f5e9ff; color: #6020a0; }}
    .pill.ktx {{ background: #e0f0ff; color: #1060c0; }}
  </style>
</head>
<body>
  <h1>SRT / KTX 시간표 조회</h1>
  <form id="qform">
    <div><label>출발역 <small style="color:#999">(KTX=서울/용산, SRT=수서)</small></label><br><input name="origin" value="서울" required></div>
    <div><label>도착역</label><br><input name="dest" value="부산" required></div>
    <div><label>날짜</label><br><input name="date" type="date" value="{today}" required></div>
    <div><label>조회 시작 시각</label><br>
      <select name="earliest_hour">
        {''.join(f'<option value="{h}"{ " selected" if h==6 else "" }>{h:02d}:00</option>' for h in range(24))}
      </select>
    </div>
    <div><label>인원</label><br>
      <select name="passengers">
        {''.join(f'<option value="{n}"{ " selected" if n==1 else "" }>{n}명</option>' for n in range(1, 10))}
      </select>
    </div>
    <div class="btnrow">
      <button type="button" class="srt" onclick="search('srt')">SRT 조회</button>
      <button type="button" class="ktx" onclick="search('ktx')">KTX 조회</button>
      <button type="button" onclick="search('both')">둘 다 조회</button>
    </div>
  </form>
  <div id="status"></div>
  <div id="result"></div>

<script>
function payload() {{
  const f = document.getElementById('qform');
  return {{
    origin: f.origin.value,
    dest:   f.dest.value,
    date:   f.date.value,
    earliest_hour: parseInt(f.earliest_hour.value, 10),
    passengers:    parseInt(f.passengers.value, 10),
  }};
}}

async function callOne(rail, body) {{
  const r = await fetch(`/api/search/${{rail}}`, {{
    method: 'POST',
    headers: {{ 'Content-Type': 'application/json' }},
    body: JSON.stringify(body),
  }});
  if (!r.ok) {{
    const t = await r.text();
    throw new Error(`${{rail.toUpperCase()}} ${{r.status}}: ${{t}}`);
  }}
  return r.json();
}}

function renderRows(rail, rows) {{
  if (!rows || rows.length === 0) {{
    return `<div class="empty">${{rail.toUpperCase()}} 결과 없음</div>`;
  }}
  const head = `<tr>
    <th>구분</th><th>열차</th><th>열차번호</th>
    <th>출발</th><th>도착</th><th>특실</th><th>일반실</th>
  </tr>`;
  const body = rows.map(r => `<tr>
    <td><span class="pill ${{rail}}">${{rail.toUpperCase()}}</span></td>
    <td>${{r.train_type || ''}}</td>
    <td>${{r.train_no || ''}}</td>
    <td>${{r.depart || ''}}</td>
    <td>${{r.arrive || ''}}</td>
    <td>${{r.first || ''}}</td>
    <td>${{r.general || ''}}</td>
  </tr>`).join('');
  return `<table>${{head}}${{body}}</table>`;
}}

async function search(which) {{
  const status = document.getElementById('status');
  const result = document.getElementById('result');
  const body = payload();
  status.textContent = `조회 중... (${{which.toUpperCase()}}) — 브라우저 자동화로 ~10초 소요`;
  result.innerHTML = '';
  const t0 = performance.now();
  try {{
    let html = '';
    if (which === 'srt' || which === 'both') {{
      const data = await callOne('srt', body);
      html += `<h3>SRT (${{data.count}}건)</h3>` + renderRows('srt', data.rows);
    }}
    if (which === 'ktx' || which === 'both') {{
      const data = await callOne('ktx', body);
      html += `<h3>KTX (${{data.count}}건)</h3>` + renderRows('ktx', data.rows);
    }}
    result.innerHTML = html;
    status.textContent = `완료 (${{((performance.now()-t0)/1000).toFixed(1)}}초)`;
  }} catch (e) {{
    status.textContent = `오류: ${{e.message}}`;
  }}
}}
</script>
</body>
</html>
"""


@app.post("/api/search/srt")
def api_search_srt(req: SearchRequest) -> Dict[str, Any]:
    _parse_date(req.date)
    try:
        rows = _srt_list_schedules(req)
    except Exception as exc:
        LOGGER.exception("SRT 검색 실패")
        raise HTTPException(status_code=500, detail=f"SRT 검색 실패: {exc}") from exc
    return {"rail": "SRT", "count": len(rows), "rows": rows}


@app.post("/api/search/ktx")
def api_search_ktx(req: SearchRequest) -> Dict[str, Any]:
    _parse_date(req.date)
    try:
        rows = _ktx_list_schedules(req)
    except Exception as exc:
        LOGGER.exception("KTX 검색 실패")
        raise HTTPException(status_code=500, detail=f"KTX 검색 실패: {exc}") from exc
    return {"rail": "KTX", "count": len(rows), "rows": rows}


@app.get("/healthz")
def healthz() -> Dict[str, str]:
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
