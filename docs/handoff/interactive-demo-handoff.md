# Handoff — interactive simulation, site restructure, and GNN

**Status: work stopped mid-implementation and handed off. Nothing here is finished.**

Four branches carry partial work. Every one is incomplete, and **no tests were run on any of
them**. Treat every claim in the code as unverified until you run it yourself. Where a section
below says something was not done, it was not done — that is not hedging.

Everything below is Texas / ACTIVSg2000. Minnesota stays aggregate-mode per
[`10-minnesota-demo.md`](../specs/10-minnesota-demo.md) and must never render lines, flows,
loading, trips, or cascades.

---

## 1. The governing spec

[`docs/specs/12-interactive-simulation.md`](../specs/12-interactive-simulation.md), open as
**PR #310**. Docs only, based on current master, no code paths touched.

It is numbered 12 because master already defines spec 11 (physical inventory contract). It
declares the interactive-physics lane and bounds fidelity to DC screening — no reactive power,
no dynamics, no protection modeling — with `model_fidelity`, `network_provenance`, and
`limitations` required on every response.

---

## 2. Branches carrying partial work

| Branch | Issue | Base | State |
| --- | --- | --- | --- |
| `williamyanjunzhang/2wkg-483-causal-explainer-section` | 2WKG-483 | PR #302 | 4 files, 1,315 lines. Components and toy model drafted. **Index barrel unfinished, no tests written, none run.** |
| `williamyanjunzhang/2wkg-484-jepa-explainer-section` | 2WKG-484 | PR #302 | 6 files, 1,080 lines. Section, embedding schematic, evaluation artifact. **Tests written but never run.** |
| `williamyanjunzhang/2wkg-485-gnn-explainer-section` | 2WKG-485 | PR #302 | 4 files, 754 lines. Section and message-passing schematic. **Render test in progress, no tests run.** |
| `williamyanjunzhang/2wkg-490-solver-labelled-training-samples` | 2WKG-490 | PR #258 | 3 files, 362 lines. Contracts and hour selection only. **Sampler, split, and tests all missing.** |

All three explainer branches base on **PR #302** (`joshuawangia/2wkg-482-...`), the explainer
page, which is itself unmerged. The sample generator bases on **PR #258**, which is unmerged
*and* conflicting with master.

### First thing to do

Run the tests. `cd web && npm run test:data` style commands per `web/package.json`, and
`uv run --extra dev pytest gnn/` for the Python. Expect failures — the code was never executed.

---

## 3. What remains, per branch

### 2WKG-483 — causal explainer section

Drafted: `CausalSection.tsx`, `causalToy.ts`, `evidenceGate.ts`, `index.ts` under
`web/src/explainer/causal/`.

Remaining:
- Finish the index barrel export.
- Write tests as `.test.mjs` for `node --test`, matching `web/src/pages/toyCascade.test.mjs`.
- Verify the confounder interaction actually distinguishes **conditioning** from **intervening** —
  that distinction is the entire teaching point and is easy to get subtly wrong.
- Confirm nothing renders an effect claim that `copilot/tools/causal_query.py` would not return.

### 2WKG-484 — JEPA explainer section

Drafted: `JepaSection.tsx`, `embeddingSchematic.ts`, `recordedEvaluation.ts`,
`embeddingSchematic.test.mjs`, and `recorded-evaluation.artifact.json`.

**The evaluation artifact is real, not fabricated — but read this before trusting it.** It cites
the genuine EAGLE-I 2024 source with sha256 `d5d75ea4ef3943446aaf0623e9b451cb4e7796d20cc379de9cf497106ebab2e6`,
which matches `data/sources/texas-eaglei-2021-2024.json`. It records a persistence baseline and
self-reports a **22.5× train/holdout regime asymmetry** (train count MAE 7630.29 vs holdout
339.59), stating plainly that beating persistence on a calm holdout does not establish
storm-time skill. That caveat must survive to the screen.

Its `regeneration` block says it was produced by `models/jepa` at revision `3dc2389` and that
several fields were **added by hand** from values already in the file. It cannot be regenerated
without the gitignored 1.4 GB EAGLE-I source.

Remaining:
- Run `embeddingSchematic.test.mjs`.
- Decide whether committing a copied, partly hand-edited artifact into `web/src/` is acceptable,
  or whether the section should read it from the real `models/jepa` output path instead. **My
  recommendation: the latter.** A hand-edited artifact in the frontend is exactly the kind of
  thing that erodes trust in the numbers next to it.
- Reconcile with 2WKG-474 / PR #259, which owns the real JEPA work.

### 2WKG-485 — GNN explainer section

Drafted: `GnnSection.tsx`, `messagePassing.ts`, `messagePassing.test.mjs`, `index.ts`.

