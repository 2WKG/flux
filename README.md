# Flux — grid resilience data product

Flux compares resilience scenarios on a synthetic fixture today and is structured for national-grid data ingestion next. The interactive desk is served by Node/Express and rendered with React; it intentionally does not use Vite.

## Run the desk

```powershell
python model/generate_demo.py
npm --prefix web install
npm --prefix web run dev
```

Open `http://localhost:4173`. The React client reads `GET /api/demo`; the Node server currently returns `data/demo/bundle.json`. Ingestion jobs can validate and publish the same versioned contract without changing the client.

## Repository context

The project is expanding from the current synthetic preview toward source-backed network, scenario, and candidate-site datasets. The wider research plan and data catalog live in `docs/specs/` and `datasets/README.md`. Bulk downloads, parquet outputs, and DuckDB files remain outside Git.

## Verify

```powershell
python -m unittest discover -s model -p "test_*.py"
npm --prefix web run build
```

The current fixture is not a Texas-grid model, outage forecast, interconnection study, or licensing assessment.
