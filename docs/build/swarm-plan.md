---
title: "Flux — hackathon swarm plan"
status: active
created: 2026-09-05
updated: 2026-09-06
related:
  - "[[converging-swarm-target]]"
  - "[[../specs/00-overview]]"
---

# Flux hackathon swarm plan

> **Work-graph status (D-9).** Four rival work graphs describe this same project: this file's
> units, [`team-work-plan.md`](team-work-plan.md)'s two waves,
> [`../specs/10-minnesota-demo.md`](../specs/10-minnesota-demo.md)'s MN01–MN11 acceptance gates,
> and that spec's numbered execution list. **Linear is the authoritative tracker** —
> `.github/workflows/pr-gates.yml` `gate/linear-key` is what actually enforces a key on every PR,
> and no prose graph here is enforced anywhere. Treat the units below as **historical**: they
> record how the build was divided, not what is currently assigned. (One open question rides on
> this — see OQ-2 in
> [`../specs/spec-code-reconciliation.md`](../specs/spec-code-reconciliation.md).)

The amended `docs/specs/00-overview.md` is the current authority for the
shared technical contract. This plan assigns ownership and integration order
for a fast hackathon build. It does not impose an old gate baseline, numerical
threshold suite, or mandatory per-PR approval process.

## Ownership and dependency DAG

| Unit | Spec | Owned paths | Depends on | Integration contribution |
|---|---|---|---|---|
| U1 data ingest | 01 | `pipelines/**`, `scripts/data/download.sh` | — | DuckDB schema, source provenance, and scenario data |
| U1a intake readiness (2WKG-412) | 01, Minnesota amendment | `pipelines/preflight.py`, `docs/data/data-intake-readiness.md` | U1 raw artifacts | Read-only P0 receipt, legacy-contract diagnosis, and fresh-output rebuild guard; it does not make Texas a Minnesota demo |
| U2 twin build | 03 build | `twin/build.py`, `twin/params.yaml` | U1 | Base pandapower network |
| U3 outage model | 02 | `models/outage/**` | U1 | Prediction and evaluation artifacts |
| U4 cascade simulation | 03 cascade | `twin/cascade.py`, `twin/tools.py` | U2 | Scenario replay and cascade results |
| U5 siting engine | 04 | `siting/**` | U4 | Safety screen and counterfactual scores |
| U6 line upgrades | 08 | `pipelines/line_upgrade.py`, `lines/**` | U1, U2 | Upgrade ranking data and `top_lines` support |
| U7 copilot | 05 | `copilot/**` | U3, U4, U5, U6 | Tool wrappers, source retrieval, and read APIs |
| U8 frontend | 06 | `web/**` | U7 routes | Demo views and playback |
| U9 causal layer | 07 | `causal/**` | U3, U4 | Labeled causal query support |
| U10 historical event baseline | 2WKG-460/461 (contract), 462–472 (hazard bundles), 473 (catalog + split) | `docs/data/event-baseline/**` (schema at `docs/data/event-baseline/event_baseline.schema.json`), `scripts/data/event_baseline_*` | — | County-window contract and validated research receipts; hazard workers own only `events/<hazard>/`; final audit owns catalog and grouped splits |

### U10 integration state (2026-09-06)

The final audit has frozen the 63-request acquisition frame and staged its
catalog, normalized exhaustive-acquisition ledger, source-artifact registry,
and grouped-split generator on 2WKG-473. The artifact audit records coverage
and label shortfalls explicitly; it makes no model-training, forecast, or
performance claim. Final split manifests depend on the current contract
validator accepting the legacy receipt shape without changing the locked
county windows. The source collector dependency is the fail-closed bounded
range repair (PR 249); final evidence uses only exhaustive annual scans.

Suggested waves: U1; then U2 and U3; then U4 and U6; then U5, U7, and U9 as
their dependencies become available; then U8. The critical path is
U1 → U2 → U4 → U5 → U7 → U8.

## How work is coordinated

The primary orchestrator coordinates only. It maintains the DAG, assigns
file-disjoint scopes to `gpt-5.6-terra` workers, resolves dependency order,
and keeps an accurate integration status. It does not write product
implementation.

Use an isolated worktree for substantive work when it prevents overlapping
edits; a small, clearly isolated change may work directly in the shared
checkout. Before a worker begins, record its paths, dependency assumptions, and
the portion of the spec it owns. Avoid broad shared-file edits while related
workers are active.

Each worker should:

1. Read `CLAUDE.md`, the amended overview, its feature spec, and relevant
   verification notes.
2. Implement only its assigned paths and surface a contract conflict early.
3. Run checks that exercise the changed behavior and record the exact commands
   and actual outcome.
4. Hand off integration notes: touched interfaces, data prerequisites, known
   limits, and unavailability states.

Peer review, a browser walkthrough, or a targeted mutation probe are useful
when a change carries risk or a claim is load-bearing. Choose them based on the
change; they are not automatic merge gates. Health/doctor checks are reserved
for setup changes or actual connectivity troubleshooting.

## Integration standards

Integrate dependencies in DAG order and keep interfaces aligned with the
amended overview. For a demo-ready pass, exercise the coherent storm → outage
→ cascade → siting → frontend → copilot path, plus the line-upgrade view.
Validate behavior that is visible or load-bearing; do not require unrelated
components to be green before delivering a focused feature.

Never fabricate a command result, source, citation, model output, or fallback
value. Missing datasets, credentials, API access, or a failed solve must be
recorded as an explicit unavailable or error state. Do not copy credentials or
implementation material into Buckeye repositories; Buckeye practices are
reference knowledge only.
