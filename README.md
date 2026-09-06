# Flux — grid resilience data product

Flux compares resilience scenarios on a synthetic fixture today and is structured for state-scoped, source-backed data ingestion. A selected state needs its own validated source artifacts and configuration; the current fixture does not represent any state. The interactive desk is a static React build: the client bundles its data at build time and calls no API at runtime. `STACK-LOCK.md` holds that runtime contract.

## Run the desk

```powershell
python model/generate_demo.py
npm --prefix web install
npm --prefix web run dev
```

Open `http://localhost:4173`. `web/server.mjs` serves the built `web/dist/` and nothing else — the React client bundles `data/demo/bundle.json` at build time, so there is no demo API to call. Rebuild after regenerating the bundle. Ingestion jobs can validate and publish the same versioned contract without changing the client.

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
