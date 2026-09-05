# Flux resilience desk

Flux is a Node-served React application for comparing power-system resilience scenarios. It currently ships a clearly labeled synthetic fixture; its data boundary is designed for upcoming network, scenario, and candidate-site ingestion.

## Run

```powershell
python model/generate_demo.py
npm --prefix web install
npm --prefix web run dev
```

Open `http://localhost:4173`. `npm --prefix web run build` creates the browser bundle; `npm --prefix web start` serves an already-built bundle.

## Data contract

The React client loads `GET /api/demo`. The Node server reads `data/demo/bundle.json`; today it is produced by the deterministic synthetic generator. Future ingestion jobs should validate and publish the same versioned contract to that location (or replace the API implementation) without requiring a client rewrite.

## Verify

```powershell
python -m unittest discover -s model -p "test_*.py"
npm --prefix web run build
```

The synthetic fixture is not a Texas-grid model, outage forecast, interconnection study, or licensing assessment.
