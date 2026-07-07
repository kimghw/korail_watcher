"""chrome_bind.py — 크롬 아이콘(.lnk) 지정 → 자동화 채널 바인딩 관리 (스킬 chrome-bind 워커).

사용자가 아이콘을 지정하면(set) .lnk 에서 포트·프로필을 읽어 <루트>/chrome_binding.yaml(SSOT)에
등록하고, 모든 KRS 자동화 러너는 krs_watcher/chrome_binding.resolve() 로 그 창에만 붙는다.

  python chrome_bind.py set "<lnk 경로>" [--channel krs] [--port 9333]   # 지정(포트 없으면 주입+백업)
  python chrome_bind.py status [--channel krs]                           # 아이콘·인수·창·기기신뢰 점검
  python chrome_bind.py launch [--channel krs]                           # 바인딩대로 창 기동(재사용)
  python chrome_bind.py resolve [--channel krs]                          # 러너가 쓸 값 출력(JSON)

원칙: 자격증명 미저장 · .lnk 수정 시 KRS_ECLASS_CACHE 에 .bak 백업 · 창은 종료하지 않음(비파괴).
"""
from __future__ import annotations
import argparse, json, os, re, socket, subprocess, sys, time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SKILL = Path(__file__).resolve().parent
ROOT = SKILL.parents[2]                              # <프로젝트루트>
sys.path.insert(0, str(ROOT))
from krs_watcher.chrome_binding import BINDING_FILE, FALLBACKS, resolve  # noqa: E402

CHROME = os.environ.get("KTXA_CHROME_EXE") or r"C:\Program Files\Google\Chrome\Application\chrome.exe"
BACKUP_DIR = ROOT / "KRS_ECLASS_CACHE"
STD_FLAGS = "--remote-allow-origins=* --no-first-run --no-default-browser-check --ignore-certificate-errors"


# ── .lnk 읽기/쓰기 (PowerShell WScript.Shell — 한글 경로는 env 로 전달) ────────
def read_lnk(lnk: str) -> dict:
    ps = ("$ws = New-Object -ComObject WScript.Shell; $sc = $ws.CreateShortcut($env:CB_LNK); "
          "@{target=$sc.TargetPath; args=$sc.Arguments} | ConvertTo-Json -Compress")
    env = {**os.environ, "CB_LNK": lnk}
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], env=env,
                       capture_output=True, text=True, encoding="utf-8", timeout=30)
    if r.returncode != 0 or not (r.stdout or "").strip().startswith("{"):
        raise RuntimeError(f".lnk 읽기 실패: {r.stderr.strip()[:200]}")
    return json.loads(r.stdout)


def write_lnk(lnk: str, target: str, args: str, desc: str) -> None:
    ps = ("$ws = New-Object -ComObject WScript.Shell; $sc = $ws.CreateShortcut($env:CB_LNK); "
          "$sc.TargetPath = $env:CB_TGT; $sc.Arguments = $env:CB_ARGS; $sc.Description = $env:CB_DESC; $sc.Save()")
    env = {**os.environ, "CB_LNK": lnk, "CB_TGT": target, "CB_ARGS": args, "CB_DESC": desc}
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], env=env,
                       capture_output=True, text=True, encoding="utf-8", timeout=30)
    if r.returncode != 0:
        raise RuntimeError(f".lnk 쓰기 실패: {r.stderr.strip()[:200]}")


def parse_args_str(args_str: str) -> dict:
    port = None
    m = re.search(r"--remote-debugging-port=(\d+)", args_str or "")
    if m:
        port = int(m.group(1))
    udd = None
    m = re.search(r'--user-data-dir="([^"]+)"', args_str or "") or re.search(r"--user-data-dir=(\S+)", args_str or "")
    if m:
        udd = m.group(1)
    return {"port": port, "user_data_dir": udd}


# ── 바인딩 yaml 읽기/쓰기 (주석 헤더 보존) ────────────────────────────────────
def load_yaml() -> dict:
    import yaml
    if BINDING_FILE.exists():
        return yaml.safe_load(BINDING_FILE.read_text(encoding="utf-8")) or {}
    return {}


def save_yaml(data: dict) -> None:
    import yaml
    header = ""
    if BINDING_FILE.exists():
        lines = BINDING_FILE.read_text(encoding="utf-8").splitlines(keepends=True)
        header = "".join(l for l in lines if l.startswith("#"))
    else:
        header = ("# chrome_binding.yaml — 지정 크롬 아이콘(.lnk) ↔ 자동화 채널 바인딩 (SSOT · 실데이터)\n"
                  "# 스키마·작성법 → .claude/skills/chrome-bind/SKILL.md · 빈 양식 → templates/chrome_binding.template.yaml\n")
    body = yaml.safe_dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False)
    BINDING_FILE.write_text(header + "\n" + body, encoding="utf-8")


# ── 동작 ─────────────────────────────────────────────────────────────────────
def cdp_alive(port: int) -> bool:
    s = socket.socket(); s.settimeout(1)
    try:
        s.connect(("127.0.0.1", port)); return True
    except Exception:
        return False
    finally:
        s.close()


