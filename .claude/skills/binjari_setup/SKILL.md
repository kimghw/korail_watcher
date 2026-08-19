---
name: binjari_setup
description: binjari 웹서버 설치·셋업 — 의존성 라이브러리 설치(필요 시 .venv 생성), 실행 런처(launch_binjari.bat) 생성, 바탕화면 'binjari' 아이콘 설치, 채팅·AI 복구용 claude CLI(exe) 설정 검토. 사용자가 "설치", "셋업", "바탕화면 아이콘", "새 PC 세팅", "의존성 설치" 등을 말하면 시작. 절차 — (1) scripts/setup.ps1 실행 (2) 아이콘·런처·의존성·claude CLI 검증 (3) 결과 보고.
---

# binjari_setup — 웹서버 설치·바탕화면 아이콘

한 번 실행하면 이 PC 에서 binjari 웹서버를 더블클릭으로 쓸 수 있게 만든다. 멱등 — 여러 번 실행해도 안전.

## 하는 일

1. **python 결정**: `.venv` 가 있으면 그걸 사용. 없으면 시스템 python 에 핵심 의존성(fastapi·uvicorn·playwright·pydantic·dotenv·aiohttp)이 있는지 확인하고, 부족할 때만 `.venv` 를 새로 만든다. `-Venv` 스위치로 강제 생성 가능.
2. **의존성 설치**: pyproject.toml 의 dependencies 와 동일한 목록을 pip 으로 설치 (충족된 건 skip).
3. **런처 생성**: 프로젝트 루트에 `launch_binjari.bat` — 포트 8001 이 안 떠 있으면 서버를 백그라운드(pythonw, 콘솔 창 없음)로 띄운 뒤 기본 브라우저로 http://localhost:8001 을 연다.
4. **바탕화면 아이콘**: `binjari.lnk` 를 바탕화면에 생성 (아이콘은 Chrome 아이콘, 없으면 시스템 기본). `-NoIcon` 으로 생략 가능.
5. **claude CLI 검토**: 웹 채팅 도우미(`/api/chat`)와 AI 자동 복구 폴백(fable→opus)이 쓰는 claude CLI(exe)가 있는지 확인 — PATH → `~\.local\bin\claude.exe` → `%APPDATA%\npm\claude.cmd` 순으로 탐색(web_server 의 `_find_claude` 와 동일 순서). 있으면 버전 출력, 없으면 설치 안내(https://claude.com/claude-code)를 경고로 남긴다. 자동 설치는 하지 않는다 (로그인이 필요해서 사용자가 직접).

## 실행

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "<프로젝트루트>\.claude\skills\binjari_setup\scripts\setup.ps1"
```

옵션: `-Venv` (강제 .venv), `-NoIcon` (아이콘 생략).

## 검증 (실행 후 반드시)

- [ ] 스크립트 출력에 `[binjari_setup] 완료` 가 있다.
- [ ] `launch_binjari.bat` 이 프로젝트 루트에 생겼다.
- [ ] 바탕화면에 `binjari.lnk` 가 있다 (`-NoIcon` 아니면).
- [ ] 선택한 python 으로 `import fastapi, uvicorn, playwright, aiohttp` 가 된다.
- [ ] claude CLI 가 `claude CLI OK` 로 확인됐다 — 없으면 사용자에게 채팅·AI 복구가 비활성임을 알린다.

## 주의

- `.venv` 를 새로 만든 경우 playwright 등 설치에 수 분 걸릴 수 있다.
- 의존성 목록을 바꾸면 **pyproject.toml 과 setup.ps1 의 $deps 를 같이** 고친다.
- 런처는 서버가 이미 떠 있으면 새로 띄우지 않고 브라우저만 연다. 서버 중지는 `/port_manager` 또는 웹 UI 와 무관하게 프로세스 종료로.
- 워처의 CDP Chrome(별도 프로필) 과는 무관 — 그건 감시 시작 시 워처가 알아서 띄운다.
