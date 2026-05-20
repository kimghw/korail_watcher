# korean_air 워처 — 문제점 & 해결방안

`korail_watcher` 의 `korean_air_watcher` 가 KE 보너스(마일) 좌석을 폴링하면서 만난 함정과 검증된 회피책. 작성 시점 2026-05-20.

---

## 1. DB 경로 버그 — Teams 토큰 못 찾음

### 증상
워처 로그에 `No token found for kimghw@krs.co.kr`. `team_mcp/database/auth.db` 에는 분명 토큰이 있는데 워처가 빈 DB 를 보고 있음.

### 원인
`team_mcp/session/auth_database.py` 의 path 해석.

```python
base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# = <repo>/team_mcp
resolved_path = os.path.join(base_dir, db_path)
```

`.env` 에 `DB_PATH=./team_mcp/database/auth.db` 가 있으면 `base_dir + "./team_mcp/database/auth.db"` = `<repo>/team_mcp/team_mcp/database/auth.db` 로 이중 prefix. 그 경로엔 DB 가 없으니 빈 DB 새로 만들어 거기서 토큰 조회 → 0건.

### 해결
`.env` 의 `DB_PATH` 를 절대 경로로.

```dotenv
DB_PATH=C:/Users/kimghw/korail_watcher/team_mcp/database/auth.db
```

토큰 자동 refresh 가 정상 동작 — access 만료돼도 refresh_token 으로 갱신, 다음 알림에 사용 가능.

검증:

```python
from session.auth_manager import AuthManager
import asyncio
mgr = AuthManager()
print(mgr.auth_db.db_path)            # 절대 경로 한 번만
asyncio.run(mgr.validate_and_refresh_token('kimghw@krs.co.kr'))
# → Token refreshed successfully
```

---

## 2. 위젯 함정 — warm-up 매 iteration 실행 + 매번 실패

### 증상
2차 iteration 부터 `warm-up: date picker 못 열음`, `fare switch 토글 실패`, `select-flight 진입 실패 (page.url='https://www.koreanair.com/', js_url='https://www.koreanair.com/')`. backoff 후 무한 retry.

### 원인 (메모리 `project_ke_warmup_findings` 와 일치)

| 함정 | 메커니즘 |
|---|---|
| `chip-X 가짜` | radio input 의 `checked` 속성이 UI 실제 상태와 어긋남 |
| `ui-switch 클릭 무시` | fare-type 토글이 KDS-SWITCH 커스텀 컴포넌트. 일반 `click()` 무시, pointerdown/up 또는 드래그 필요 |
| `fare-type 탭 없음` | fare 는 탭이 아니라 토글. 탭으로 찾으려 하면 매번 fail |
| `Escape=discard` | picker 안에서 Escape 누르면 변경 사항 버림 |
| `page.url stale` | CDP `pg.url` 캐시가 navigation 뒤에도 안 갱신됨 |
| `KE의 home redirect` | idle/봇 의심 상태가 되면 결과 페이지를 home 으로 강제 redirect |

추가로 `search.py:_ensure_select_flight_referer` 가 URL query string (`origin=`, `destination=`, `departureDate=`) 까지 매칭을 요구했음. SPA 로 진입한 페이지엔 query string 이 없으니 매 iteration `on_target=False` → warm-up 재호출 → 함정 부딪힘.

### 해결
**warm-up 회피 — 결과 페이지면 새로고침만**.

```python
# search.py:_ensure_select_flight_referer
cur = page.evaluate("location.href") or ""           # page.url stale 회피
want_path = "/booking/select-award-flight" if miles else "/booking/select-flight"
if want_path in cur:
    page.reload(wait_until="domcontentloaded", timeout=30000)
    new_url = page.evaluate("location.href") or ""
    if want_path not in new_url:
        _reserve.warm_up_select_flight(client, cfg)  # 이탈 시에만 warm-up
else:
    _reserve.warm_up_select_flight(client, cfg)      # 초기 1회
```

조건: 사용자가 (1) 로그인된 Chrome 으로 (2) 최초 1회 KE 위젯 세팅 + 검색 클릭 — 그 이후엔 reload 만으로 SPA state 유지. 워처가 위젯을 다시 안 만짐.

---

## 3. Akamai 403 — air-bounds API 차단

### 증상
```
air-bounds status=403 body=Access Denied — You don't have permission to access "/api/rp/dx/search/air-bounds"
```

XHR 헤더 다 맞춰서 `page.evaluate` 로 호출해도 동일. KE 자체 SPA 의 XHR 호출은 통과.

### 원인
Akamai bot manager 가 fingerprint (TLS, header set, navigator 속성, 마우스 패턴 등) 로 봇 추정. 우리 fetch 가 일관되게 봇으로 분류됨.

