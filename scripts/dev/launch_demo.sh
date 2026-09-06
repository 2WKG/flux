#!/usr/bin/env bash
# Serve the bundled static demo or an explicitly supplied read-only local API.
# This helper never creates data, calls a provider, or publishes a service.
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/dev/launch_demo.sh [--offline | --live --duckdb PATH]
       [--api-port PORT] [--web-port PORT] [--bind ADDR] [--run-dir PATH]
       [--ready-timeout SECONDS] [--skip-install] [--skip-build]
       [--status] [--stop]

  --bind ADDR           Interface both servers bind. Default 127.0.0.1 (loopback
                        only). Anything else publishes the demo to that network.
  --ready-timeout SEC   Seconds to wait for each server. Default 180; a cold
                        `uv run` creates a venv and installs before it serves.
  --skip-build          Reuse an existing web/dist/ instead of rebuilding.
  --status              Report the recorded processes and their listeners.
                        Exit 0 only when every recorded process is alive and
                        every recorded port is being answered.
  --stop                Stop the recorded processes, verify their ports are
                        released, and only then remove the PID files. Exit
                        non-zero if anything outlived the stop.
EOF
}

mode=offline
duckdb_path=""
api_port=8031
web_port=4317
bind_addr=127.0.0.1
run_dir="${TMPDIR:-/tmp}/flux-demo-launch-${USER:-user}"
skip_install=0
skip_build=0
stop_only=0
status_only=0
ready_timeout=180

while (($#)); do
  case "$1" in
    --offline) mode=offline ;;
    --live) mode=live ;;
    --duckdb) duckdb_path="${2:?--duckdb requires a path}"; shift ;;
    --api-port) api_port="${2:?--api-port requires a number}"; shift ;;
    --web-port) web_port="${2:?--web-port requires a number}"; shift ;;
    --bind) bind_addr="${2:?--bind requires an address}"; shift ;;
    --run-dir) run_dir="${2:?--run-dir requires a path}"; shift ;;
    --ready-timeout) ready_timeout="${2:?--ready-timeout requires a number}"; shift ;;
    --skip-install) skip_install=1 ;;
    --skip-build) skip_build=1 ;;
    --status) status_only=1 ;;
    --stop) stop_only=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