Remaining:
- Run the tests; a render test was mid-write.
- **Re-verify the status label against what has actually landed.** As of this handoff no GNN is
  running: no checkpoint, no training run, no error envelope. If that is still true the section
  must say "not running" and show zero model-produced numbers. Do not inherit the label from the
  code — check.
- `graphify-out/` is a knowledge graph of the *documentation*. It is not grid ML. Do not let it
  drift into this section.

### 2WKG-490 — solver-labelled sample generator

Drafted: `gnn/contracts.py`, `gnn/hours.py`, `gnn/__init__.py`.

Remaining — most of the issue:
- The deliberate sampler itself. Uniform N-1 sampling mostly produces contingencies where
  nothing happens, and a model trained on that learns to predict "nothing happens." Weight
  toward high-flow corridors, add a smaller N-2 budget, include placement samples.
- **Contingency-level train/held-out split.** Random row splits leak, because near-identical
  contingencies land on both sides and the held-out score stops meaning anything.
- Seeding, resumability, and regeneration metadata.
- All tests. Then generate a real batch against `data/duck/grid.duckdb` and record actual counts
  and timings rather than estimates.

---

## 4. Not started at all

- **2WKG-486** — shared navigation, unified truth-label vocabulary, per-page failure states.
- **The mount PR.** The three explainer sections were each built in their own directory and
  deliberately do **not** modify `ExplainerPage.tsx`, so they would not collide. Someone still
  has to mount all three and extend `web/src/status-vocabulary.test.mjs` to cover them.
- **The wiring PR** — inject the real `twin` implementation into the route seam in
  `copilot/interactive_routes.py` (PR #261). Needs both #258 and #261 as ancestors. I did not
  start it because #258 is conflicting, and building on an unstable two-branch base produces a
  PR nobody can review.
- **2WKG-491 / 492 / 493** — GNN model, evaluation envelope, screen-then-confirm serving.

---

## 5. PR operations still outstanding

These were deliberately left for a human — they touch other people's PRs.

```
gh pr close 292 --comment "Superseded by #304."
gh pr edit 305 --base joshuawangia/2wkg-479-main-page-integration-fix
```

**#292 and #304 are duplicate work on 2WKG-479** with byte-identical `MainPage.tsx` diffs
(+222/−408). #304 is the superset — it also fixes the e2e spec, router, and four test files.
Two PRs racing on one file is the likeliest source of lost work here.

**#305 must stack on #304.** It is a new `web/src/main-assistant/` directory so it will not
conflict, but it has to be mounted inside `MainPage.tsx`, which #304 rewrites. Merged flat,
whichever lands second either conflicts or the assistant never renders.

**#258 needs a rebase.** It is conflicting and was 777 commits diverged. It carries
`twin/build.py`, `twin/cascade.py`, `twin/contracts.py`, and `twin/tools.py`, and it gates
2WKG-480, 452, 490, and 493. It is the single highest-impact unblock in the repo.

---

## 6. Two findings worth carrying forward

**The 138 kV placement threshold is wrong for this network.** Spec 12 §12.3 rule P1 reuses spec
04's "nearest bus with `base_kv >= 138` within 40 km." ACTIVSg2000's transmission voltages are
115 kV (826 buses), 161 kV (453), 230 kV (152), and 500 kV (120) — **there is no 138 kV class at
all**, so that filter silently excludes the single largest transmission class. Verified against
the built database. Fix before anyone implements placement feasibility.

**P0 preflight checks existence, not integrity.** `_missing_p0_inputs` in `pipelines/build.py`
tests only `path.exists()`, while sha256 for every one of those files already sits in
`data/sources/*.json`. That is how a 2 GB corrupt EAGLE-I CSV passed the gate and failed 118,294
lines into a DuckDB load. Both EAGLE-I files have since been re-downloaded and verified byte-exact.
Adding a checksum step to preflight is cheap and belongs in 2WKG-426.

---

## 7. Database state

`data/duck/grid.duckdb` is built and verified — 790 MB, 2,000 buses all with real AUX
coordinates inside the Texas bounding box, 3,206 branches all carrying `rate_a_mw` and geometry,
67,109 MW nominal load against 96,292 MW generation nameplate. EAGLE-I loaded counts
(2,443,041 for 2021 and 2,921,200 for 2024) match `data/sources/texas-eaglei-2021-2024.json`
exactly, which independently confirms the re-downloaded sources.

The 505 `ingest_warnings` are the design working, not failures: 504 are zone-type storm events
falling outside the two pinned NWS crosswalk validity windows, flagged rather than mapped with a
wrong-vintage crosswalk. One is a military facility outside loaded county coverage.

`critical_loads` contains **only DoD rows (20)**. The contract defines `dod|hospital|water`;
hospitals and water never loaded. Anything promising "named critical facilities lose supply"
currently has only military bases to work with.
