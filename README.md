# Flux — a national grid digital twin (hackathon)

**Flux** provides outage prediction, cascade simulation, and nuclear/firm-generation
siting on a synthetic-but-realistic US grid, Texas first. The repository and package
name are also `flux`. Pitch (v2, two ideas; backup = Speed-to-Power):
`hackathon-pitches-and-designs.md`,
mirrored at `docs/pitch/hackathon-pitches-and-designs.md`. Build specs:
`docs/specs/` (start at `docs/specs/README.md`, then `00-overview.md`).

## Layout

```
data/raw/<source>/   untracked downloads          pipelines/   ingest → DuckDB
data/duck/grid.duckdb                              twin/        pandapower model + cascade
data/parquet/                                      models/outage/  LightGBM
siting/   safety + grid-value scoring              causal/      pgmpy / DoWhy
copilot/  FastAPI + Claude tool loop               web/         Vite + React + deck.gl + MapLibre
docs/specs/  one spec per unit                     scripts/data/download.sh
datasets/    source registry + safe downloader
```

## Setup

```
uv sync --frozen --extra dev
pnpm --dir web install --frozen-lockfile
```

The development extras, key imports, a DuckDB query, a tiny LightGBM fit, and
the real 2,000-bus pandapower DC solve have been verified; see
`DEPENDENCIES.md` for the exact evidence. No product code exists yet.

## Build workflow

The amended overview is the current authority for the shared technical
contract. The primary orchestrator coordinates scope and integration; Terra
workers implement file-disjoint areas, using isolated worktrees for substantive
changes when helpful. Verify the behavior changed, expanding to browser, HTTP,
model, or data checks when the change affects those paths. Use health/doctor
checks only after setup changes or for actual connectivity troubleshooting.

Never present unavailable data, failed solves, missing API access, or
unverified claims as results. Buckeye material is reference knowledge only:
do not write Flux material into Buckeye repositories or reuse its credentials.
Status: specs + dependencies only. No product code yet.

See [`datasets/README.md`](datasets/README.md) for the complete public-data
catalog, acquisition routes, and commands that keep bulk files out of Git.
