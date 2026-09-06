---
title: "Flux — hackathon build target"
status: active
owner: Flux hackathon team
created: 2026-09-05
updated: 2026-09-05
related:
  - "[[../specs/00-overview]]"
  - "[[swarm-plan]]"
---

# Flux hackathon build target

Build a credible, demoable state-configurable grid resilience product: state-scoped public context, plus outage prediction, cascade simulation, firm-generation siting, line-upgrade ranking, and a tool-grounded copilot where a state has validated topology inputs. The repository's Texas / ACTIVSg2000 / ERCOT adapter also requires its source artifacts and build. Flux must make the origin and limits of every result clear enough to defend during a five-minute demo.

Read `docs/specs/README.md` and then the complete amended
`docs/specs/00-overview.md` before work. The amended overview is the current
authority for shared tables, scenario IDs, interfaces, and feature contract.
This document turns that contract into a delivery target; it does not restore
older frozen gates or stale quantitative requirements.

## Delivery focus

The demo should support one coherent path for a state with validated topology: select a storm, inspect its outage risk and cascade, compare a candidate generation site with the baseline, view line-upgrade evidence, and ask a question whose answer traces to tool output and sources. It must also exercise the non-Texas state-context ingestion path with declared source artifacts, while keeping topology, flow, cascade, and siting unavailable until that state has a validated topology contract. The frontend must display synthetic-topology labeling. CEII utility data, Grid2Op operation, and the backup pitch remain outside this build target.

## Feature ownership and dependency path

| Feature | Primary owner | Needs | Demonstrates |
|---|---|---|---|
| Data and shared schema | U1 | amended overview | Contract tables, current AUX coordinates, scenarios, and source provenance in DuckDB |
| Twin build | U2 | U1 | ACTIVSg2000 imports and solves through pandapower DC flow, including impedance branches |
| Outage model | U3 | U1 | Held-out-scenario prediction with recorded inputs and evaluation provenance |
| Cascade simulation | U4 | U2 | Reproducible scenario replay, tripped elements, lost load, and critical-load translation |
| Siting engine | U5 | U4 | Safety/buildability screen and same-scenario with-unit versus baseline evidence |
| Line upgrades | U6 | U1, U2 | Weather/rating and congestion evidence used to rank candidate upgrades |
| Copilot and read APIs | U7 | U3, U4, U5, U6 | Tool-grounded answers, source retrieval, explicit unavailable states |
| Frontend | U8 | U7 routes | Map, replay, siting, line, and copilot views backed by product data |
| Causal layer | U9 | U3, U4 | Clearly labeled causal query supporting the explanatory narrative |

The critical path is U1 → U2 → U4 → U5 → U7 → U8. U3 may proceed after U1;
U6 after U1 and U2; U7 integrates completed capabilities in dependency order.

## Behavioral evidence

Use the feature specification's acceptance criteria as the first source for
what to check. Select the checks below when their behavior is implemented or
changed; run broader checks for integration and demo readiness.

| Area | Meaningful check |
|---|---|
| Environment | Frozen dependency installs preserve lockfiles; required imports work in the supported Python environment. |
| Ingest | Inspect the DuckDB schema and sample provenance; reject current/old AUX mismatches and malformed source columns loudly. |
| Twin | Import the real 2,000-bus case and run pandapower DC flow; ensure impedance branches participate in the overload path. |
| Outage | Preserve holdout provenance and exercise prediction output for a declared scenario; detect leakage and invalid probabilities. |
| Cascade | Replay the same scenario and seed consistently; validate element references and ensure load attribution does not exceed scaled load. |
| Siting | Compare a candidate's with-unit run against the matching baseline and expose safety inputs and sources. |
| Lines | Exercise the weather/rating calculation and ranking order with data that changes the expected outcome. |
| Copilot | Exercise real FastAPI/SSE endpoints; require numerical answers to trace to tool responses and regulatory assertions to cited source text. |
| Web | Build and inspect the app path; verify displayed replay, cards, and streaming text derive from delivered data. |
| Hygiene | Keep secrets and generated data out of Git. |

Focused tests, fixtures, and temporary mutations may be used to establish that
a load-bearing behavior is wired. Reset only mutations you made. A check that
cannot run because a service, credential, or dataset is unavailable must report
that condition clearly; it must never be represented as a successful result.

## Working model

The primary orchestrator coordinates only: it maintains scopes, dependencies,
integration, and status. `gpt-5.6-terra` workers perform implementation in
file-disjoint areas. Isolated worktrees are optional and recommended for
substantive changes that could otherwise overlap. The team may request peer
review or deeper behavioral probes for risky changes, but no per-PR approval,
universal mutation exercise, fixed gate suite, or all-green condition is
required to make progress.

## Non-negotiable honesty

- Copilot numbers come from tool results; the model does not compute them.
- Regulatory and market claims have supporting sources. `[UNVERIFIED]` claims
  remain unresolved and stay out of asserted product copy.
- ACTIVSg2000 is called synthetic anywhere its topology is presented.
- Product views use product data, never a preferred baked answer or plausible
  fallback.
- Missing data, model access, APIs, fetches, and solves are explicit errors or
  unavailable states.
- Credentials, raw data, local databases, and generated environments stay out
  of Git.

## Completion

The build is ready to demo when the integrated path works with the available
inputs, each visible claim has appropriate evidence, and known unavailable
dependencies or limitations are disclosed clearly. Record the commands that
were actually run and their results; do not fill gaps with invented evidence.
