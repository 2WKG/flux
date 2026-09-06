# Local startup runbook

Start the static demo and the optional read-only copilot API on a clean
checkout. Every command below is idempotent, uses no cloud resource, and needs
no secret. Static-origin and tunnel facts (bind port, `web/dist/`, Cloudflare
status) live in [`static-origin-and-tunnel.md`](static-origin-and-tunnel.md);
this runbook does not repeat them.

Commands are shown for bash. PowerShell differences are called out inline:
`/dev/null` is `NUL`, and `VAR=value command` becomes `$env:VAR = "value"` on
the line before. To unset a variable use `Remove-Item Env:VAR`; `$env:VAR = ""`
sets an *empty* value, which for `DUCKDB_PATH` is now rejected by validation
(`ValidationError` naming `duckdb_path`) rather than falling back to the default.

## Prerequisites

| Tool | Version | Check |
|---|---|---|
| uv | 0.5+ | `uv --version` |
| Python | 3.12.x, installed and selected by `uv` (`pyproject.toml`: `>=3.12,<3.13`) | `uv run python --version` |
| Node.js | 18+ | `node --version` |
| npm | bundled with Node | `npm --version` |

Use `uv run python`, never bare `python`: a stock macOS has no `python` on
`PATH` (`python3` there is 3.9, outside the project's range), and `uv run`
guarantees the 3.12 interpreter and the locked dependencies. `web/` uses npm
with a committed `package-lock.json`; pnpm is not used.

The repo root is `flux/`. All paths below are relative to it.

## Static demo

`web/server.mjs` is a Node/Express server. It serves the built React client
from `web/dist/` and **exposes no API route**: the static origin returns the SPA
shell for every path. 2WKG-300 (`db53a83`) deleted `GET /api/demo` together with
its scenario selection and its failure envelope; `web/server.mjs` now carries an
explicit comment telling you not to re-add one.

The React client needs no route: the bundle is inlined at build time
(`web/test/static-demo.test.mjs` asserts the built `web/dist/assets/app.js`
contains no `fetch(` and no `api/demo`). Requesting `/api/demo` today is not an
error and not a payload — the Express catch-all answers `200 text/html` with the
same `index.html` bytes as `/`. The Copilot API is the separate FastAPI service
below.

### Configuration

| Variable | Default | Used by |
|---|---|---|
| `PORT` | `4173` | `web/server.mjs` (`app.listen(port)`) |

This is the static server's only environment variable.

### First-time setup

```bash
uv sync --frozen --extra dev            # Python 3.12 env; needed for `uv run python`
uv run python model/generate_demo.py    # -> Wrote data/demo/bundle.json (idempotent; no git diff)
npm --prefix web ci                     # reproducible install from web/package-lock.json
```

`model/generate_demo.py` writes `data/demo/bundle.json` from
`data/demo/synthetic-scenario-input-v1.json`. The committed bundle is already
current; re-running is a no-op (`git status --porcelain data/` stays empty).

### Start

```bash
npm --prefix web run dev
```

`dev` runs `build` (which is `npm run lint` — `scripts/check-browser-boundary.mjs`
— then `tsc --noEmit`, then `node scripts/build.mjs` with esbuild) and then
`node server.mjs`. Any lint or type error stops the start. Expected last line:

```
Flux is running at http://localhost:4173
```

To start without rebuilding (an existing `web/dist/`): `npm --prefix web run start`.

Open `http://localhost:4173` — the synthetic five-bus comparison renders.

### Smoke test

Run these in a **second terminal** while the server from [Start](#start) is
still running.

```bash
# SPA shell served
curl -s -o /dev/null -w "%{http_code} %{content_type}\n" http://localhost:4173/
# Expected: 200 text/html; charset=utf-8

# No API route: every unmatched path is the same SPA shell, /api/demo included.
curl -s -o /dev/null -w "%{http_code} %{content_type}\n" http://localhost:4173/api/demo
# Expected: 200 text/html; charset=utf-8
curl -s http://localhost:4173/ | shasum -a 256
curl -s http://localhost:4173/api/demo | shasum -a 256
# Expected: the same digest twice
#   4c9dc8d4c80841e07b5fd7d0c2c63364d78193f1233299e307ff31cc2e7bccd5

# The bundled asset is real (this is what distinguishes a served build from a shell alone)
curl -s -o /dev/null -w "%{http_code} %{content_type}\n" http://localhost:4173/assets/app.js
# Expected: 200 text/javascript; charset=utf-8

# The built client requests nothing at runtime
grep -c "api/demo" web/dist/assets/app.js ; grep -c "fetch(" web/dist/assets/app.js
# Expected: 0 ; 0
```

Because the shell is returned for any path, a `200` from this origin proves only
that the process is serving `web/dist/`; it never proves a route exists. Piping
`/api/demo` into a JSON parser is now a failure — `json.decoder.JSONDecodeError:
Expecting value: line 1 column 1 (char 0)` — because the response is HTML. The
FastAPI envelope below belongs to the separate copilot service, not to this
origin.

### Stop / restart

`Ctrl+C` in the server terminal; the port is released immediately. Restart with
`npm --prefix web run dev` (rebuild) or `npm --prefix web run start` (reuse
`web/dist/`). Delete `web/dist/` for a from-scratch build.

## Optional API (copilot)

`copilot.app:app` is a FastAPI app with the nine registered local routes listed
by `copilot/test_read_route_contracts.py`: `GET /health`; `GET /layers/{name}`;
`POST /site-score` and `POST /compare` (persisted site scores, JSON body);
`GET /scenarios` and `GET /scenarios/{id}`; `GET /predictions`; `GET /cascade`;
and `POST /ask`. The default `/ask` backend is deliberately unconfigured: it
returns a local SSE `lifecycle` event followed by an explicit `unavailable`
terminal, with no provider or network call. A `GET` on the POST routes is a
plain FastAPI `405` (`{"detail":"Method Not Allowed"}`, not the envelope). The
API is not required by the static demo, reads DuckDB read-only, and never creates
a database.

### First-time setup

```bash
uv sync --frozen --extra dev
```

### Configuration

Settings come from the environment or a `.env` file in the repo root
(`copilot/config.py`, pydantic-settings; unknown keys are ignored). None is
required to start.

| Variable | Default | Effect |
|---|---|---|
| `DUCKDB_PATH` | `data/duck/grid.duckdb` | Database the routes open read-only. (`FLUX_DUCKDB_PATH` is **not** read.) |
| `COPILOT_MODEL` | unset | Together with `ANTHROPIC_API_KEY`, flips `/health` `model.status` from `not_configured` to `not_verified`. No route calls a model today. |
| `ANTHROPIC_API_KEY` | unset | Same as above; optional, never contacted by the local health check. |

A fresh checkout has no `data/duck/grid.duckdb` (DuckDB files stay out of Git),
so every route answers with the shared **unavailable** envelope until a database
is built by the pipelines. That is the expected first-run state, not a fault.

### Start

```bash
uv run uvicorn copilot.app:app --port 8000
# Expected: INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```

### Smoke test (fresh checkout, no database)

Run these in a **second terminal** while uvicorn from [Start](#start-1) is
still running.

Failures are `503` with the versioned envelope from `copilot/api/envelope.py`:
`{status: "unavailable", data: null, error: {code, message, retryable, retry_after_s, details}, meta: {api_version, request_id, generated_at}}`.

```bash
curl -s -w "\n%{http_code}\n" http://localhost:8000/health
# Expected: 503; body.status "unavailable", error.code "unavailable",
#           error.details {"artifact":"database","model":"not_configured"}

curl -s http://localhost:8000/health | uv run python -c "import sys,json; d=json.load(sys.stdin); print(d['status'], d['error']['code'], d['error']['details'])"
# Expected: unavailable unavailable {'artifact': 'database', 'model': 'not_configured'}

curl -s http://localhost:8000/scenarios | uv run python -c "import sys,json; d=json.load(sys.stdin); print(d['status'], d['error']['details'])"
# Expected: unavailable {'artifact': 'database', 'reason': 'missing'}

curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/scenarios/nope
# Expected: 503   (database missing is checked before the id; 404 not_found needs a database)

curl -s http://localhost:8000/layers/buses | uv run python -c "import sys,json; d=json.load(sys.stdin); print(d['status'], d['error']['details'])"
# Expected: unavailable {'artifact': 'database', 'reason': 'missing'}
curl -s http://localhost:8000/layers/lines | uv run python -c "import sys,json; d=json.load(sys.stdin); print(d['status'], d['error']['details'])"
# Expected: unavailable {'artifact': 'lines', 'reason': 'not_built'}   (documented layer, only `buses` is implemented)
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8000/layers/bogus
# Expected: 404   (error.code not_found, details {"layer":"bogus"})
curl -sS -iN -X POST http://localhost:8000/ask \
  -H 'content-type: application/json' \
  -d '{"attempt_id":"local_startup_0001","question":"What evidence is available?"}'
# Expected: 200 text/event-stream; X-Flux-Attempt-Id: local_startup_0001;
#           lifecycle seq 1 followed by error seq 2 with code "unavailable".
# This proves only the injected local transport boundary, not a configured
# provider, real topology, or a live external SSE route.

The default unconfigured app produces that `200` SSE response. A valid
`Last-Event-ID` resume is different: replay storage is not implemented, so it
is rejected **before** streaming as a `503` JSON unavailable envelope and has
no `X-Flux-Attempt-Id` acknowledgement. A configured backend whose provider is
missing also uses `200` SSE, after it has emitted its local tool evidence; that
is a deployment-injected state and is not established by this fresh-checkout
smoke test.

curl -s -X POST http://localhost:8000/site-score -H "content-type: application/json" -d '{"site_id":"s1","unit_mw":300,"scenario_id":"baseline"}' | uv run python -c "import sys,json; d=json.load(sys.stdin); print(d['status'], d['error']['details'])"
# Expected: unavailable {'artifact': 'database', 'reason': 'missing'}
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://localhost:8000/compare -H "content-type: application/json" -d '{}'
# Expected: 422   (envelope error.code invalid_input, details {"field":"scenario_id"}; body is {scenario_id, intervention_ids:["site:<id>[@300|1000]", ...]})
```

### Smoke test (with a database)

With a schema-2.0.0 database at `DUCKDB_PATH` (built by `pipelines/build.py`, or
an empty one from `pipelines.db.connect(path)`), `/health` returns `200` with the
unwrapped success body and `/scenarios` returns a bare array. The separate
clean-checkout fixture-preparation prerequisite remains tracked by 2WKG-418;
this runbook does not treat a schema-only database as fixture-data success.
Run these in a **second terminal** while uvicorn is running.

```bash
curl -s http://localhost:8000/health | uv run python -c "import sys,json; d=json.load(sys.stdin); print(d['ok'], d['duckdb_path'], len(d['tables']), d['model']['status'])"
# Expected: True <your DUCKDB_PATH> 36 not_configured
#   (the success body is {ok: true, duckdb_path, tables, corpus_chunks, dense, model:{status,message}})

curl -s http://localhost:8000/scenarios | uv run python -c "import sys,json; d=json.load(sys.stdin); print(len(d) if isinstance(d, list) else (d['status'], d['error']['details']))"
# Expected: the scenario count, or `('unavailable', {'artifact': 'scenarios', 'reason': 'no_rows'})`
#   for a schema-only database (an empty table is a 503, never an empty list)

curl -s http://localhost:8000/layers/buses | uv run python -c "import sys,json; d=json.load(sys.stdin); print(d['status'], d['error']['details']) if 'error' in d else print(d['type'], len(d['features']))"
# Expected: a GeoJSON FeatureCollection once `buses` has rows, or
#   `unavailable {'artifact': 'buses', 'reason': 'no_rows'}` for a schema-only database
```

`POST /site-score` with a database but no matching row is `404` `not_found`
(`details {"site_id": ...}`), never a fabricated score.

Each `/scenarios` element is
`{scenario_id, name, kind, ts_start, ts_end, hours, has_cascade, has_predictions, provenance}`
(`copilot/routes/scenarios.py`).

### Exercise the missing-database path explicitly

```bash
DUCKDB_PATH=/nonexistent/grid.duckdb uv run uvicorn copilot.app:app --port 8001
# PowerShell: $env:DUCKDB_PATH = "C:\nonexistent\grid.duckdb"; uv run uvicorn copilot.app:app --port 8001
curl -s http://localhost:8001/health | uv run python -c "import sys,json; d=json.load(sys.stdin); print(d['status'], d['error']['details']['artifact'])"
# Expected: unavailable database
```

Leaving `ANTHROPIC_API_KEY`/`COPILOT_MODEL` unset is the way to see
`model: not_configured`; it appears in `error.details.model` on the 503 and in
`model.status` on the 200. There is no separate step for it.

### Stop / restart

`Ctrl+C` in the uvicorn terminal; restart with the same command.

## Quick-start checklist

```bash
# 1. Static demo
uv sync --frozen --extra dev
uv run python model/generate_demo.py
npm --prefix web ci
npm --prefix web run dev
# Open http://localhost:4173 — the network comparison renders

# 2. Smoke test (second shell)
curl -s -o /dev/null -w "%{http_code} %{content_type}\n" http://localhost:4173/
# 200 text/html; charset=utf-8   (the same shell answers every path; there is no API route)

# 3. (Optional) API
uv run uvicorn copilot.app:app --port 8000
curl -s -w "\n%{http_code}\n" http://localhost:8000/health
# 503 unavailable envelope without a database; 200 {"ok":true,...} with one
```

## Troubleshooting

| Symptom | Check |
|---|---|
| `python: command not found` | Use `uv run python model/generate_demo.py`; bare `python` is not on a stock macOS `PATH`. |
| `uv sync` fails | `uv` is installed; it needs a Python 3.12.x it can select (`uv python list`). |
| `npm --prefix web ci` fails | Node 18+ and npm are installed; `web/package-lock.json` is present and in sync with `web/package.json`. |
| `npm --prefix web run dev` stops before "Flux is running" | Read the `lint` (`scripts/check-browser-boundary.mjs`) or `tsc` output; `dev` runs both before starting the server. |
| `/api/demo` returns HTML, or a JSON parse of it fails | Expected. 2WKG-300 deleted the route; the static origin answers every path with the SPA shell. Scenario data is bundled into `web/dist/assets/app.js` at build time. |
| The page shows stale scenario numbers | `data/demo/bundle.json` changed without a rebuild; re-run `uv run python model/generate_demo.py` and `npm --prefix web run build`. |
| `/health`, `/scenarios`, `/layers/buses` return 503 `unavailable` with `reason: missing` | No database at `DUCKDB_PATH` (default `data/duck/grid.duckdb`). Expected on a fresh checkout; build one with the pipelines. |
| `/scenarios` or `/layers/buses` return 503 `no_rows` with a database present | The table is empty; the API refuses to return an empty list or collection. |
| `/layers/<name>` returns 503 `not_built` | A documented layer whose artifact is not implemented yet; only `buses` is. |
| `POST /site-score` returns 404 `not_found` with a database present | No persisted `site_scores` row for that `site_id`/`unit_mw`/`scenario_id`; the API never fabricates a score. |
| `GET /site-score` or `GET /compare` returns 405 | Those routes are POST with a JSON body; see `copilot/routes/interventions.py`. |
| `POST /ask` emits `lifecycle` then SSE `error` code `unavailable` | The local app has no injected backend. This is expected; no provider is contacted. |
| An unknown path returns 404 `not_found` | Only the nine routes listed above are registered. |
| `ConfigError: Invalid Flux configuration -> duckdb_path: ...` at startup | `DUCKDB_PATH` is empty, names a directory, or is a DuckDB connection target (`md:`, `ducklake:`, `:memory:`, `scheme://`). This service opens a *local* file read-only; a remote target would take it off the filesystem onto a network. Set `DUCKDB_PATH` to a `.duckdb` file path, or unset it for the default `data/duck/grid.duckdb`. The rejected value is never echoed back. |

## Current local API handoff verification

The updated route inventory and `/ask` statements above were checked without
starting the static demo, contacting a provider, or using an external route on
master `560dc7fcec6a543198749b3fcf54edb98f4e95d5` (PR #124 plus the already
merged local Ask implementation). A local FastAPI `TestClient` trace used
`attempt_id: "local_startup_0001"` and found:

- The default app (no injected backend) returns `200 text/event-stream`, echoes
  `X-Flux-Attempt-Id: local_startup_0001`, then sends `lifecycle` sequence 1
  and `error` sequence 2 with code `unavailable`.
- An injected backend with local evidence but no provider remains `200` SSE;
  it sends its tool events before the explicit unavailable terminal.
- A valid `Last-Event-ID: 1` request is a pre-stream `503` JSON unavailable
  response and has no attempt acknowledgement because replay storage is absent.

`uv run --extra dev pytest -q copilot/test_api_route_inventory.py
copilot/test_ask.py` passed 14 tests for the registered inventory and local SSE
contract. This verification does not provide the separate 2WKG-418 fixture
preparation path or any live HTTPS/tunnel/provider evidence.

## Historical verification on master `e67b435` (merged into this branch as `7cf30d3`) on 2026-09-05

Read this section as a dated record, not as current behaviour: every `/api/demo`
line below predates 2WKG-300 (`db53a83`, 2026-09-05) and cannot be reproduced on
master today — that path now returns the SPA shell.

macOS (Darwin 25.6.0), Node v26.0.0, npm 11.12.1, uv 0.11.16, `uv run python`
3.12.13, no `python` on `PATH` (`python3` is 3.9.6). The following original
startup commands were run in this order; outputs are verbatim. They predate the
current `/predictions`, `/cascade`, and `/ask` route inventory.

```
$ uv sync --frozen --extra dev                                  rc=0
$ npm --prefix web ci                                            rc=0
$ python model/generate_demo.py
python: command not found                                        rc=127
$ uv run python model/generate_demo.py
Wrote data/demo/bundle.json                                      rc=0 (twice; git status --porcelain data/ empty)
$ npm --prefix web run dev
> npm run lint && tsc --noEmit && node scripts/build.mjs ... Flux is running at http://localhost:4173
$ curl -s -o /dev/null -w "%{http_code}\n" http://localhost:4173/
200
$ curl -s http://localhost:4173/api/demo | uv run python -c "...assert d['status']=='available'; print(d['selectedScenarioId'], d['data']['fixtureHash'])"
baseline f5b2c271416b
$ curl -s http://localhost:4173/api/demo | uv run python -c "...print(sorted(d))"
['data', 'selectedScenarioId', 'status']
$ curl -s "http://localhost:4173/api/demo?scenario=a" | ... print(d['status'], d['selectedScenarioId'])
available a
$ curl -s "http://localhost:4173/api/demo?scenario=bogus"                                      -> 404
{"status":"unavailable","code":"SCENARIO_NOT_FOUND","message":"The requested scenario 'bogus' is not in this synthetic bundle.",...}
$ curl -s -o /dev/null -w "%{http_code}\n" "http://localhost:4173/api/demo?scenario=a&scenario=b"
400
$ grep -c "api/demo" web/dist/assets/app.js ; grep -c "fetch(" web/dist/assets/app.js
0 ; 0
$ (bundle.json moved aside) npm --prefix web run start ; curl -s -w "\n%{http_code}\n" http://localhost:4173/api/demo
{"status":"unavailable","code":"DEMO_INPUT_UNAVAILABLE",...,"nextStep":"Run python model/generate_demo.py and reload the page."}   503
$ ls data/duck
ls: data/duck: No such file or directory
$ uv run uvicorn copilot.app:app --port 8000
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
$ curl -s -w "\n%{http_code}\n" http://localhost:8000/health
{"status":"unavailable","data":null,"error":{"code":"unavailable","message":"The configured database artifact is unavailable.","retryable":true,"retry_after_s":30,"details":{"artifact":"database","model":"not_configured"}},"meta":{"api_version":"v1",...}}   503
$ curl -s http://localhost:8000/scenarios | ... print(d['status'], d['error']['details'])
unavailable {'artifact': 'database', 'reason': 'missing'}
$ /scenarios/nope ; /layers/buses ; /layers/lines ; /layers/bogus ; /layers ; GET /ask ; POST /ask   (http codes)
503 ; 503 ; 503 ; 404 ; 404 ; 404 ; 404
$ curl -s http://localhost:8000/openapi.json | ... print(sorted(d['paths']))
['/compare', '/health', '/layers/{layer_name}', '/scenarios', '/scenarios/{scenario_id}', '/site-score']
$ curl -s -X POST http://localhost:8000/site-score -H "content-type: application/json" -d '{"site_id":"s1","unit_mw":300,"scenario_id":"baseline"}'
{"status":"unavailable",...,"details":{"artifact":"database","reason":"missing"}}   503
$ curl -s -X POST http://localhost:8000/site-score -H "content-type: application/json" -d '{}'
{"status":"error",...,"error":{"code":"invalid_input",...,"details":{"field":"site_id"}}}   422
$ curl -s -X POST http://localhost:8000/compare -H "content-type: application/json" -d '{}'
{"status":"error",...,"error":{"code":"invalid_input",...,"details":{"field":"scenario_id"}}}   422
$ curl -s http://localhost:8000/site-score
{"detail":"Method Not Allowed"}   405
$ curl -s http://localhost:8000/ask | ... print(d['status'], d['error']['code'], d['error']['message'])
error not_found No route matches the request path.
$ curl -s http://localhost:8000/layers/buses | ... print(d['status'], d['error']['details'])
unavailable {'artifact': 'database', 'reason': 'missing'}
$ curl -s http://localhost:8000/layers/lines | ...
unavailable {'artifact': 'lines', 'reason': 'not_built'}
$ curl -s http://localhost:8000/layers/bogus | ... print(d['status'], d['error']['code'], d['error']['details'])
error not_found {'layer': 'bogus'}
$ DUCKDB_PATH=/nonexistent/grid.duckdb uv run uvicorn copilot.app:app --port 8001 ; curl .../health | ... print(d['status'], d['error']['details']['artifact'])
unavailable database
$ DUCKDB_PATH=/nonexistent/grid.duckdb uv run python -c "from copilot.config import Settings; print(Settings().duckdb_path)"
/nonexistent/grid.duckdb
$ FLUX_DUCKDB_PATH=/nonexistent/grid.duckdb uv run python -c "from copilot.config import Settings; print(Settings().duckdb_path)"
data/duck/grid.duckdb                                            (not honoured)
$ DUCKDB_PATH='' uv run python -c "from copilot.config import Settings; print(repr(str(Settings().duckdb_path)))"
pydantic_core._pydantic_core.ValidationError: 1 validation error for Settings
duckdb_path
  Value error, DUCKDB_PATH must be a non-empty local file path [type=value_error]
                                                                 (empty is not "unset": it now fails validation instead of resolving to '.')
$ DUCKDB_PATH='' uv run python -c "import copilot.app"
copilot.config.ConfigError: Invalid Flux configuration -> duckdb_path: Value error, DUCKDB_PATH must be a non-empty local file path
$ DUCKDB_PATH=md:my_db uv run python -c "import copilot.app"
copilot.config.ConfigError: Invalid Flux configuration -> duckdb_path: Value error, DUCKDB_PATH must be a local file path, not a DuckDB connection target (md:, ducklake:, :memory:, or scheme://)
$ uv run python -c "from copilot.config import Settings; print(Settings().model_is_configured)" ; ANTHROPIC_API_KEY=x COPILOT_MODEL=m uv run python -c "..."
False ; True
$ uv run python -c "from pipelines.db import connect; connect('/tmp/f124/grid.duckdb').close()"
$ DUCKDB_PATH=/tmp/f124/grid.duckdb uv run uvicorn copilot.app:app --port 8000
$ curl -s http://localhost:8000/health | ... print(d['ok'], d['duckdb_path'], len(d['tables']), d['corpus_chunks'], d['dense'], d['model']['status'])   -> 200
True /tmp/f124/grid.duckdb 36 0 False not_configured
$ curl -s http://localhost:8000/scenarios | ... print(len(d) if isinstance(d, list) else (d['status'], d['error']['details']))
('unavailable', {'artifact': 'scenarios', 'reason': 'no_rows'})
$ curl -s http://localhost:8000/layers/buses | ... print(d['status'], d['error']['details'])
unavailable {'artifact': 'buses', 'reason': 'no_rows'}
$ curl -s -X POST http://localhost:8000/site-score -H "content-type: application/json" -d '{"site_id":"s1","unit_mw":300,"scenario_id":"baseline"}'
{"status":"error",...,"error":{"code":"not_found","message":"The requested site score does not exist.",...,"details":{"site_id":"s1"}}}   404
```

The static-demo and `/health`, `/scenarios`, `/layers` outputs above were first
recorded on master `80d2d55` (merge `86d8b63`) and re-checked unchanged on
`e67b435`, which added only the `interventions` router (#133) and pipeline/test
files.

Control — lines from the previous revision of this runbook (`af8a76e`) re-run on
the same tree before the rewrite: `python model/generate_demo.py` and every
`python -c` one-liner (rc 127, `python: command not found`); `d['ok']` and
`assert json.load(sys.stdin)['ok']` on a fresh-checkout `/health` (`KeyError:
'ok'`); `len(d)` on a fresh-checkout `/scenarios` (prints `4`, the envelope's key
count, not a scenario count); `$env:DUCKDB_PATH = ""` then `d['model']['status']`
(`DUCKDB_PATH` becomes `.`, `/health` is 503, `KeyError: 'model'`).
