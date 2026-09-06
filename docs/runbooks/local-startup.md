# Local startup runbook

Start the static demo and the optional read-only copilot API on a clean
checkout. Every command below is idempotent, uses no cloud resource, and needs
no secret. Static-origin and tunnel facts (bind port, `web/dist/`, Cloudflare
status) live in [`static-origin-and-tunnel.md`](static-origin-and-tunnel.md);
this runbook does not repeat them.

Commands are shown for bash. PowerShell differences are called out inline:
`/dev/null` is `NUL`, and `VAR=value command` becomes `$env:VAR = "value"` on
the line before. To unset a variable use `Remove-Item Env:VAR`; `$env:VAR = ""`
sets an *empty* value, which for `DUCKDB_PATH` resolves to `.` and is not the
default.

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
from `web/dist/` and exposes `GET /api/demo`, which reads
`data/demo/bundle.json` on every request.

The React client does **not** call `/api/demo`: the bundle is inlined at build
time (`web/test/static-demo.test.mjs` asserts the built `web/dist/assets/app.js`
contains no `fetch(` and no `api/demo`). The route exists for the recorded
2WKG-296 question in `README.md` and for ingestion jobs to validate the same
contract; the page renders even if you never request it.

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
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:4173/
# Expected: 200

# Demo route. Envelope is {status, selectedScenarioId, data}; the bundle is under `data`.
curl -s http://localhost:4173/api/demo | uv run python -c "import sys,json; d=json.load(sys.stdin); assert d['status']=='available'; print(d['selectedScenarioId'], d['data']['fixtureHash'])"
# Expected: baseline f5b2c271416b

# Scenario selection and validation (ids: baseline, a, b)
curl -s "http://localhost:4173/api/demo?scenario=a" | uv run python -c "import sys,json; d=json.load(sys.stdin); print(d['status'], d['selectedScenarioId'])"
# Expected: available a
curl -s -o /dev/null -w "%{http_code}\n" "http://localhost:4173/api/demo?scenario=bogus"
# Expected: 404   (body: {"status":"unavailable","code":"SCENARIO_NOT_FOUND",...})
curl -s -o /dev/null -w "%{http_code}\n" "http://localhost:4173/api/demo?scenario=a&scenario=b"
# Expected: 400   (body: {"status":"unavailable","code":"SCENARIO_ID_INVALID",...})

# The built client makes no request to the route
grep -c "api/demo" web/dist/assets/app.js
# Expected: 0
```

`/api/demo` failures use the Node stopgap envelope
`{status, code, message, nextStep}` (see the comment in `web/server.mjs`), not
the FastAPI envelope below.

### Stop / restart

`Ctrl+C` in the server terminal; the port is released immediately. Restart with
`npm --prefix web run dev` (rebuild) or `npm --prefix web run start` (reuse
`web/dist/`). Delete `web/dist/` for a from-scratch build.

## Optional API (copilot)

`copilot.app:app` is a FastAPI app with four routers on master
(`copilot/app.py`): `GET /health`; `GET /layers/{name}`; `POST /site-score` and
`POST /compare` (persisted site scores, JSON body); `GET /scenarios` and
`GET /scenarios/{id}`. `POST /ask` and SSE are specification only
(`docs/specs/05-copilot.md`); any unmatched path — `/ask` included — answers
`404` with the shared envelope (`error.code` `not_found`, "No route matches the
request path."). A `GET` on the two POST routes is a plain FastAPI `405`
(`{"detail":"Method Not Allowed"}`, not the envelope). The API is not required
by the static demo, reads DuckDB read-only, and never creates a database.

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
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://localhost:8000/ask
# Expected: 404   (no such route; envelope error.code not_found)

curl -s -X POST http://localhost:8000/site-score -H "content-type: application/json" -d '{"site_id":"s1","unit_mw":300,"scenario_id":"baseline"}' | uv run python -c "import sys,json; d=json.load(sys.stdin); print(d['status'], d['error']['details'])"
# Expected: unavailable {'artifact': 'database', 'reason': 'missing'}
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://localhost:8000/compare -H "content-type: application/json" -d '{}'
# Expected: 422   (envelope error.code invalid_input, details {"field":"scenario_id"}; body is {scenario_id, intervention_ids:["site:<id>[@300|1000]", ...]})
```

### Smoke test (with a database)

With a schema-2.0.0 database at `DUCKDB_PATH` (built by `pipelines/build.py`, or
an empty one from `pipelines.db.connect(path)`), `/health` returns `200` with the
unwrapped success body and `/scenarios` returns a bare array. Run these in a
**second terminal** while uvicorn is running.

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
curl -s http://localhost:4173/api/demo | uv run python -c "import sys,json; d=json.load(sys.stdin); assert d['status']=='available'; print(d['selectedScenarioId'], d['data']['fixtureHash'])"
# baseline f5b2c271416b

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
| `/api/demo` returns 503 `DEMO_INPUT_UNAVAILABLE` | `data/demo/bundle.json` is missing; run `uv run python model/generate_demo.py`. |
| `/api/demo` returns 404 `SCENARIO_NOT_FOUND` / 400 `SCENARIO_ID_INVALID` | Use exactly one `?scenario=` with an id from the bundle (`baseline`, `a`, `b`). |
| `/health`, `/scenarios`, `/layers/buses` return 503 `unavailable` with `reason: missing` | No database at `DUCKDB_PATH` (default `data/duck/grid.duckdb`). Expected on a fresh checkout; build one with the pipelines. |
| `/scenarios` or `/layers/buses` return 503 `no_rows` with a database present | The table is empty; the API refuses to return an empty list or collection. |
| `/layers/<name>` returns 503 `not_built` | A documented layer whose artifact is not implemented yet; only `buses` is. |
| `POST /site-score` returns 404 `not_found` with a database present | No persisted `site_scores` row for that `site_id`/`unit_mw`/`scenario_id`; the API never fabricates a score. |
| `GET /site-score` or `GET /compare` returns 405 | Those routes are POST with a JSON body; see `copilot/routes/interventions.py`. |
| `POST /ask` (or any unknown path) returns 404 `not_found` | Not implemented on master; spec only. |

## Verified on master `e67b435` (merged into this branch as `7cf30d3`) on 2026-09-05

macOS (Darwin 25.6.0), Node v26.0.0, npm 11.12.1, uv 0.11.16, `uv run python`
3.12.13, no `python` on `PATH` (`python3` is 3.9.6). Every command above was run
in this order; outputs are verbatim.

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
'.'                                                              (empty is not "unset"; /health -> 503)
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