valid_port() { [[ "$1" =~ ^[0-9]+$ ]] && ((10#$1 >= 1 && 10#$1 <= 65535)); }
valid_port "$api_port" || { echo "Ports must be 1-65535: $api_port" >&2; exit 2; }
valid_port "$web_port" || { echo "Ports must be 1-65535: $web_port" >&2; exit 2; }
[[ "$ready_timeout" =~ ^[0-9]+$ ]] || { echo "--ready-timeout must be a whole number of seconds." >&2; exit 2; }
if [[ "$mode" == offline && -n "$duckdb_path" ]]; then echo "--duckdb is only valid with --live." >&2; exit 2; fi
if [[ "$mode" == live && -z "$duckdb_path" ]]; then echo "--live requires --duckdb PATH; this helper never creates a database." >&2; exit 2; fi
if [[ "$mode" == live && (! -f "$duckdb_path" || ! -r "$duckdb_path") ]]; then echo "Live database is not a readable file: $duckdb_path" >&2; exit 2; fi

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
run_dir="$(mkdir -p "$run_dir" && cd "$run_dir" && pwd)"
api_pid_file="$run_dir/api.pid"
web_pid_file="$run_dir/web.pid"
api_port_file="$run_dir/api.port"
web_port_file="$run_dir/web.port"

# `--stop` used to `kill` `$!`, which is the wrapper subshell (and for `--live`
# the `uv run` wrapper sits between that and uvicorn), so the listener survived
# a "successful" stop while its PID file was deleted — an orphan holding the
# DuckDB read handle with no command in the repo able to find it. Record the
# whole process group we started, and never drop the breadcrumb while it lives.
descendants() {
  local pid="$1" child
  for child in $(pgrep -P "$pid" 2>/dev/null || true); do
    printf '%s\n' "$child"
    descendants "$child"
  done
}

record_pids() {
  local file="$1" pid="$2"
  { printf '%s\n' "$pid"; descendants "$pid"; } >"$file"
}

read_pids() {
  local file="$1" pid
  [[ -f "$file" ]] || return 0
  while IFS= read -r pid; do
    [[ "$pid" =~ ^[0-9]+$ ]] && printf '%s\n' "$pid"
  done <"$file"
}

live_pids() {
  local file="$1" pid seen=""
  while IFS= read -r pid; do
    [[ -n "$pid" ]] || continue
    case " $seen " in *" $pid "*) continue ;; esac
    seen="$seen $pid"
    kill -0 "$pid" 2>/dev/null && printf '%s\n' "$pid"
  done < <({ read_pids "$file"; while IFS= read -r pid; do descendants "$pid"; done < <(read_pids "$file"); })
}

port_is_free() { node "$repo/scripts/dev/port_free.mjs" "$1" "$bind_addr" >/dev/null 2>&1; }

still_alive() {
  local pid
  for pid in $1; do kill -0 "$pid" 2>/dev/null && printf '%s ' "$pid"; done
  return 0
}

# Stop everything recorded in a PID file, confirm it died, and only then remove
# the file. Returns non-zero when something outlived the stop.
stop_pid_file() {
  local file="$1" pid attempt snapshot alive
  [[ -f "$file" ]] || return 0
  # Snapshot the whole tree BEFORE signalling anything. Killing a parent
  # re-parents its children to init, so re-walking the tree afterwards loses
  # exactly the orphan this function exists to reap -- which is how #282's
  # `--stop` left a uvicorn holding the DuckDB and reported success.
  snapshot="$(live_pids "$file" | tr '\n' ' ')"
  if [[ -z "${snapshot// /}" ]]; then rm -f "$file"; return 0; fi
  for pid in $snapshot; do kill -TERM "$pid" 2>/dev/null || true; done
  for attempt in $(seq 1 100); do
    alive="$(still_alive "$snapshot")"
    [[ -z "${alive// /}" ]] && break
    sleep 0.1
  done
  alive="$(still_alive "$snapshot")"
  if [[ -n "${alive// /}" ]]; then
    for pid in $alive; do kill -KILL "$pid" 2>/dev/null || true; done
    for attempt in $(seq 1 30); do
      alive="$(still_alive "$snapshot")"
      [[ -z "${alive// /}" ]] && break
      sleep 0.1
    done
  fi
  alive="$(still_alive "$snapshot")"
  if [[ -n "${alive// /}" ]]; then
    echo "Processes recorded in $file are still alive: $alive" >&2
    return 1
  fi
  rm -f "$file"
  return 0
}

if ((status_only)); then
  any_live=0
  rc=0
  for name in api web; do
    pid_file="$run_dir/$name.pid"
    port_file="$run_dir/$name.port"
    if [[ ! -f "$pid_file" && ! -f "$port_file" ]]; then continue; fi
    recorded="$(read_pids "$pid_file" | tr '\n' ' ')"
    alive="$(live_pids "$pid_file" | tr '\n' ' ')"
    port="$( [[ -f "$port_file" ]] && cat "$port_file" || echo "-" )"
    listening=no
    if [[ "$port" != "-" ]] && ! port_is_free "$port"; then listening=yes; fi
    echo "$name: recorded=[${recorded% }] alive=[${alive% }] port=$port listening=$listening"
    [[ -n "$alive" ]] && any_live=1
    if [[ -z "$alive" && "$listening" == yes ]]; then
      echo "$name: port $port is answered by a process this run directory did not start" >&2
      rc=1
    fi
    if [[ -n "$alive" && "$port" != "-" && "$listening" == no ]]; then rc=1; fi
    [[ -n "$recorded" && -z "$alive" ]] && rc=1
  done
  if ((any_live == 0)); then
    echo "No live processes recorded in $run_dir"
    exit 1
  fi
  exit "$rc"
fi

if ((stop_only)); then
  if [[ ! -f "$api_pid_file" && ! -f "$web_pid_file" ]]; then
    echo "No recorded processes in $run_dir; nothing to stop."
    rm -f "$api_port_file" "$web_port_file"
    exit 0
  fi
  rc=0
  stop_pid_file "$api_pid_file" || rc=1
  stop_pid_file "$web_pid_file" || rc=1
  for name in api web; do
    port_file="$run_dir/$name.port"
    [[ -f "$port_file" ]] || continue
    port="$(<"$port_file")"
    if valid_port "$port" && ! port_is_free "$port"; then
      echo "$name port $port is still in use after --stop." >&2
      rc=1
    else
      rm -f "$port_file"
    fi
  done
  ((rc == 0)) && echo "Stopped the recorded processes; their ports are released."
  exit "$rc"
fi

needs_uv=0
if [[ "$mode" == live ]] || ((! skip_install)); then needs_uv=1; fi
for command in npm node curl; do command -v "$command" >/dev/null || { echo "Required command is unavailable: $command" >&2; exit 1; }; done
if ((needs_uv)); then command -v uv >/dev/null || { echo "Required command is unavailable: uv" >&2; exit 1; }; fi
if [[ -f "$api_pid_file" || -f "$web_pid_file" ]]; then echo "Run directory already contains recorded PIDs. Use --stop first: $run_dir" >&2; exit 1; fi
port_is_free "$web_port" || { echo "Web port is already in use: $web_port" >&2; exit 1; }
if [[ "$mode" == live ]]; then port_is_free "$api_port" || { echo "API port is already in use: $api_port" >&2; exit 1; }; fi

if (( ! skip_install )); then (cd "$repo" && uv sync --frozen --extra dev); npm --prefix "$repo/web" ci; fi
if (( skip_build )); then
  [[ -f "$repo/web/dist/index.html" && -f "$repo/web/dist/assets/app.js" ]] \
    || { echo "--skip-build needs an existing build at $repo/web/dist; run npm --prefix web run build first." >&2; exit 1; }
else
  npm --prefix "$repo/web" run build
fi

# Wait on a real readiness signal, on a window the caller can widen, and say so
# while waiting instead of failing silently at a fixed 60s.
wait_ready() {
  local label="$1" url="$2" check="$3" started="$SECONDS" announced=0 status
  while ((SECONDS - started < ready_timeout)); do
    if [[ "$check" == health ]]; then
      if status="$(node "$repo/scripts/dev/health_ready.mjs" "$url" 2>/dev/null)"; then
        printf '%s\n' "$status"
        return 0
      fi
    elif curl --silent --fail --max-time 2 "$url" >/dev/null 2>&1; then
      return 0
    fi
    if ((SECONDS - started >= 15 && (SECONDS - started) / 15 > announced)); then
      announced=$(( (SECONDS - started) / 15 ))
      echo "Still waiting for $label after $((SECONDS - started))s of ${ready_timeout}s..." >&2
    fi
    sleep 0.5
  done
  return 1
}

successful=0
cleanup() {
  local rc=$?
  if ((rc != 0 && successful == 0)); then
    stop_pid_file "$api_pid_file" || true
    stop_pid_file "$web_pid_file" || true
    rm -f "$api_port_file" "$web_port_file"
  fi
}
trap cleanup EXIT

api_health=""
if [[ "$mode" == live ]]; then
  printf '%s\n' "$api_port" >"$api_port_file"
  ( cd "$repo" && exec env DUCKDB_PATH="$duckdb_path" uv run uvicorn copilot.app:app --host "$bind_addr" --port "$api_port" ) >"$run_dir/api.log" 2>&1 &
  record_pids "$api_pid_file" "$!"
  api_health="$(wait_ready "the API" "http://127.0.0.1:$api_port/health" health)" \
    || { echo "API did not answer /health with a Flux health body within ${ready_timeout}s; see $run_dir/api.log" >&2; exit 1; }
  # `uv run` execs a child; re-read the tree now that it exists so --stop can find it.
  record_pids "$api_pid_file" "$(head -n 1 "$api_pid_file")"
fi

printf '%s\n' "$web_port" >"$web_port_file"
( cd "$repo/web" && exec env PORT="$web_port" HOST="$bind_addr" node server.mjs ) >"$run_dir/web.log" 2>&1 &
record_pids "$web_pid_file" "$!"
wait_ready "the web app" "http://127.0.0.1:$web_port/" http \
  || { echo "Web app did not start within ${ready_timeout}s; see $run_dir/web.log" >&2; exit 1; }
record_pids "$web_pid_file" "$(head -n 1 "$web_pid_file")"

shell_code="$(curl --silent --output "$run_dir/index.html" --write-out '%{http_code}' "http://127.0.0.1:$web_port/")"
[[ "$shell_code" == 200 ]] || { echo "Expected the web shell, got HTTP $shell_code." >&2; exit 1; }
grep -q '/assets/app.js' "$run_dir/index.html" || { echo "The served shell does not reference the built bundle /assets/app.js." >&2; exit 1; }
# `web/server.mjs`'s SPA catch-all answers 200 for any path, so an HTTP code alone
# cannot tell a served bundle from the shell: /assets/DOES-NOT-EXIST.js is 200 too.
# Check what came back, not that something came back.
asset_meta="$(curl --silent --output "$run_dir/app.js" --write-out '%{http_code} %{content_type}' "http://127.0.0.1:$web_port/assets/app.js")"
asset_code="${asset_meta%% *}"
asset_type="${asset_meta#* }"
[[ "$asset_code" == 200 ]] || { echo "Expected the app bundle, got HTTP $asset_code." >&2; exit 1; }
case "$asset_type" in
  *javascript*|*ecmascript*) ;;
  *) echo "/assets/app.js is not JavaScript: content-type $asset_type (the SPA shell is served for missing assets)." >&2; exit 1 ;;
