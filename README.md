# flux — national grid digital twin (hackathon)

Outage prediction + cascade simulation + nuclear/firm-generation siting on a
synthetic-but-realistic US grid, Texas first. Pitch source:
`docs/pitch/hackathon-pitches-and-designs.md`. Build specs: `docs/specs/`
(start at `docs/specs/README.md`, then `00-overview.md`).

## Layout

```
data/raw/<source>/   untracked downloads          pipelines/   ingest → DuckDB
data/duck/grid.duckdb                              twin/        pandapower model + cascade
data/parquet/                                      models/outage/  LightGBM
siting/   safety + grid-value scoring              causal/      pgmpy / DoWhy
copilot/  FastAPI + Claude tool loop               web/         Vite + React + deck.gl + MapLibre
docs/specs/  one spec per unit                     scripts/data/download.sh
```

## Setup

```
uv sync                      # Python 3.12 env (see DEPENDENCIES.md)
brew install libomp          # macOS: LightGBM runtime
cd web && pnpm install        # front end
```

Status: specs + dependencies only. No product code yet.