### 해결
**API 호출 포기 — KE가 페이지에 그린 결과를 DOM scrape**.

```python
def _dom_scrape_candidates(client, cfg):
    cards = page.evaluate("""
      Array.from(document.querySelectorAll("[class*='itinerary']"))
        .filter(el => /KE\\d{4,5}/.test(el.innerText))
        .map(el => {
          let cur = el;
          for (let i=0; i<8 && cur; i++) {
            const t = cur.innerText || '';
            if (/매진|미운영|마일|\\d[\\d,]*\\s*원/.test(t)) return t;
            cur = cur.parentElement;
          }
          return el.innerText;
        })
        .filter(t => t.length > 60)
    """)
    # 텍스트로 편명·시각·매진여부 파싱
```

`perform_search` 가 API → DOM 순서로 시도. API 가 200 + 후보 있으면 그걸, 403 이거나 비었으면 DOM 폴백.

---

## 4. 매진 판정 false positive

### 증상
KE1214 13:05 보너스 일반석 매진 / 프레스티지 미운영인데 candidate 로 잡혀 Teams 알림 폭주.

### 원인
KE 결과 페이지 DOM 구조:
- `[class*='itinerary']` 카드: 시각 / 출도착지 / 편명 (`KE1214`) / "상세 보기"
- 그 카드 옆 별개 element: 일반석 박스 (`매진` 또는 `5,000 마일`), 프레스티지석 박스 (`미운영` 또는 `6,000 마일`)

즉 itinerary 카드 자체에는 fare 정보 없음. `"매진" in raw_text` → False → available 로 분류.

### 해결
`itinerary` element 에서 시작해 **parent ancestor 8단계까지 walk**, 매진/미운영/마일/원 중 하나가 처음 등장하는 가장 가까운 ancestor 의 `innerText` 를 카드 텍스트로 사용. cabin 별 정규식:

```python
unit = "마일" if miles_mode else "원"
has_price = unit in raw
if ("매진" in raw or "미운영" in raw) and not has_price:
    continue   # 전체 매진
if cabin == "economy" and re.search(r"일반석[^프]{0,40}매진", raw):
    continue
if cabin == "prestige" and re.search(r"프레스티지석[^일]{0,40}(매진|미운영)", raw):
    continue
```

검증된 카드 텍스트 (`5/29 KE1114 06:55` 잔여 좌석):
```
출발시각 / 06:55 / 출발지 / CJU / 도착시각 / 08:10 / 도착지 / GMP
소요시간 / 01시간 15분 / 편명 / 대한항공 운항 / KE1114 / 상세 보기
항공편명 KE1114 / 일반석 / 5,000 마일
항공편명 KE1114 / 프레스티지석 / 6,000 마일 /  1 석
```

---

## 정상 폴링 흐름 (5/29 13:05 대 보너스석 매진 상태)

```
새로고침: .../booking/select-award-flight/departure
air-bounds payload (head): {...}
air-bounds status=403 Access Denied
air-bounds API 응답 없음 → DOM scrape fallback
DOM scrape: 116 cards
DOM scrape sample card[0]: <KE1114 06:55 5,000 마일 ...>
후보 추출 (DOM): 0 건                                  ← 13:05 ±30분 매진
후보 없음. 다음 iteration 진행
다음 검색까지 12.74s 대기
```

좌석이 1석이라도 풀리면 `후보 추출 (DOM): N 건` → `_notify` 가 Teams `48:notes` 로 한 줄 알림 (`KE1214 CJU→GMP 13:05→14:20 [miles]`).

---

## 사전 조건 (이 모든 fix 가 효과를 보려면)

1. `.env` 의 `DB_PATH` 가 절대 경로 (위 §1).
2. **`KOREAN_AIR_USER` / `KOREAN_AIR_PASS` 가 채워져 있음** — 워처는 부팅 시 `ensure_logged_in()` 으로 자동 로그인한다. 익명 모드 미지원 (config validator 가 빈 값이면 즉시 reject).
3. CDP 9446 Chrome 이 사용자 프로필로 띄워져 있음. 워처가 ID/PW 로 로그인하므로 사전에 수동 로그인되어 있을 필요는 없음.
4. 사용자가 한 번 위젯 → 검색 → select-award-flight (cash 면 select-flight) 페이지에 진입해 둠. SPA state 유지하는 동안 워처는 reload-only.
5. 페이지가 home 으로 redirect 되면 워처가 `_reserve.warm_up_select_flight` 1회 호출로 자동 복귀 시도. 그것도 실패하면 사용자에게 알림 (현재는 backoff retry).
