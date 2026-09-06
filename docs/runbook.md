# Flux — local startup runbook

Start the static demo and optional API on a clean checkout. Every command is
idempotent, avoids cloud resources, and stores no secrets.

## Prerequisites

| Tool | Minimum | Check |
|---|---|---|
| Python | 3.12 | `python --version` |
| Node.js | 18 LTS | `node --version` |
| npm | (bundled) | `npm --version` |
| pnpm | 8+ | `pnpm --version` |
| uv | 0.5+ | `uv --version` |

The repo root is `flux/`. All paths below are relative to it.

## Configuration

No secrets or credentials are required. The only env var is optional:

| Variable | Default | Used by |
|---|---|---|
| `PORT` | `4173` | `web/server.mjs` |

Set it before starting the server if you need a different port.

## Static demo

The static demo is a self-contained Node/Express server that serves the React
frontend and a synthetic `/api/demo` JSON payload. It does not depend on the
copilot API, DuckDB, or any Python package beyond `model/generate_demo.py`.

### First-time setup

```powershell
python model/generate_demo.py
npm --prefix web install
```

### Start

```powershell
npm --prefix web run dev
```

This builds the frontend bundle with esbuild, runs the TypeScript type-check,
and starts the Express server.

Open `http://localhost:4173`. The React client reads `GET /api/demo` and
renders the synthetic five-bus network comparison.

### Smoke test

```powershell
# Static asset served
curl -s -o NUL -w "%{http_code}" http://localhost:4173/
# Expected: 200

# Demo payload
curl -s http://localhost:4173/api/demo | python -c "import sys,json; d=json.load(sys.stdin); print(d['dataStatus']['mode'], d['fixtureHash'])"
# Expected: synthetic ab7092ddee11
```

### Stop

`Ctrl+C` in the terminal running the server. The process releases the port
immediately; no cleanup is needed.

### Restart

```powershell
npm --prefix web run dev
```

### Verify the demo works without the API

The static demo server has no API dependency. Stop the copilot (if running)
and confirm the demo still loads:

```powershell
curl -s http://localhost:4173/api/demo | python -c "import sys,json; d=json.load(sys.stdin); assert d['dataStatus']['mode'] == 'synthetic'; print('OK')"
# Expected: OK
```

## Optional API (copilot)

The copilot is a FastAPI server (`copilot.app:app`) that wraps the DuckDB
read layer and exposes the Claude tool-calling loop. It is not required for
the static demo.

### First-time setup

```powershell
uv sync --frozen --extra dev
```

### Configuration

| Variable | Required | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | yes | Claude tool-calling (`/ask` SSE) |
| `FLUX_DUCKDB_PATH` | no | Path to `grid.duckdb`; defaults to `data/duck/grid.duckdb` |

No other API keys, cloud credentials, or secrets are needed. Missing
`ANTHROPIC_API_KEY` disables the `/ask` SSE endpoint; all other read endpoints
still work.

### Start

```powershell
uv run uvicorn copilot.app:app --port 8000
```

### Smoke test

```powershell
# Health check
curl -s http://localhost:8000/health | python -c "import sys,json; d=json.load(sys.stdin); print(d['ok'])"
# Expected: True

# Scenarios list
curl -s http://localhost:8000/scenarios | python -c "import sys,json; d=json.load(sys.stdin); print(len(d))"
# Expected: count of loaded scenarios

# Map layer
curl -s http://localhost:8000/layers/buses | python -c "import sys,json; d=json.load(sys.stdin); print(d['type'])"
# Expected: FeatureCollection
```

### Test missing-config / missing-database behavior

```powershell
# 1. Missing DuckDB: point FLUX_DUCKDB_PATH at a nonexistent file
$env:FLUX_DUCKDB_PATH = "C:\nonexistent\grid.duckdb"
uv run uvicorn copilot.app:app --port 8001
# Expected: /health returns ok=false, duckdb_path=missing

# 2. Missing ANTHROPIC_API_KEY: unset the variable
$env:ANTHROPIC_API_KEY = ""
curl -s -X POST http://localhost:8001/ask -H "Content-Type: application/json" -d '{"messages":[]}'
# Expected: 503 with {"error": "ANTHROPIC_API_KEY not configured"}
```

### Stop

`Ctrl+C` in the terminal running uvicorn. The process releases the port.

### Restart

```powershell
uv run uvicorn copilot.app:app --port 8000
```

## Quick-start checklist

From a clean checkout, in order:

```powershell
# 1. Static demo
python model/generate_demo.py
npm --prefix web install
npm --prefix web run dev
# Open http://localhost:4173 — verify the network comparison renders

# 2. Smoke test
curl -s http://localhost:4173/api/demo | python -c "import sys,json; d=json.load(sys.stdin); assert d['dataStatus']['mode'] == 'synthetic'; print('OK')"

# 3. (Optional) API
uv sync --frozen --extra dev
uv run uvicorn copilot.app:app --port 8000
curl -s http://localhost:8000/health | python -c "import sys,json; assert json.load(sys.stdin)['ok']; print('OK')"
```

## Troubleshooting

| Symptom | Check |
|---|---|
| `python model/generate_demo.py` fails | Python 3.12+ is installed; the file exists at `model/generate_demo.py` |
| `npm --prefix web install` fails | Node.js 18+ and npm are installed; `web/package.json` exists |
| `npm --prefix web run dev` fails | `pnpm` is installed (`npm install -g pnpm`) |
| Server starts but page is blank | `python model/generate_demo.py` ran successfully; `data/demo/bundle.json` exists |
| `/api/demo` returns 503 | Run `python model/generate_demo.py` to regenerate the bundle |
| `uv sync` fails | `uv` is installed; Python 3.12 is the active version |
| `uvicorn` fails to import `copilot` | The copilot directory has not been built yet — this is expected |