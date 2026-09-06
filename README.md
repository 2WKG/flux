# Flux — grid resilience data product

Flux compares resilience scenarios on a synthetic fixture today and is structured for state-scoped, source-backed data ingestion. A selected state needs its own validated source artifacts and configuration; the current fixture does not represent any state. The interactive desk is served by Node/Express and rendered with React; it intentionally does not use Vite.

## Run the desk

```powershell
python model/generate_demo.py
npm --prefix web install
npm --prefix web run dev
```

Full start/stop/smoke steps for the desk and the optional API, verified against master, are in [`docs/runbooks/local-startup.md`](docs/runbooks/local-startup.md).

Open `http://localhost:4173`. The React client bundles `data/demo/bundle.json` at build time and makes no runtime request; `web/server.mjs` still exposes `GET /api/demo` (validating `?scenario=`) over the same file for the recorded 2WKG-296 question above. Ingestion jobs can validate and publish the same versioned contract without changing the client.

## Repository context

The project is expanding from the current synthetic preview toward source-backed network, scenario, and candidate-site datasets. The wider research plan and data catalog live in `docs/specs/` and `datasets/README.md`. Bulk downloads, parquet outputs, and DuckDB files remain outside Git.

## Verify

```powershell
python -m unittest discover -s model -p "test_*.py"
npm --prefix web run build
```

The synthetic fixture's cross-scenario validation report is documented in
[`docs/data/synthetic-cross-scenario-validation.md`](docs/data/synthetic-cross-scenario-validation.md).

The current fixture is not a Texas-grid model, outage forecast, interconnection study, or licensing assessment.
