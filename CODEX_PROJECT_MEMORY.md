# Codex project memory — flux / GridMind

This file is a durable project-context note for future Codex sessions. It is
not product code and should be updated through a pull request.

## Repository

- GitHub: `Wyzard1004/flux`
- Product: **GridMind**, a state-configurable grid resilience prototype. Public context is state-scoped; the only implemented topology adapter is Texas / ACTIVSg2000 / ERCOT and requires its source artifacts and build.
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


## Scope supersession — read before using the build order above

The Linear project **Flux — 48-hour Grid Resilience Hackathon** (team `2WKG`) carries a
document, *Flux — 48-hour hackathon build plan*, which states: "This plan replaces the earlier
platform/pilot roadmap. Linear items outside this scope are canceled rather than carried as
hackathon blockers."

For the hackathon weekend it therefore supersedes the U0–U9 unit table above and the
`docs/build/` swarm specs. Its cut list explicitly removes ML training, copilot/RAG, cascade
dynamics, EAGLE-I ingestion, licensing scoring, databases and APIs.

The reduced scope is one screen: a geographic-neutral synthetic case under one fixed cold-weather stress,
with a baseline and two 300 MW firm-generation additions precomputed in Python/pandapower,
written to JSON on disk, and read by a static React/Vite build served through the **existing**
Cloudflare Tunnel at `bouncepulse.com`. Target layout is `web/`, `model/`, `data/demo/`,
`docs/planning/`.

The `docs/build/` and `docs/specs/` trees are not deleted — they remain the post-hackathon
roadmap. Do not implement against them this weekend.

## Ghadi's task ownership (Linear 2WKG)

Eight issues, ~180 minutes of timeboxed work, in three independent dependency chains.
All were still `Todo` as of 2026-09-05.

**Chain A — deployment (critical path)**

    H02 (Mira) -> H03* -> R08* -> R09 (Joshua) -> R10* -> R11*
    2WKG-20      2WKG-27 2WKG-83  2WKG-84         2WKG-85 2WKG-86

`H03` and `R08` are back-to-back and both Ghadi's, 15 minutes each. They gate Joshua's `R09`
and the entire judge-access path — the highest-leverage half hour on the board.

**Chain B — UI polish (all behind Mira)**

    U01 2WKG-68 -----------------> U04* 2WKG-71
    U05 2WKG-72 -+- U06 2WKG-73 -> U09* 2WKG-76
                 +- U07 2WKG-74 -> U10* 2WKG-77

**Chain C — claims check**

    R02 (Joshua) 2WKG-79 -> R03* 2WKG-22

`R03` strips unsupported outage-forecast, real-facility-protection, licensing and black-start
claims. The `docs/pitch/` and `docs/specs/` text in this repo contains exactly that class of
claim, so R03 is a check against the demo script, not against these specs.

Acceptance criteria for `H03` and `R03` follow the Linear plan document, not the specs in this
repository.

## Standing hackathon rules

- Timeboxes are hard. Exceeding one means invoking the task's fallback or cutting scope, never
  extending the roadmap.
- Each Linear issue expects the file/change or short verification evidence attached on
  completion.
- A tie between candidate sites A and B is an honest result; do not manufacture a winner.
- ACTIVSg2000 is synthetic and candidate-to-bus mappings are illustrative. Both must be stated
  on screen and in the pitch.
- The demo runs from precomputed JSON with the network off; a backup recording and screenshot
  stay reachable.

## R08 field notes — bouncepulse.com tunnel (checked 2026-09-05)

Discovery done ahead of the task unblocking. Current facts:

- `bouncepulse.com` resolves to `172.67.218.236` / `104.21.24.128` — Cloudflare proxy IPs, so
  the domain is on Cloudflare and proxied.
- `HTTPS HEAD https://bouncepulse.com` returns **530** (Cloudflare error 1033, "Tunnel not
  found"). DNS points at a Cloudflare Tunnel whose connector is not currently running.
- `cloudflared` is **not installed on this Windows machine**: absent from `PATH`,
  `~/.cloudflared/`, `Program Files`, `Program Files (x86)`, `AppData`, `ProgramData`, and the
  Windows service list.

Implication for R08: the "existing tunnel" is not hosted on this laptop. Before the task can be
written up, establish which machine owns the connector and who runs it — that is precisely the
"who keeps the host powered and online" field the issue asks for. If no machine owns it, the
team is one step further back than the board assumes, and R09 (Joshua) inherits that gap.

The 530 is expected while nothing is being served; it is not evidence the tunnel config is
broken. Re-check after the connector starts.

## Current state snapshot — captured 2026-09-05 19:45Z

This is a point-in-time handoff. Check the current branch, open PRs, and Linear
before acting on its status notes. The accompanying Graphify artifacts are a
pre-rebase snapshot and do not yet index the data-quality or metric-layer files
that subsequently landed on `master`.

**State scope:** public context can be ingested for a selected U.S. state when its declared
source artifacts are supplied. The only implemented topology adapter is Texas / ACTIVSg2000 /
ERCOT and requires its source artifacts and build. `docs/specs/10-minnesota-demo.md` is a
planning contract, not a checked-in Minnesota fixture; the checked-in five-bus preview represents
no state.

**Storage is settled: DuckDB.** Recorded as contract amendment **A9** in
`docs/specs/00-overview.md`; the `[DECISION]` in the curation plan is closed. Postgres was
never adopted and Mongo/NoSQL was never proposed. `pipelines/db.py` is the executable
authority — **19 contract tables** with FK constraints,
`county_fips` as a 5-char checked string, and provenance columns on every table. Where a
document and that module disagree, the module wins. Read
`pipelines/db.py::SCHEMA_VERSION` for the current contract version.

**The bottleneck is review and merge, not building.** At capture time, around 38 PRs were
open; query GitHub for live counts. Two collisions have already cost real work: PR #27 rebuilt
a source registry and downloader that already existed as
`datasets/catalog.json` + `download.py`, and a duplicate
set of child issues (2WKG-289–292) was created against 2WKG-276 minutes after 279/280/283/285
already existed. Before starting an issue, check `git worktree list`, open PRs for a matching
branch, and `list_issues` filtered by `parentId` — `get_issue` on a parent never returns its
children.

**Two contradictions the team must resolve; both are documented, neither is decided.**
`README.md` describes Node/Express with `GET /api/demo` and says it "intentionally does not
use Vite", while `STACK-LOCK.md` locks React+Vite served statically with no API — the built
app violates the lock twice. And whether `docs/build/converging-swarm-target.md` and
`swarm-plan.md` are superseded: this file says they are, but copilot work is actively landing
against spec 05. Tracked in Linear 2WKG-296.

**Parallel agents.** Ghadi runs Codex in a second terminal on this repo. Both act as the same
Linear user, so neither can see the other's claims. Split by workstream, and only one agent
should ever run `/graphify` — `graphify-out/` is a single shared artifact.