esac
if cmp -s "$run_dir/index.html" "$run_dir/app.js"; then
  echo "/assets/app.js returned the SPA shell byte for byte; the build is not being served." >&2
  exit 1
fi

if [[ "$mode" == live ]]; then
  api_code="$(curl --silent --output "$run_dir/api-layers.json" --write-out '%{http_code}' "http://127.0.0.1:$api_port/layers/buses")"
  node -e 'JSON.parse(require("fs").readFileSync(process.argv[1], "utf8"))' "$run_dir/api-layers.json" || { echo "API did not return JSON (HTTP $api_code)." >&2; exit 1; }
  [[ "$api_code" == 200 || "$api_code" == 503 ]] || { echo "API returned unexpected HTTP $api_code." >&2; exit 1; }
fi

successful=1
trap - EXIT
echo "Flux $mode demo ready: http://127.0.0.1:$web_port/ (bound to $bind_addr)"
if [[ "$mode" == live ]]; then
  echo "API health: $api_health; GET /layers/buses: HTTP $api_code$( [[ "$api_code" == 503 ]] && echo ' (layer unavailable)' )"
fi
echo "Logs and PIDs: $run_dir"
echo "Check these processes: $0 --run-dir '$run_dir' --status"
echo "Stop only these recorded processes: $0 --run-dir '$run_dir' --stop"
