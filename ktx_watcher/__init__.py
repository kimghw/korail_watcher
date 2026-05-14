"""KTX-A watcher — CDP-only variant.

이 패키지는 Korail SPA(www.korail.com) 에 대해 사용자가 띄운 Chrome 디버그
인스턴스에 connect_over_cdp 로 붙어서 동작한다. 자체 chromium 을 launch 하는
경로는 없다 — 매크로/봇 가드(-8002/-8003) 가 자체 launch 인스턴스를 지속적으로
차단하기 때문.

흐름:
  1. chrome_launcher 가 KTXA_CDP_PORT 가 살아있는지 확인. 없으면 chrome.exe
     subprocess 로 디버그 모드 기동.
  2. korail.client 가 connect_over_cdp 로 attach.
  3. korail.search 가 검색 폼 입력/제출/결과 파싱.
  4. -8002/-8003 안내 모달/팝업이 뜨면 '확인' 클릭으로 dismiss 후 빈 결과
     return → main polling 이 자연스럽게 다음 iteration 에서 재검색.
"""
