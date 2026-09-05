# Codex project memory — flux / GridMind

This file is a durable project-context note for future Codex sessions. It is
not product code and should be updated through a pull request.

## Repository

- GitHub: `Wyzard1004/flux`
- Product: **GridMind**, a Texas-first prototype of a national grid digital twin
- Default branch: `master`
- GitHub workflow: work on a feature or unit branch, push it, and open a PR into
  `master`; do not commit directly to `master` or merge without explicit approval.
- Repository is public. GitHub account currently connected: `ghadikhoury`.

## Current state

- The repository is specs- and dependency-first; product implementation code has
  not yet been built.
- Start with `README.md`, `docs/specs/README.md`, and
  `docs/specs/00-overview.md`.
- Product description: `discription.md` (the filename is intentionally kept as
  it exists in the repository).
- Dependencies and data-source verification: `DEPENDENCIES.md`.
- Existing graphify outputs are in `graphify-out/`.

## Architecture in one sentence

Public/synthetic grid and weather data feed ingest and a DuckDB/Parquet data
layer; outage prediction, power-flow/cascade simulation, siting and upgrade
scoring feed typed FastAPI/copilot tools; the Vite/React/deck.gl/MapLibre web
app presents the results with citations and counterfactual comparisons.

## Build order and ownership

The authoritative unit plan is `docs/build/swarm-plan.md`:

| Unit | Focus | Depends on |
|---|---|---|
| U0 | gates, contracts, CI | — |
| U1 | data ingest | U0 |
| U2 | twin build | U1 |
| U3 | outage model | U1 |
| U4 | cascade simulation | U2 |
| U5 | siting engine | U4 |
| U6 | transmission upgrades | U1, U2 |
| U7 | copilot/API | U3, U4, U5, U6 |
| U8 | frontend | U7 |
| U9 | causal layer | U3, U4 |

The planned waves are U0 → U1 → (U2 ∥ U3) → (U4 ∥ U6) →
(U5 ∥ U9 ∥ U7) → U8. Respect the unit path ownership and dependency order.

## Quality and honesty rules

- Read the relevant spec and verification files before implementation.
- Do not invent data, scores, topology, citations, or performance results.
- Synthetic topology must be labeled as synthetic.
- The copilot explains structured tool results; it does not perform grid
  mathematics itself.
- Every implementation PR needs its declared gate evidence and an independent
  honesty review, as described in `docs/build/swarm-plan.md` and
  `docs/build/converging-swarm-target.md`.
- Preserve real-data boundaries: large downloads are not assumed to be present;
  use explicit skipped/gated states rather than silent fallbacks.

## Working conventions

- Python environment: Python 3.12 managed by `uv`; use `uv sync`.
- Web environment: `web/`, managed with `pnpm`.
- Before changing code, inspect the relevant spec, current branch, and existing
  tests/gates. Keep changes within the declared unit scope.
- For each PR, report the branch, changed paths, checks run, and any blocked or
  unverified items. Stop before merge unless explicitly instructed otherwise.

