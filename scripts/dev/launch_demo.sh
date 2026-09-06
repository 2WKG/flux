#!/usr/bin/env bash
# Serve the bundled static demo or an explicitly supplied read-only local API.
# This helper never creates data, calls a provider, or publishes a service.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/dev/launch_demo.sh [--offline | --live --duckdb PATH]
       [--api-port PORT] [--web-port PORT] [--run-dir PATH] [--skip-install] [--stop]
EOF
}

mode=offline
duckdb_path=""
api_port=8031
web_port=4317
run_dir="${TMPDIR:-/tmp}/flux-demo-launch-${USER:-user}"
skip_install=0
stop_only=0

while (($#)); do
  case "$1" in
    --offline) mode=offline ;;
    --live) mode=live ;;
    --duckdb) duckdb_path="${2:?--duckdb requires a path}"; shift ;;
    --api-port) api_port="${2:?--api-port requires a number}"; shift ;;
    --web-port) web_port="${2:?--web-port requires a number}"; shift ;;
    --run-dir) run_dir="${2:?--run-dir requires a path}"; shift ;;
    --skip-install) skip_install=1 ;;
    --stop) stop_only=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

case "$api_port:$web_port" in *[!0-9:]*|:*|*::*) echo "Ports must be numeric." >&2; exit 2;; esac
if [[ "$mode" == offline && -n "$duckdb_path" ]]; then echo "--duckdb is only valid with --live." >&2; exit 2; fi
if [[ "$mode" == live && -z "$duckdb_path" ]]; then echo "--live requires --duckdb PATH; this helper never creates a database." >&2; exit 2; fi
if [[ "$mode" == live && (! -f "$duckdb_path" || ! -r "$duckdb_path") ]]; then echo "Live database is not a readable file: $duckdb_path" >&2; exit 2; fi

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
run_dir="$(mkdir -p "$run_dir" && cd "$run_dir" && pwd)"
api_pid_file="$run_dir/api.pid"
web_pid_file="$run_dir/web.pid"

stop_pid_file() {
  local file="$1" pid
  [[ -f "$file" ]] || return 0
  pid="$(<"$file")"
  if [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null; then kill "$pid"; fi
  rm -f "$file"
}

if ((stop_only)); then stop_pid_file "$api_pid_file"; stop_pid_file "$web_pid_file"; exit 0; fi
for command in uv npm node curl; do command -v "$command" >/dev/null || { echo "Required command is unavailable: $command" >&2; exit 1; }; done
if [[ -f "$api_pid_file" || -f "$web_pid_file" ]]; then echo "Run directory already contains recorded PIDs. Use --stop first: $run_dir" >&2; exit 1; fi
port_free() { node -e 'const net=require("net");const s=net.createServer();s.once("error",()=>process.exit(1));s.listen(Number(process.argv[1]),"127.0.0.1",()=>s.close(()=>process.exit(0)));' "$1"; }
port_free "$web_port" || { echo "Web port is already in use: $web_port" >&2; exit 1; }
if [[ "$mode" == live ]]; then port_free "$api_port" || { echo "API port is already in use: $api_port" >&2; exit 1; }; fi

if (( ! skip_install )); then (cd "$repo" && uv sync --frozen --extra dev); npm --prefix "$repo/web" ci; fi
npm --prefix "$repo/web" run build

wait_for_http() { for _ in {1..120}; do curl --silent --fail --max-time 1 "$1" >/dev/null && return 0; sleep 0.5; done; return 1; }
successful=0
cleanup() { if (($? != 0 && successful == 0)); then stop_pid_file "$api_pid_file"; stop_pid_file "$web_pid_file"; fi; }
trap cleanup EXIT

if [[ "$mode" == live ]]; then
  (cd "$repo" && DUCKDB_PATH="$duckdb_path" uv run uvicorn copilot.app:app --host 127.0.0.1 --port "$api_port") >"$run_dir/api.log" 2>&1 &
  echo $! >"$api_pid_file"
  wait_for_http "http://127.0.0.1:$api_port/health" || { echo "API did not start; see $run_dir/api.log" >&2; exit 1; }
fi
(
  cd "$repo/web"
  PORT="$web_port" node server.mjs
) >"$run_dir/web.log" 2>&1 &
echo $! >"$web_pid_file"
wait_for_http "http://127.0.0.1:$web_port/" || { echo "Web app did not start; see $run_dir/web.log" >&2; exit 1; }

shell_code="$(curl --silent --output "$run_dir/index.html" --write-out '%{http_code}' "http://127.0.0.1:$web_port/")"
asset_code="$(curl --silent --output "$run_dir/app.js" --write-out '%{http_code}' "http://127.0.0.1:$web_port/assets/app.js")"
[[ "$shell_code" == 200 && "$asset_code" == 200 ]] || { echo "Expected web shell and app asset, got shell=$shell_code asset=$asset_code" >&2; exit 1; }
if [[ "$mode" == live ]]; then
  api_code="$(curl --silent --output "$run_dir/api-layers.json" --write-out '%{http_code}' "http://127.0.0.1:$api_port/layers/buses")"
  node -e 'JSON.parse(require("fs").readFileSync(process.argv[1], "utf8"))' "$run_dir/api-layers.json" || { echo "API did not return JSON (HTTP $api_code)." >&2; exit 1; }
  [[ "$api_code" == 200 || "$api_code" == 503 ]] || { echo "API returned unexpected HTTP $api_code." >&2; exit 1; }
fi

successful=1
trap - EXIT
echo "Flux $mode demo ready: http://127.0.0.1:$web_port/"
echo "Logs and PIDs: $run_dir"
echo "Stop only these recorded processes: $0 --run-dir '$run_dir' --stop"
