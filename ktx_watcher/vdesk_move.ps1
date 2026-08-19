# Chrome 창을 별도 가상 데스크톱("binjari")으로 이동 — 사용자 화면 전환 없음.
#
# chrome_launcher.py 가 CDP 준비 후 호출한다.
# 요구사항: VirtualDesktop PowerShell 모듈 (MScholtes, PSGallery)
#   Install-Module VirtualDesktop -Scope CurrentUser -Force
# 없으면 exit 2 로 조용히 skip (런처가 경고 로그만 남김).
#
# NOTE: 문서화된 IVirtualDesktopManager.MoveWindowToDesktop 은 다른 프로세스
# 창에 Access Denied (2026-08-19 검증) — 그래서 모듈(내부 API) 사용.
param(
    [Parameter(Mandatory = $true)][int]$Port,
    [string]$Name = 'binjari'
)

$ErrorActionPreference = 'Stop'
# 호출측(python)이 utf-8 로 읽음 — 한글 출력 인코딩 고정
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

try {
    Import-Module VirtualDesktop -WarningAction SilentlyContinue
} catch {
    Write-Output "SKIP: VirtualDesktop 모듈 없음 — Install-Module VirtualDesktop -Scope CurrentUser -Force"
    exit 2
}

# 1) CDP 포트를 listen 중인 Chrome 브라우저 프로세스 pid
$conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
    Select-Object -First 1
if (-not $conn) { Write-Output "SKIP: port $Port listener 없음"; exit 3 }
$chromePid = [uint32]$conn.OwningProcess

# 2) 해당 pid 의 보이는 top-level 창 열거 (popup 포함 — MainWindowHandle 은 1개만 줌)
Add-Type -Language CSharp @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;

public static class BinjariWinEnum
{
    delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);
    [DllImport("user32.dll")] static extern bool EnumWindows(EnumWindowsProc cb, IntPtr lParam);
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint pid);
    [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr hWnd);
    [DllImport("user32.dll")] static extern int GetWindowTextLength(IntPtr hWnd);

    public static long[] TopWindowsOfPid(uint targetPid)
    {
        // 타이틀 없는 보조 창(툴팁 등)은 가상 데스크톱 관리 대상이 아님 → 제외
        var found = new List<long>();
        EnumWindows((h, l) => {
            uint pid;
            GetWindowThreadProcessId(h, out pid);
            if (pid == targetPid && IsWindowVisible(h) && GetWindowTextLength(h) > 0)
                found.Add(h.ToInt64());
            return true;
        }, IntPtr.Zero);
        return found.ToArray();
    }
}
'@

$wins = [BinjariWinEnum]::TopWindowsOfPid($chromePid)
if ($wins.Count -eq 0) { Write-Output "SKIP: pid $chromePid 의 보이는 창 없음"; exit 4 }

# 3) 이름이 $Name 인 데스크톱 찾기, 없으면 생성 (New-Desktop 은 화면 전환 안 함)
$target = $null
$count = Get-DesktopCount
for ($i = 0; $i -lt $count; $i++) {
    if ((Get-DesktopName $i) -eq $Name) { $target = Get-Desktop $i; break }
}
if (-not $target) {
    $target = New-Desktop
    Set-DesktopName -Desktop $target -Name $Name
}
$targetIdx = Get-DesktopIndex $target

# 4) 이동 (이미 그 데스크톱이면 skip, 관리 대상 아닌 창은 무시)
$moved = 0
foreach ($h in $wins) {
    try {
        $curIdx = Get-DesktopIndex (Get-DesktopFromWindow -Hwnd $h)
        if ($curIdx -ne $targetIdx) {
            Move-Window -Desktop $target -Hwnd $h | Out-Null
            $moved++
        }
    } catch {
        Write-Output "warn: hwnd=$h 이동 불가 — $($_.Exception.Message.Trim())"
    }
}
Write-Output "OK: moved=$moved/$($wins.Count) desktop='$Name'(idx=$targetIdx) pid=$chromePid"
