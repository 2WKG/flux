#!/usr/bin/env bash
# Start the Flux demo in an explicit offline or live local mode.
#
# This script never creates a database, calls a model provider, or publishes a
# service. It keeps the API and web logs/PIDs in one caller-chosen run directory
# so a morning demo can be checked and stopped without guessing which process
# owns a port.

set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  scripts/dev/launch_demo.sh [--offline | --live --duckdb PATH]
                             [--api-port PORT] [--web-port PORT]
                             [--run-dir PATH] [--skip-install] [--stop]
                             [--persist | --remove-persist]

Modes:
  --offline                 Build and start the web app alone (default). The
                            app must expose its named unavailable agent state.
  --live --duckdb PATH      Require an existing readable DuckDB file, start the
                            local API and same-origin web proxy, then verify
                            health and an allowlisted proxy response.
  --persist                 Install and start the explicit macOS user LaunchAgent
                            `com.fluxdemo.local` for a live launch. It owns only
                            the selected Flux API and web ports.
  --remove-persist          Unload and remove that LaunchAgent; it does not touch
                            any other local process or service.

The helper does not create a database, contact a provider, expose a public URL,
or change Cloudflare. --stop only terminates PIDs previously recorded by this
helper in --run-dir.
EOF
}

mode="offline"
duckdb_path=""
api_port=8031
web_port=4317
run_dir="${TMPDIR:-/tmp}/flux-demo-launch-${USER:-user}"
skip_install=0
stop_only=0
persist=0
remove_persist=0

while (($#)); do
  case "$1" in
    --offline) mode="offline" ;;
    --live) mode="live" ;;
    --duckdb) duckdb_path="${2:?--duckdb requires a path}"; shift ;;
    --api-port) api_port="${2:?--api-port requires a number}"; shift ;;
    --web-port) web_port="${2:?--web-port requires a number}"; shift ;;
    --run-dir) run_dir="${2:?--run-dir requires a path}"; shift ;;
    --skip-install) skip_install=1 ;;
    --stop) stop_only=1 ;;
    --persist) persist=1 ;;
    --remove-persist) remove_persist=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

case "$api_port:$web_port" in
  *[!0-9:]*|:*|*::*) echo "Ports must be numeric." >&2; exit 2 ;;
esac
if ((persist && remove_persist)); then
  echo "Choose only one of --persist and --remove-persist." >&2
  exit 2
fi
if ((persist)) && [[ "$mode" != "live" ]]; then
  echo "--persist requires --live --duckdb PATH." >&2
  exit 2
fi
if [[ "$mode" == "offline" && -n "$duckdb_path" ]]; then
  echo "--duckdb is only valid with --live." >&2
  exit 2
fi
if [[ "$mode" == "live" && -z "$duckdb_path" ]]; then
  echo "--live requires --duckdb PATH; this helper never creates a database." >&2
  exit 2
fi
if [[ "$mode" == "live" && (! -f "$duckdb_path" || ! -r "$duckdb_path") ]]; then
  echo "Live database is not a readable file: $duckdb_path" >&2
  exit 2
fi

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
run_dir="$(mkdir -p "$run_dir" && cd "$run_dir" && pwd)"
api_pid_file="$run_dir/api.pid"
web_pid_file="$run_dir/web.pid"
flux_user_home="${HOME:?HOME is required for user LaunchAgent installation}"
launch_agents_dir="$flux_user_home/Library/LaunchAgents"
launch_logs_dir="$flux_user_home/Library/Logs/FluxDemo"
launch_label="com.fluxdemo.local"
launch_plist="$launch_agents_dir/$launch_label.plist"
launch_domain="gui/$(id -u)"

