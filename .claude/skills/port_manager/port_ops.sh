#!/usr/bin/env bash
# port_ops.sh — port_manager 스킬의 저수준 유틸리티
#
# 사용법:
#   port_ops.sh list <project>                       # 프로젝트의 행 출력 (TSV: 포트\t서비스\t시작명령\t작업디렉토리)
#   port_ops.sh list_all                             # port_list.md 전체 표 출력
#   port_ops.sh has   <project> <port>               # 행 존재 시 exit 0, 없으면 exit 1
#   port_ops.sh add   <project> <port> <service> <cmd> <cwd>   # 행 추가 (존재하면 오류)
#   port_ops.sh update <project> <port> <service> <cmd> <cwd>  # 같은 (project,port) 행 갱신 (없으면 오류)
#   port_ops.sh remove <project> <port>              # 행 삭제 (없으면 NOT_FOUND)
#   port_ops.sh status <port>                        # "RUNNING <pid>" 또는 "STOPPED"
#   port_ops.sh kill <port>                          # 포트의 LISTEN 프로세스 종료. "KILLED <pid>" 또는 "NOT_RUNNING"
#   port_ops.sh start <port> <cwd> <cmd...>          # cwd로 cd 후 cmd를 백그라운드 실행, 로그파일 경로 출력
#   port_ops.sh restart <port> <cwd> <cmd...>        # kill + start
#   port_ops.sh discover [project_root]              # 현재 프로젝트에 속한 LISTEN 서버 자동발견. TSV: 포트\tPID\t시작명령\t작업디렉토리
#   port_ops.sh inspect  [project_root]              # 프로젝트 내부 설정 파일에서 선언된 서버 추출 (실행 여부 무관). TSV: source\t이름\t포트\t시작명령\t작업디렉토리. 미상 필드는 "—"
#
# 환경변수:
#   PORT_LIST   port_list.md 경로 (기본: 스크립트와 같은 폴더의 port_list.md)
#   PROJECT_ROOT  start 시 cwd 기준 루트 (기본: $PWD)
#   LOG_DIR     백그라운드 로그 디렉토리 (기본: /tmp/port_manager)

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PORT_LIST="${PORT_LIST:-$SCRIPT_DIR/port_list.md}"
PROJECT_ROOT="${PROJECT_ROOT:-$PWD}"
LOG_DIR="${LOG_DIR:-/tmp/port_manager}"
mkdir -p "$LOG_DIR"

die() { echo "port_ops: $*" >&2; exit 2; }

list_rows() {
  local project="$1"
  [ -f "$PORT_LIST" ] || die "port_list.md not found: $PORT_LIST"
  awk -F'|' -v proj="$project" '
    /^\|/ {
      f1=$2; gsub(/^[ \t]+|[ \t]+$/,"",f1)
      if (f1 == proj) {
        for (i=2; i<=NF; i++) gsub(/^[ \t]+|[ \t]+$/,"",$i)
        # 출력: 포트\t서비스\t시작명령\t작업디렉토리
        print $3 "\t" $4 "\t" $5 "\t" $6
      }
    }
  ' "$PORT_LIST"
}

list_all_rows() {
  [ -f "$PORT_LIST" ] || die "port_list.md not found: $PORT_LIST"
  cat "$PORT_LIST"
}

ensure_list() {
  if [ ! -f "$PORT_LIST" ]; then
    mkdir -p "$(dirname "$PORT_LIST")"
    {
      echo "# 프로젝트 서버·포트·실행명령 할당"
      echo
      echo "본 표는 \`/port_manager\` 가 읽는 단일 출처(SSOT)다. 한 행 = 한 서버 정의."
      echo
      echo "| 프로젝트 | 포트 | 서비스 | 시작명령 | 작업디렉토리 |"
      echo "|---------|------|-------|---------|------------|"
    } > "$PORT_LIST"
  fi
}

has_row() {
  local project="$1" port="$2"
  [ -f "$PORT_LIST" ] || return 1
  awk -F'|' -v proj="$project" -v p="$port" '
    /^\|/ {
      f1=$2; gsub(/^[ \t]+|[ \t]+$/,"",f1)
      f2=$3; gsub(/^[ \t]+|[ \t]+$/,"",f2)
      if (f1 == proj && f2 == p) { found=1; exit }
    }
    END { exit (found ? 0 : 1) }
  ' "$PORT_LIST"
}

