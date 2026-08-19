#!/usr/bin/env bash
# export_azure.sh [<src>] [<out>]
# .env.ktx 에서 "Azure AD OAuth" 섹션(헤더 주석 포함)만 추출해 <out> 으로 저장한다.
# 섹션 경계: "# ====..." 룰러 3줄 헤더 ~ 다음 "# ====..." 룰러(다음 섹션 시작) 직전.
set -euo pipefail

SRC="${1:-.env.ktx}"
OUT="${2:-.env.azure}"

[ -f "$SRC" ] || { echo "ERROR: source not found: $SRC" >&2; exit 1; }

awk '
  /^# ={10,}/ {
    if (insec) {
      if (hdrclose) exit            # 다음 섹션 시작 룰러 → 종료
      print; hdrclose = 1; next     # Azure 헤더의 닫는 룰러
    }
    hdr = $0; expect = 1; next      # 여는 룰러 후보 저장
  }
  expect && /Azure AD OAuth/ { insec = 1; hdrclose = 0; print hdr; print; expect = 0; next }
  expect { expect = 0 }
  insec { print }
' "$SRC" > "$OUT"

# 섹션 헤더를 못 찾았으면 AZURE_* 키 직접 추출로 폴백
if ! grep -q '^AZURE_' "$OUT" 2>/dev/null; then
  grep '^AZURE_' "$SRC" > "$OUT" || { echo "ERROR: no AZURE_* keys in $SRC" >&2; rm -f "$OUT"; exit 1; }
fi

echo "OK $OUT ($(grep -c '^AZURE_' "$OUT") keys)"
grep '^AZURE_' "$OUT" | cut -d= -f1