stop_pid_file() {
  local file="$1"
  [[ -f "$file" ]] || return 0
  local pid
  pid="$(<"$file")"
  if [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null; then
    kill "$pid"
    echo "Stopped PID $pid from $file"
  fi
  rm -f "$file"
}

remove_persistent_service() {
  command -v launchctl >/dev/null || { echo "launchctl is required on macOS." >&2; exit 1; }
  launchctl bootout "$launch_domain/$launch_label" 2>/dev/null || true
  rm -f "$launch_plist"
  echo "Removed user-owned $launch_label LaunchAgent."
}

install_persistent_service() {
  command -v launchctl >/dev/null || { echo "launchctl is required on macOS." >&2; exit 1; }
  local uv_bin node_bin
  uv_bin="$(command -v uv)"
  node_bin="$(command -v node)"
  mkdir -p "$launch_agents_dir" "$launch_logs_dir"
  cat >"$launch_plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$launch_label</string>
  <key>ProgramArguments</key><array><string>$repo/scripts/dev/flux_demo_service.sh</string></array>
  <key>WorkingDirectory</key><string>$repo</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
  <key>EnvironmentVariables</key><dict>
    <key>FLUX_DEMO_DUCKDB_PATH</key><string>$duckdb_path</string>
    <key>FLUX_DEMO_API_PORT</key><string>$api_port</string>
    <key>FLUX_DEMO_WEB_PORT</key><string>$web_port</string>
    <key>FLUX_DEMO_LOG_DIR</key><string>$launch_logs_dir</string>
    <key>FLUX_DEMO_UV_BIN</key><string>$uv_bin</string>
    <key>FLUX_DEMO_NODE_BIN</key><string>$node_bin</string>
  </dict>
  <key>StandardOutPath</key><string>$launch_logs_dir/launchd.out.log</string>
  <key>StandardErrorPath</key><string>$launch_logs_dir/launchd.err.log</string>
</dict></plist>
EOF
  plutil -lint "$launch_plist" >/dev/null
  launchctl bootout "$launch_domain/$launch_label" 2>/dev/null || true
  launchctl bootstrap "$launch_domain" "$launch_plist"
  launchctl kickstart -k "$launch_domain/$launch_label"
  echo "Installed $launch_label. Logs: $launch_logs_dir"
}

if ((remove_persist)); then
  remove_persistent_service
  exit 0
fi

if ((stop_only)); then
  stop_pid_file "$api_pid_file"
  stop_pid_file "$web_pid_file"
  exit 0
fi

for command in uv npm node curl; do
  command -v "$command" >/dev/null || { echo "Required command is unavailable: $command" >&2; exit 1; }
done
if [[ -f "$api_pid_file" || -f "$web_pid_file" ]]; then
  echo "Run directory already contains recorded PIDs. Use --stop first: $run_dir" >&2
  exit 1
fi

port_free() {
  node -e 'const net=require("net");const server=net.createServer();server.once("error",()=>process.exit(1));server.listen(Number(process.argv[1]),"127.0.0.1",()=>server.close(()=>process.exit(0)));' "$1"
}
port_free "$web_port" || { echo "Web port is already in use: $web_port" >&2; exit 1; }
if [[ "$mode" == "live" ]]; then
  port_free "$api_port" || { echo "API port is already in use: $api_port" >&2; exit 1; }
fi

if (( ! skip_install )); then
  (cd "$repo" && uv sync --frozen --extra dev)
  npm --prefix "$repo/web" ci
fi
npm --prefix "$repo/web" run build

if ((persist)); then
  install_persistent_service
  echo "Verify independently: curl --fail http://127.0.0.1:$api_port/health"
  exit 0
fi

wait_for_http() {
  local url="$1"
  # A first `uv run` can need to initialize the locked environment. Keep this
  # bounded, but do not mistake that one-time setup for a failed API launch.
  for _ in {1..120}; do
    if curl --silent --fail --max-time 1 "$url" >/dev/null; then return 0; fi
    sleep 0.5
  done
  return 1
}

launch_succeeded=0
cleanup_on_exit() {
  local status=$?
  if ((status != 0 && launch_succeeded == 0)); then
    stop_pid_file "$api_pid_file"
    stop_pid_file "$web_pid_file"
  fi
}
trap cleanup_on_exit EXIT

if [[ "$mode" == "live" ]]; then
  (
    cd "$repo"
    DUCKDB_PATH="$duckdb_path" uv run uvicorn copilot.demo_app:app --host 127.0.0.1 --port "$api_port"
  ) >"$run_dir/api.log" 2>&1 &
  echo $! >"$api_pid_file"
  wait_for_http "http://127.0.0.1:$api_port/health" || {
    echo "API did not start; see $run_dir/api.log" >&2; exit 1;
  }
  health_code="$(curl --silent --output "$run_dir/health.json" --write-out '%{http_code}' "http://127.0.0.1:$api_port/health")"
  if [[ "$health_code" != "200" ]]; then
    echo "Live API health was HTTP $health_code; refusing to call this a live demo. See $run_dir/health.json" >&2
    exit 1
  fi
  (
    cd "$repo/web"
    PORT="$web_port" FLUX_API_ORIGIN="http://127.0.0.1:$api_port" node server.mjs
  ) >"$run_dir/web.log" 2>&1 &
else
  (
    cd "$repo/web"
    PORT="$web_port" node server.mjs
  ) >"$run_dir/web.log" 2>&1 &
fi
echo $! >"$web_pid_file"
wait_for_http "http://127.0.0.1:$web_port/" || {
  echo "Web app did not start; see $run_dir/web.log" >&2; exit 1;
}

shell_code="$(curl --silent --output "$run_dir/index.html" --write-out '%{http_code}' "http://127.0.0.1:$web_port/")"
asset_code="$(curl --silent --output "$run_dir/app.js" --write-out '%{http_code}' "http://127.0.0.1:$web_port/assets/app.js")"
[[ "$shell_code" == "200" && "$asset_code" == "200" ]] || {
  echo "Expected web shell and app asset, got shell=$shell_code asset=$asset_code" >&2; exit 1;
}
grep -q 'Not available in this offline build' "$run_dir/app.js" || {
  echo "Built client lacks the named offline-agent state." >&2; exit 1;
}

if [[ "$mode" == "live" ]]; then
  proxy_code="$(curl --silent --output "$run_dir/proxy-layers.json" --write-out '%{http_code}' "http://127.0.0.1:$web_port/layers/buses")"
  node -e 'JSON.parse(require("fs").readFileSync(process.argv[1], "utf8"))' "$run_dir/proxy-layers.json" || {
    echo "Allowlisted proxy route did not return JSON (HTTP $proxy_code)." >&2; exit 1;
  }
  [[ "$proxy_code" == "200" || "$proxy_code" == "503" ]] || {
    echo "Allowlisted proxy route returned unexpected HTTP $proxy_code." >&2; exit 1;
  }
fi

launch_succeeded=1
trap - EXIT
echo "Flux $mode demo ready: http://127.0.0.1:$web_port/"
echo "Logs and PIDs: $run_dir"
echo "Stop only these recorded processes: $0 --run-dir '$run_dir' --stop"
