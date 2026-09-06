#!/usr/bin/env bash
# launchd child for the explicit, user-installed Flux demo service.
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
duckdb_path="${FLUX_DEMO_DUCKDB_PATH:?missing FLUX_DEMO_DUCKDB_PATH}"
api_port="${FLUX_DEMO_API_PORT:-8031}"
web_port="${FLUX_DEMO_WEB_PORT:-4317}"
log_dir="${FLUX_DEMO_LOG_DIR:?missing FLUX_DEMO_LOG_DIR}"
uv_bin="${FLUX_DEMO_UV_BIN:?missing FLUX_DEMO_UV_BIN}"
node_bin="${FLUX_DEMO_NODE_BIN:?missing FLUX_DEMO_NODE_BIN}"
mkdir -p "$log_dir"

if [[ ! -r "$duckdb_path" ]]; then
  echo "Flux demo database is not readable: $duckdb_path" >&2
  exit 1
fi

api_pid=""
web_pid=""
stop_children() {
  for pid in "$api_pid" "$web_pid"; do
    [[ -n "$pid" ]] && kill "$pid" 2>/dev/null || true
  done
}
trap stop_children EXIT INT TERM

(
  cd "$repo"
  DUCKDB_PATH="$duckdb_path" "$uv_bin" run uvicorn copilot.demo_app:app --host 127.0.0.1 --port "$api_port"
) >>"$log_dir/api.log" 2>&1 &
api_pid=$!
echo "$api_pid" >"$log_dir/api.pid"

(
  cd "$repo/web"
  PORT="$web_port" FLUX_API_ORIGIN="http://127.0.0.1:$api_port" "$node_bin" server.mjs
) >>"$log_dir/web.log" 2>&1 &
web_pid=$!
echo "$web_pid" >"$log_dir/web.pid"

# macOS ships Bash 3.2, which has no `wait -n`. Poll both children so an exit
# from either one brings down the pair; launchd then restarts this explicit job.
while kill -0 "$api_pid" 2>/dev/null && kill -0 "$web_pid" 2>/dev/null; do
  sleep 1
done
exit 1