# 셀 안에서 파이프(|)와 백슬래시는 마크다운 표를 깨므로 이스케이프한다.
# (실제 사용에서는 거의 발생하지 않지만 방어용)
sanitize_cell() {
  local v="$1"
  v="${v//\\/\\\\}"
  v="${v//|/\\|}"
  if [ -z "$v" ]; then v="—"; fi
  printf '%s' "$v"
}

cmd_add() {
  local project="$1" port="$2" service="$3" cmd_="$4" cwd_="$5"
  [ -n "$project" ] && [ -n "$port" ] || die "add: project and port required"
  ensure_list
  if has_row "$project" "$port"; then
    die "row already exists: $project:$port (use 'update')"
  fi
  printf '| %s | %s | %s | %s | %s |\n' \
    "$(sanitize_cell "$project")" \
    "$(sanitize_cell "$port")" \
    "$(sanitize_cell "$service")" \
    "$(sanitize_cell "$cmd_")" \
    "$(sanitize_cell "$cwd_")" \
    >> "$PORT_LIST"
  echo "ADDED $project $port"
}

cmd_update() {
  local project="$1" port="$2" service="$3" cmd_="$4" cwd_="$5"
  [ -n "$project" ] && [ -n "$port" ] || die "update: project and port required"
  has_row "$project" "$port" || die "no such row: $project:$port (use 'add')"
  local tmp; tmp="$(mktemp)"
  awk -F'|' -v proj="$project" -v p="$port" \
      -v s="$(sanitize_cell "$service")" \
      -v c="$(sanitize_cell "$cmd_")" \
      -v w="$(sanitize_cell "$cwd_")" '
    /^\|/ {
      f1=$2; gsub(/^[ \t]+|[ \t]+$/,"",f1)
      f2=$3; gsub(/^[ \t]+|[ \t]+$/,"",f2)
      if (f1 == proj && f2 == p) {
        printf "| %s | %s | %s | %s | %s |\n", proj, p, s, c, w
        next
      }
    }
    { print }
  ' "$PORT_LIST" > "$tmp" && mv "$tmp" "$PORT_LIST"
  echo "UPDATED $project $port"
}

cmd_remove() {
  local project="$1" port="$2"
  [ -n "$project" ] && [ -n "$port" ] || die "remove: project and port required"
  if ! has_row "$project" "$port"; then
    echo "NOT_FOUND $project $port"; return 0
  fi
  local tmp; tmp="$(mktemp)"
  awk -F'|' -v proj="$project" -v p="$port" '
    /^\|/ {
      f1=$2; gsub(/^[ \t]+|[ \t]+$/,"",f1)
      f2=$3; gsub(/^[ \t]+|[ \t]+$/,"",f2)
      if (f1 == proj && f2 == p) next
    }
    { print }
  ' "$PORT_LIST" > "$tmp" && mv "$tmp" "$PORT_LIST"
  echo "REMOVED $project $port"
}

find_pid() {
  local port="$1" pid=""
  if command -v ss >/dev/null 2>&1; then
    pid="$(ss -tlnpH "sport = :$port" 2>/dev/null \
      | grep -oP 'pid=\K[0-9]+' | head -1 || true)"
  fi
  if [ -z "$pid" ] && command -v lsof >/dev/null 2>&1; then
    pid="$(lsof -ti tcp:"$port" -sTCP:LISTEN 2>/dev/null | head -1 || true)"
  fi
  if [ -z "$pid" ] && command -v fuser >/dev/null 2>&1; then
    pid="$(fuser -n tcp "$port" 2>/dev/null | tr -s ' \t' '\n' | grep -E '^[0-9]+$' | head -1 || true)"
  fi
  printf '%s' "$pid"
}

cmd_status() {
  local port="$1"
  local pid; pid="$(find_pid "$port")"
  if [ -n "$pid" ]; then
    echo "RUNNING $pid"
  else
    echo "STOPPED"
  fi
}

cmd_kill() {
  local port="$1"
  local pid; pid="$(find_pid "$port")"
  if [ -z "$pid" ]; then
    echo "NOT_RUNNING"
    return 0
  fi
  kill "$pid" 2>/dev/null || true
  for _ in 1 2 3 4 5; do
    sleep 0.4
    [ -z "$(find_pid "$port")" ] && { echo "KILLED $pid"; return 0; }
  done
  kill -9 "$pid" 2>/dev/null || true
  sleep 0.4
  if [ -z "$(find_pid "$port")" ]; then
    echo "KILLED $pid"
  else
    echo "KILL_FAILED $pid"
    return 1
  fi
}

