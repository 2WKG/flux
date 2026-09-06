---
title: "Flux team work plan"
status: active
updated: 2026-09-05
related:
  - "[[swarm-plan]]"
  - "[[../specs/00-overview]]"
---

# Flux team work plan

> **Legacy Texas scope (D-5) and work-graph status (D-9).** The Texas/ERCOT framing below is the
> legacy path [`../specs/README.md`](../specs/README.md) declares superseded by
> [`../specs/10-minnesota-demo.md`](../specs/10-minnesota-demo.md) as planning authority; it is
> retained because it is what the code runs. The key lists below are **historical**: Linear is the
> authoritative tracker (`gate/linear-key` enforces it), and the keys transcribed here drift the
> moment an issue moves. See OQ-2 in
> [`../specs/spec-code-reconciliation.md`](../specs/spec-code-reconciliation.md).

This plan records the actual Linear assignments for the Flux 48-hour hackathon.
It uses the lighter coordination workflow requested for this build: owners work
in dependency order, run focused checks for the behavior they change, and
surface unavailable inputs explicitly. It does not add frozen gates, numerical
thresholds, or a mandatory per-PR review ritual.

## Current core demo

The existing two-site demo remains the active Todo path. Its assignments and
dependencies are unchanged:

| Linear issue | Work | Owner | Existing dependency role |
| --- | --- | --- | --- |
| 2WKG-48 | Import the synthetic Texas case with pandapower | William Zhang | Follows 2WKG-38 and enables geometry, base solve, and candidate-bus work. |
| 2WKG-10 | Stress calculation | William Zhang | Existing stress/cascade lane. |
| 2WKG-13 | Two-site comparison | Mixed existing ownership | Existing comparison lane. |
| 2WKG-15 | Demo interface | Mixed existing ownership | Existing UI lane. |

Mira Krishnaiah retains 2WKG-38 (download one synthetic Texas case), which
blocks 2WKG-48. William's existing core assignments remain in place. The
next-wave items below must not become blockers for this core path.

## Next-wave work

All items in this table are Backlog. Their source and local paths are
repository-relative so the implementing Terra worker can begin from the shared
contract and the applicable feature specification.

| Linear issue | Owner | Scope and local source | Dependencies |
| --- | --- | --- | --- |
| 2WKG-88 | Joshua Wangia | Shared DuckDB contract and fixture database; `pipelines/` and `docs/specs/01-data-ingest.md` | Enables 2WKG-89, 2WKG-90, and 2WKG-91. |
| 2WKG-89 | Joshua Wangia | Fixture-safe FastAPI read and map API scaffold; `copilot/app.py`, `copilot/routes/`, `copilot/config.py`, and `docs/specs/05-copilot.md` | Blocked by 2WKG-88; enables 2WKG-92, 2WKG-94, and 2WKG-95. |
| 2WKG-90 | Mira Krishnaiah | Source-labeled line-upgrade ranking and `top_lines`; `pipelines/line_upgrade.py`, `lines/`, and `docs/specs/08-line-upgrade-screen.md` | Blocked by 2WKG-88 and 2WKG-48; enables 2WKG-92. |
| 2WKG-91 | Joshua Wangia | Held-out county outage predictions; `models/outage/` and `docs/specs/02-outage-model.md` | Blocked by 2WKG-88; enables 2WKG-92 and 2WKG-93. |
| 2WKG-92 | Joshua Wangia | Evidence-bound Copilot tool loop, retrieval, and SSE; `copilot/` and `docs/specs/05-copilot.md` | Blocked by 2WKG-89, 2WKG-90, and 2WKG-91; enables 2WKG-95. |
| 2WKG-94 | Mira Krishnaiah | Analytical overlays and Ask views; `web/` and `docs/specs/06-frontend.md` | Blocked by 2WKG-89. |
| 2WKG-95 | Ghadi Khoury | API/SSE deployment and external verification; delivery lane and `docs/specs/05-copilot.md` | Blocked by 2WKG-89 and 2WKG-92. |

## Stretch capability

| Linear issue | Owner | Scope and local source | Dependencies |
| --- | --- | --- | --- |
| 2WKG-93 | Joshua Wangia | Fail-closed causal query artifact; `causal/`, `copilot/tools/causal_query.py`, and `docs/specs/07-causal-layer.md` | Blocked by 2WKG-91 and existing replay input 2WKG-55. |

The Copilot item includes model-default reconciliation and a developer-API
availability check before any model is declared ready. This plan does not
choose or rename a model; configuration alignment remains a Copilot work item.
The Copilot surface registers causal capability as unavailable until 2WKG-93
lands, rather than waiting on the stretch work.

## Meeting-data follow-ups

The meeting follow-ups are Backlog research and collection tasks under existing
2WKG-7. They are nonblocking: the current fixture remains geographic-neutral while
Texas-plus-New-York feasibility is assessed with explicit source, license,
availability, granularity, provenance, and join-feasibility evidence. The
meeting source is [Flux data and scenario discussion](https://notes.granola.ai/t/5ca14bf7-0f0c-469f-acf3-9bc751ebe99a).

| Linear issue | Owner | Research or collection scope |
| --- | --- | --- |
| 2WKG-140 | Mira Krishnaiah | Three-year demand history and county-granularity assessment. |
| 2WKG-135 | Mira Krishnaiah | Texas A&M and Microsoft GridSFM source compatibility; descriptive overlap with 2WKG-38 only. |
| 2WKG-137 | Mira Krishnaiah | Weather, seasonal, and geographic overlay candidates. |
| 2WKG-134 | Mira Krishnaiah | Curated source dictionary and joined-data handoff; blocked by 2WKG-140, 2WKG-135, 2WKG-137, 2WKG-133, and 2WKG-139. |
| 2WKG-133 | Ghadi Khoury | Brookhaven data access, feasibility, and coverage. |
| 2WKG-138 | Ghadi Khoury | Texas-plus-New-York data and scenario feasibility; blocked by 2WKG-140, 2WKG-137, and 2WKG-139. |
| 2WKG-139 | Ghadi Khoury | Industry, urban-rural, and population-growth inputs. |

`2WKG-136` is marked Duplicate of `2WKG-138`; its economic-disruption and
energy-source-shift assumptions are retained by 2WKG-138.

## Assignment record

The canonical engineering backlog assigns five items to Joshua Wangia, two to
Mira Krishnaiah, and one to Ghadi Khoury. The meeting-data backlog assigns four
items to Mira and three canonical items to Ghadi. The richer records under
2WKG-96 were retained and reconciled into the canonical 2WKG-88 through
2WKG-95 DAG. No existing Todo status, core dependency, project membership, or
named core assignment changed.

## Handoff rules

Each implementation worker reads `docs/specs/00-overview.md`, its feature spec,
and `docs/specs/VERIFICATION.md`; changes only its assigned paths; and records
the commands it actually ran. Integrators keep the core demo independent from
next-wave and stretch artifacts. API and UI consumers show explicit unavailable
states until their upstream artifacts exist.
