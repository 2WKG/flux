# Flux — grid resilience data product

Flux compares resilience scenarios on a synthetic fixture today and is structured for state-scoped, source-backed data ingestion. A selected state needs its own validated source artifacts and configuration; the current fixture does not represent any state. The interactive desk is served by Node/Express and rendered with React; it intentionally does not use Vite.

## Run the demo

```bash
scripts/dev/launch_demo.sh --offline
```

To run the optional local read-only API beside the demo, supply an already-built
DuckDB file:

```bash
scripts/dev/launch_demo.sh --live --duckdb /absolute/path/to/grid.duckdb
```

The helper uses loopback ports only and does not create data, contact a model
provider, configure a tunnel, or publish an external service. Full start, stop,
and limitation details are in [`docs/runbooks/local-startup.md`](docs/runbooks/local-startup.md).

Open `http://localhost:4173`. The React client bundles `data/demo/bundle.json` at build time and makes no runtime request. `web/server.mjs` exposes **no API route**: 2WKG-300 (`db53a83`) deleted `GET /api/demo` along with its scenario selection and failure envelope, and the static origin now returns the SPA shell for every path — `/api/demo` answers `200 text/html` with a body byte-identical to `/`. The Copilot API is a separate FastAPI service ([`docs/specs/05-copilot.md`](docs/specs/05-copilot.md)). Ingestion jobs can validate and publish the same versioned contract without changing the client.

## Repository context

The project is expanding from the current synthetic preview toward source-backed network, scenario, and candidate-site datasets. The wider research plan and data catalog live in `docs/specs/` and `datasets/README.md`. Bulk downloads, parquet outputs, and DuckDB files remain outside Git.

The [UI style guide](docs/design/ui-style-guide.md) and [companion token reference](docs/design/ui-tokens.css) define current visual and interaction direction only. They do not change the shared API, data, geography, scenario, or provenance contracts.

## Verify

```powershell
python -m unittest discover -s model -p "test_*.py"
npm --prefix web run build
```

The synthetic fixture's cross-scenario validation report is documented in
[`docs/data/synthetic-cross-scenario-validation.md`](docs/data/synthetic-cross-scenario-validation.md).

## Demo source and current limits

The desk's checked-in artifact is
[`data/demo/bundle.json`](data/demo/bundle.json), generated from
[`data/demo/synthetic-scenario-input-v1.json`](data/demo/synthetic-scenario-input-v1.json).
It is source-attributed in the UI as `flux_checked_in_synthetic_fixture`, version
`1`, and its fixture hash is shown in **Data, units & limits**. The file is a
synthetic five-bus offline preview: it is not Minnesota, Texas, ERCOT, MISO, or
an actual interconnection model; it is not a grid-flow result, outage forecast,
historical reconstruction, or licensing assessment.

The static desk needs no API or external data service at runtime. A public
BouncePulse rehearsal is not implied by a successful local start; the current
tunnel and external-route state is recorded in
[`docs/runbooks/static-origin-and-tunnel.md`](docs/runbooks/static-origin-and-tunnel.md).
The dated freeze-readiness handoff, including its remaining external and backup
recording blockers, is
[`docs/runbooks/2wkg-87-freeze-readiness-2026-09-06.md`](docs/runbooks/2wkg-87-freeze-readiness-2026-09-06.md).