cmd_start() {
  local port="$1"; shift
  local cwd_rel="$1"; shift
  local cmd=("$@")
  local cwd
  if [ "$cwd_rel" = "—" ] || [ -z "$cwd_rel" ]; then
    cwd="$PROJECT_ROOT"
  elif [[ "$cwd_rel" = /* ]]; then
    cwd="$cwd_rel"
  else
    cwd="$PROJECT_ROOT/$cwd_rel"
  fi
  [ -d "$cwd" ] || die "cwd not found: $cwd"
  local proj_slug; proj_slug="$(basename "$PROJECT_ROOT" | tr -c 'A-Za-z0-9_-' '_')"
  local log="$LOG_DIR/${proj_slug}-${port}.log"
  : > "$log"
  ( cd "$cwd" && nohup bash -lc "${cmd[*]}" >>"$log" 2>&1 & echo $! >"$LOG_DIR/${proj_slug}-${port}.pid" ) &
  wait
  local launched_pid; launched_pid="$(cat "$LOG_DIR/${proj_slug}-${port}.pid" 2>/dev/null || true)"
  echo "STARTED pid=${launched_pid:-?} log=$log"
}

cmd_restart() {
  local port="$1"; shift
  local cwd_rel="$1"; shift
  local cmd=("$@")
  cmd_kill "$port" || true
  cmd_start "$port" "$cwd_rel" "${cmd[@]}"
}

# 주어진 pid가 project_root 안의 프로세스인지(또는 그 부모가) 검사.
# 매치 시 stdout 에 "<cwd>\t<cmdline>" 을 출력하고 0, 아니면 1.
# 최대 4 hop 까지 부모로 올라가며 (npm run dev → next-server 같은 자식 spawn 처리).
proc_belongs_to_project() {
  local pid="$1" root="$2"
  local hops=0 max_hops=4
  local cwd cmd ppid
  while [ -n "$pid" ] && [ "$pid" -gt 0 ] 2>/dev/null && [ "$hops" -lt "$max_hops" ] && [ -d "/proc/$pid" ]; do
    cwd="$(readlink "/proc/$pid/cwd" 2>/dev/null || true)"
    cmd="$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null | sed 's/[[:space:]]*$//' || true)"
    if [ -n "$cwd" ] && { [ "$cwd" = "$root" ] || [ "${cwd#$root/}" != "$cwd" ]; }; then
      printf '%s\t%s\n' "$cwd" "$cmd"
      return 0
    fi
    case "$cmd" in
      *"$root"*) printf '%s\t%s\n' "${cwd:-$root}" "$cmd"; return 0 ;;
    esac
    ppid="$(awk '/^PPid:/ {print $2; exit}' "/proc/$pid/status" 2>/dev/null || true)"
    [ -z "$ppid" ] && return 1
    [ "$ppid" = "$pid" ] && return 1
    pid="$ppid"
    hops=$((hops+1))
  done
  return 1
}

cmd_discover() {
  local root="${1:-$PROJECT_ROOT}"
  [ -n "$root" ] || die "discover: project_root required (or set PROJECT_ROOT)"
  if [ -d "$root" ]; then
    root="$(cd "$root" && pwd -P)"
  fi
  command -v ss >/dev/null 2>&1 || die "ss not available (install iproute2)"

  # ss -tlnpH: state recv send local_addr peer_addr "users:((..,pid=PID,fd=..))"
  # 한 줄씩 처리. pipe-while 안에서 stdout 만 사용해 누적.
  local seen=""
  while IFS= read -r line; do
    [ -z "$line" ] && continue
    local laddr port pids pid match_out cwd cmd cwd_rel
    laddr="$(awk '{print $4}' <<<"$line")"
    port="${laddr##*:}"
    case "$port" in ''|*[!0-9]*) continue ;; esac

    # 한 LISTEN 소켓에 pid 가 여러 개 나올 수 있음 (worker fork). 모두 검사.
    pids="$(grep -oE 'pid=[0-9]+' <<<"$line" 2>/dev/null | awk -F= '{print $2}' | sort -u || true)"
    [ -z "$pids" ] && continue

    for pid in $pids; do
      # 이미 보고한 (port,pid) 조합이면 skip
      case " $seen " in *" ${port}:${pid} "*) continue ;; esac
      if match_out="$(proc_belongs_to_project "$pid" "$root")"; then
        cwd="${match_out%%	*}"
        cmd="${match_out#*	}"
        if [ "$cwd" = "$root" ]; then
          cwd_rel="—"
        elif [ "${cwd#$root/}" != "$cwd" ]; then
          cwd_rel="${cwd#$root/}"
        else
          cwd_rel="$cwd"
        fi
        printf '%s\t%s\t%s\t%s\n' "$port" "$pid" "$cmd" "$cwd_rel"
        seen="$seen ${port}:${pid}"
        break
      fi
    done
  done < <(ss -tlnpH 2>/dev/null)
  return 0
}

# inspect <project_root>
# 프로젝트 루트 내부의 알려진 설정 파일을 스캔해 "선언된 서버"를 출력한다.
# 출력 TSV: source\tname\tport\tcommand\tcwd_rel
# 미상 필드는 "—".
cmd_inspect() {
  local root="${1:-$PROJECT_ROOT}"
  [ -n "$root" ] || die "inspect: project_root required (or set PROJECT_ROOT)"
  [ -d "$root" ] || die "inspect: directory not found: $root"
  root="$(cd "$root" && pwd -P)"
  command -v python3 >/dev/null 2>&1 || die "python3 not available"

  python3 - "$root" <<'PYEOF'
import json, os, re, sys, urllib.parse

root = sys.argv[1]
results = []  # (source, name, port, cmd, cwd_rel)

def rel(cwd):
    if not cwd or cwd == "—":
        return "—"
    abs_cwd = os.path.abspath(os.path.join(root, cwd)) if not os.path.isabs(cwd) else cwd
    if abs_cwd == root:
        return "—"
    if abs_cwd.startswith(root + os.sep):
        return abs_cwd[len(root) + 1:]
    return cwd  # 외부 경로 그대로

def port_from_url(url):
    try:
        p = urllib.parse.urlsplit(url)
        if p.port:
            return str(p.port)
    except Exception:
        pass
    m = re.search(r":(\d{2,5})(?:/|$)", url or "")
    return m.group(1) if m else "—"

def scan_mcp_like(path, source):
    if not os.path.isfile(path):
        return
    try:
        data = json.load(open(path, encoding="utf-8"))
    except Exception:
        return
    servers = data.get("servers") or data.get("mcpServers") or {}
    if not isinstance(servers, dict):
        return
    for name, sv in servers.items():
        if not isinstance(sv, dict):
            continue
        port = "—"
        if sv.get("url"):
            port = port_from_url(sv["url"])
        elif sv.get("port"):
            port = str(sv["port"])
        parts = []
        if sv.get("command"):
            parts.append(sv["command"])
        for a in sv.get("args") or []:
            parts.append(str(a))
        cmd = " ".join(parts) if parts else "—"
        cwd = rel(sv.get("cwd"))
        results.append((source, name, port, cmd, cwd))

def scan_launchers(path, source):
    if not os.path.isfile(path):
        return
    try:
        data = json.load(open(path, encoding="utf-8"))
    except Exception:
        return
    launchers = data.get("launchers") or {}
    if not isinstance(launchers, dict):
        return
    for name, cfg in launchers.items():
        if not isinstance(cfg, dict):
            continue
        parts = []
        if cfg.get("command"):
            parts.append(cfg["command"])
        for a in cfg.get("args") or []:
            parts.append(str(a))
        cmd = " ".join(parts) if parts else "—"
        cwd = rel(cfg.get("cwd"))
        port = str(cfg["port"]) if cfg.get("port") else "—"
        results.append((source, name, port, cmd, cwd))

scan_mcp_like(os.path.join(root, ".vscode", "mcp.json"),  "vscode-mcp")
scan_mcp_like(os.path.join(root, ".cursor", "mcp.json"),  "cursor-mcp")
scan_mcp_like(os.path.join(root, ".mcp.json"),            "mcp-json")
scan_mcp_like(os.path.join(root, "mcp.json"),             "mcp-json")
scan_mcp_like(os.path.join(root, "claude_desktop_config.json"), "claude-desktop")
scan_launchers(os.path.join(root, ".taskpilot", "mcp-launchers.json"), "taskpilot-launcher")

# Deep inspect: 포트가 미상(—)인 행에 대해 cmd 에서 스크립트 파일을 찾아 그 안에서 포트 리터럴을 grep 한다.
SCRIPT_EXT = re.compile(r"\.(py|js|ts|mjs|cjs|sh)$", re.I)
PORT_PATTERNS = [
    re.compile(r"uvicorn\.run\([^)]*port\s*=\s*(\d{2,5})"),
    re.compile(r"app\.run\([^)]*port\s*=\s*(\d{2,5})"),
    re.compile(r"\.listen\(\s*(\d{2,5})"),
    re.compile(r"createServer\([^)]*\)\.listen\(\s*(\d{2,5})"),
    re.compile(r"_PORT[\"']?\s*,\s*(\d{2,5})"),  # env var default like os.environ.get("MCP_SERVER_PORT", 8091)
    re.compile(r"--port[=\s]+(\d{2,5})"),
    re.compile(r"\bPORT\s*[:=]\s*(?:int\s*\(\s*)?(\d{2,5})"),
    re.compile(r"\bport\s*[:=]\s*(?:int\s*\(\s*)?(\d{2,5})"),
]

def deep_port_lookup(cwd_rel, cmd):
    if not cmd or cmd == "—":
        return None
    # cmd 토큰에서 스크립트로 보이는 파일 찾기
    script = None
    for tok in cmd.split():
        if SCRIPT_EXT.search(tok):
            script = tok
            break
    if not script:
        return None
    # cwd 해석: 상대면 root + cwd_rel + script, 절대면 그대로
    if os.path.isabs(script):
        candidates = [script]
    else:
        bases = []
        if cwd_rel and cwd_rel != "—":
            bases.append(cwd_rel if os.path.isabs(cwd_rel) else os.path.join(root, cwd_rel))
        bases.append(root)
        candidates = [os.path.join(b, script) for b in bases]
    for path in candidates:
        if not os.path.isfile(path):
            continue
        try:
            text = open(path, "r", encoding="utf-8", errors="ignore").read()
        except Exception:
            continue
        for pat in PORT_PATTERNS:
            m = pat.search(text)
            if m:
                p = int(m.group(1))
                if 1024 <= p <= 65535:
                    return str(p)
    return None

deep_resolved = []
for src, name, port, cmd, cwd in results:
    if port == "—":
        found = deep_port_lookup(cwd, cmd)
        if found:
            port = found
            src = src + "+deep"
    deep_resolved.append((src, name, port, cmd, cwd))

for r in deep_resolved:
    print("\t".join(str(x) for x in r))
PYEOF
}

main() {
  local sub="${1:-}"; shift || true
  case "$sub" in
    list)     [ $# -ge 1 ] || die "usage: list <project>";     list_rows "$1" ;;
    list_all) list_all_rows ;;
    has)      [ $# -ge 2 ] || die "usage: has <project> <port>";    has_row "$1" "$2" && echo "YES" || { echo "NO"; exit 1; } ;;
    add)      [ $# -ge 5 ] || die "usage: add <project> <port> <service> <cmd> <cwd>";    cmd_add "$@" ;;
    update)   [ $# -ge 5 ] || die "usage: update <project> <port> <service> <cmd> <cwd>"; cmd_update "$@" ;;
    remove)   [ $# -ge 2 ] || die "usage: remove <project> <port>";  cmd_remove "$@" ;;
    status)   [ $# -ge 1 ] || die "usage: status <port>";      cmd_status "$1" ;;
    kill)     [ $# -ge 1 ] || die "usage: kill <port>";        cmd_kill "$1" ;;
    start)    [ $# -ge 3 ] || die "usage: start <port> <cwd> <cmd...>";   cmd_start "$@" ;;
    restart)  [ $# -ge 3 ] || die "usage: restart <port> <cwd> <cmd...>"; cmd_restart "$@" ;;
    discover) cmd_discover "${1:-}" ;;
    inspect)  cmd_inspect "${1:-}" ;;
    ""|help|-h|--help)
      awk 'NR==1 {next} /^#/ || /^[[:space:]]*$/ {print; next} {exit}' "$0"
      ;;
    *) die "unknown subcommand: $sub" ;;
  esac
}

main "$@"