def do_set(lnk: str, channel: str, port_opt: int | None) -> dict:
    out = {"action": "set", "channel": channel, "shortcut": lnk}
    p = Path(lnk)
    if not p.exists():
        out["status"] = "lnk_not_found"; return out
    info = read_lnk(lnk)
    parsed = parse_args_str(info.get("args") or "")
    out["lnk"] = {"target": info.get("target"), **parsed}
    if "chrome" not in (info.get("target") or "").lower():
        out["status"] = "not_chrome_lnk"
        out["warning"] = "대상이 chrome.exe 가 아님 — 크롬 바로가기를 지정할 것"
        return out
    if not parsed["port"] or not parsed["user_data_dir"]:
        # 포트/프로필 없는 일반 아이콘 → 채널 기본값 주입(백업 후)
        fb = FALLBACKS.get(channel, FALLBACKS["krs"])
        port = port_opt or parsed["port"] or fb["port"]
        udd = parsed["user_data_dir"] or fb["user_data_dir"]
        bak = BACKUP_DIR / (p.name + ".bak")
        if not bak.exists():
            bak.write_bytes(p.read_bytes())
        new_args = f'--remote-debugging-port={port} {STD_FLAGS} --user-data-dir="{udd}"'
        write_lnk(lnk, info.get("target") or CHROME, new_args,
                  f"chrome-bind 채널 {channel} — 자동화 공용 창(port {port}). 원복: {bak}")
        out["injected"] = {"port": port, "user_data_dir": udd, "backup": str(bak)}
        parsed = {"port": port, "user_data_dir": udd}
    data = load_yaml()
    prev = (data.get("channels") or {}).get(channel) or {}
    data.setdefault("channels", {})[channel] = {
        **prev,  # 기존 부가 필드(account 등) 보존 — set 재실행이 계정 규칙을 지우지 않게
        "shortcut": lnk.replace("\\", "/"),
        "port": parsed["port"],
        "user_data_dir": parsed["user_data_dir"].replace("\\", "/"),
        "set_at": time.strftime("%Y-%m-%d"),
    }
    save_yaml(data)
    out["binding"] = data["channels"][channel]
    out["status"] = "bound"
    return out


def do_status(channel: str | None) -> dict:
    data = load_yaml().get("channels") or {}
    chans = [channel] if channel else list(data.keys()) or ["krs"]
    out = {"action": "status", "channels": {}}
    for ch in chans:
        b = resolve(ch)
        st = {"binding": b}
        lnk = (data.get(ch) or {}).get("shortcut")
        if lnk:
            if Path(lnk).exists():
                try:
                    cur = parse_args_str(read_lnk(lnk).get("args") or "")
                    st["lnk_match"] = (cur.get("port") == b["port"]
                                       and (cur.get("user_data_dir") or "").replace("\\", "/") == b["user_data_dir"].replace("\\", "/"))
                    if not st["lnk_match"]:
                        st["warning"] = f"아이콘 인수가 바인딩과 다름(누가 바꿈?): {cur} — set 으로 재지정 필요"
                except Exception as e:
                    st["warning"] = f".lnk 읽기 실패: {e}"
            else:
                st["warning"] = "지정 아이콘(.lnk) 없음 — set 으로 재지정 필요"
        st["cdp_alive"] = cdp_alive(b["port"])
        if st["cdp_alive"]:
            try:
                from playwright.sync_api import sync_playwright
                with sync_playwright() as pw:
                    br = pw.chromium.connect_over_cdp(f"http://localhost:{b['port']}")
                    cookies = br.contexts[0].cookies(["https://eclass.krs.co.kr"])
                    dev = next((c for c in cookies if c["name"] == "DEVICE_AUTH"), None)
                    st["device_auth"] = ({"present": True,
                                          "expires": time.strftime("%Y-%m-%d", time.localtime(dev["expires"]))}
                                         if dev and dev.get("expires", -1) > 0 else {"present": bool(dev)})
                    br.close()
            except Exception as e:
                st["device_auth"] = f"확인 실패({type(e).__name__})"
        out["channels"][ch] = st
    return out


def do_launch(channel: str) -> dict:
    b = resolve(channel)
    out = {"action": "launch", "channel": channel, "binding": b}
    if cdp_alive(b["port"]):
        out["status"] = "reused"; return out
    Path(b["user_data_dir"]).mkdir(parents=True, exist_ok=True)
    args = [CHROME, f"--remote-debugging-port={b['port']}", "--remote-allow-origins=*",
            "--no-first-run", "--no-default-browser-check", "--ignore-certificate-errors",
            f"--user-data-dir={b['user_data_dir']}", "about:blank"]
    subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
    deadline = time.time() + 25
    while time.time() < deadline:
        if cdp_alive(b["port"]):
            out["status"] = "launched"; return out
        time.sleep(0.3)
    out["status"] = "launch_failed"
    return out


def main():
    ap = argparse.ArgumentParser(description="크롬 아이콘 지정 → 자동화 바인딩(chrome_binding.yaml) 관리")
    ap.add_argument("action", choices=["set", "status", "launch", "resolve"])
    ap.add_argument("lnk", nargs="?", default=None, help="set: 지정할 크롬 바로가기(.lnk) 경로")
    ap.add_argument("--channel", default="krs", help="채널(krs=KRS 자동화 공용 · second=별도계정 · all=status 전 채널)")
    ap.add_argument("--port", type=int, default=None, help="set: 포트 없는 아이콘에 주입할 포트")
    a = ap.parse_args()
    if a.action == "set":
        if not a.lnk:
            print(json.dumps({"status": "need_lnk", "msg": "set <lnk 경로> 필요"}, ensure_ascii=False)); sys.exit(1)
        res = do_set(a.lnk, a.channel, a.port)
    elif a.action == "status":
        res = do_status(a.channel if a.channel != "all" else None)
    elif a.action == "launch":
        res = do_launch(a.channel)
    else:
        res = {"action": "resolve", "channel": a.channel, **resolve(a.channel)}
    print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
