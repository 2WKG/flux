# Flux hackathon build specs

> **Current authority — Minnesota demo.** [10-minnesota-demo.md](10-minnesota-demo.md)
> supersedes the legacy Texas/NY geography, ERCOT/Uri scenarios, ACTIVSg2000 reuse,
> provider defaults, and acceptance claims below. The checked-in five-bus synthetic preview
> must never be presented as a Minnesota network or interconnection study.

> **Shared fixture contract.** [10-duckdb-contract.md](10-duckdb-contract.md) coexists with
> both scopes as a geography-neutral identity, unit, coordinate, and provenance contract. It
> contains no geographic fixture records and does not derive Minnesota data from the Texas case.

> **Authority lattice and the spec↔code ledger.** [`00-overview.md`](00-overview.md)
> §"Authority lattice (D-0)" states the single precedence order these documents follow, and
> [`spec-code-reconciliation.md`](spec-code-reconciliation.md) records every known place a spec
> disagreed with what `master` implements, what the code does, and how it was resolved. Read the
> ledger before trusting a contract claim in any spec below.

> **Visual and interaction direction.** [UI style guide](../design/ui-style-guide.md) and its [token reference](../design/ui-tokens.css) guide presentation only; they do not supersede the authority lattice or define API, data, geography, scenario, or provenance contracts.

Product name: **Flux** (the repository and package stay `flux`; see `00-overview.md` amendment A8 and the retained pitch document).
Headline: **state-configurable grid resilience analysis: outage context, synthetic-topology analysis where validated, and siting**. The repository's Texas / ACTIVSg2000 / ERCOT topology adapter requires its source artifacts and build; other states require their own validated source artifacts and configuration.
with the line-upgrade ranker (spec 08) as one screen inside it. The pitch is two ideas (pitch v2): the
backup is **Speed-to-Power** (large-load verification + grid headroom ranking, spec 09), whose wire half
reuses spec 08's tables and `top_lines` tool. The shared contract (repo layout, DuckDB tables, scenario IDs,
copilot tool signatures — thirteen tools including the static interactive tools) lives in `00-overview.md` §2 and wins over any downstream spec.

Every spec has the same sections in order: Purpose · Inputs · Outputs · Algorithm or Design ·
Interfaces · Acceptance criteria · Demo hook · Risks/unknowns · Weekend time-box.
Anything the author could not confirm exists is marked `[UNVERIFIED]`.

| # | File | Owns | One-line purpose |
|---|---|---|---|
| 00 | [`00-overview.md`](00-overview.md) | contract, plan | The decision, shared contract (layout, tables, scenarios, tools), 6-layer architecture, unit dependency graph, demo script → units, Day 1/Day 2 hour plan, honest answers, judge hooks, definition of demo-ready. |
| 01 | [`01-data-ingest.md`](01-data-ingest.md) | `pipelines/`, `scripts/data/download.sh`, `data/` | Download and load ACTIVSg2000, counties, EIA-860/930, EAGLE-I, weather, storm events, hazards, critical loads, site candidates, and scenarios into `data/duck/grid.duckdb`; ships the fixture DB every other unit starts on. |
| 02 | [`02-outage-model.md`](02-outage-model.md) | `models/outage/` | County-level LightGBM outage model on EAGLE-I + weather + hazard; holds out `uri_2021`/`beryl_2024`/`helene_2024`; writes `outage_predictions` and the on-screen accuracy number. |
| 03 | [`03-cascade-sim.md`](03-cascade-sim.md) | `twin/` | pandapower model of the synthetic grid; weather-driven failure → DC power flow → overload trip loop; county and critical-load translation; writes `cascade_runs`; exposes the `run_cascade` core the siting engine re-runs. |
| 04 | [`04-siting-engine.md`](04-siting-engine.md) | `siting/` | Safety/buildability screen (OR-SAGE/STAND criteria on open layers) plus grid-strength value from counterfactual cascade re-runs with a 300 MW / 1 GW unit online; writes `site_scores` and persists the demo counterfactual cascade run. |
| 05 | [`05-copilot.md`](05-copilot.md) | `copilot/` | FastAPI host: thin read APIs for the map and the Claude (`claude-sonnet-5`) tool loop over `predict_outage`, `run_cascade`, `score_site`, `top_lines`, `sql`, `cite`, plus `compare_interventions`, `top_critical_elements` (A8) and `causal_query` (07); regulatory-PDF retrieval; SSE `/ask`; the model narrates, never computes. |
| 06 | [`06-frontend.md`](06-frontend.md) | `web/` | Vite + React + deck.gl + MapLibre: line/bus/county layers, outage choropleth with actual toggle, cascade playback, critical-load panel, siting cards with counterfactual toggle, line-upgrade screen, Ask box. |
| 07 | [`07-causal-layer.md`](07-causal-layer.md) | `causal/` | pgmpy/DoWhy structural model (weather → exposure → line failure → customers out, with utility investment as confounder) for "weather vs under-investment" decomposition and the counterfactual-replay narrative. |
| 08 | [`08-line-upgrade-screen.md`](08-line-upgrade-screen.md) | line scoring + one web screen | Line-upgrade screen inside the twin (Idea 1) AND the wire half of the Speed-to-Power backup: IEEE 738 DLR uplift from county wind, reconductor uplift and REFA costs, congestion proxy from twin loading, MW-per-$ ranking, FERC RM24-6 screen, SPARK flag; writes `line_upgrade_scores` + `line_upgrade_detail`; serves `top_lines`. |
| 09 | [`09-backup-idea2-datacenter-load.md`](09-backup-idea2-datacenter-load.md) | `dc_*` tables, `copilot/tools/dc.py` | Backup: **Speed-to-Power** = load half (data-center project registry, entity resolution/duplicate detection, reality model with intervals, phantom ratio, stranded cost; tools `phantom_ratio`/`duplicates`/`score_dc_site`/`cost_exposure`) + wire half by reference to 08 (`top_lines`, new `line_profile(line_id)` over `line_upgrade_detail`), joined in the Grid Impact Score (0–100, 7 components, "what makes this a 90" incl. a named line upgrade). |
| 10 | [`10-duckdb-contract.md`](10-duckdb-contract.md) | Minnesota artifact identity/provenance contract, `mn_*` tables | Minnesota data identity, unit, coordinate, and provenance contract; owns `mn:<artifact_kind>:<sha256-16>` identity and the availability/model-mode/field-provenance envelope. Implemented by `pipelines/minnesota_schema.py`. |
| 10 | [`10-minnesota-demo.md`](10-minnesota-demo.md) | Minnesota demo scope | Current authority for the demo geography, scenarios, and acceptance claims; supersedes the legacy Texas/ERCOT/ACTIVSg2000 demo contract. |
| 11 | [`11-physical-inventory-contract.md`](11-physical-inventory-contract.md) | `pipelines/physical_inventory.py`, `pipelines/assemble_physical_inventory.py`, `physical_*` tables | Versioned, source-qualified physical-grid inventory artifacts: canonical JSON + SHA-256 identity, asset/geometry/provenance rules, per class/scope coverage ledger, and state-release composition. Adds the seven `physical_*` DuckDB tables registered in `00-overview.md` §2.2 (amendment A12). Diverges from spec 10 by declaration, not silently. |

Critical path for the weekend: **01 → 03 → 04 → 06** (siting screen). See `00-overview.md` §4.1 and §7.

Run order (from `00-overview.md` §4.2):

```
uv run python -m pipelines.run_all --texas                                   # 01
uv run python -m models.outage.train --holdout uri_2021 beryl_2024 helene_2024
uv run python -m models.outage.predict --scenario uri_2021                   # 02
uv run python -m twin.build
uv run python -m twin.cascade --scenario uri_2021 --seed 0                   # 03
uv run python -m siting.candidates
uv run python -m siting.rank --unit 1000 --scenario all                      # 04
uv run python -m causal.fit                                                  # 07
uv run uvicorn copilot.app:app --port 8000                                   # 05
pnpm --dir web dev                                                           # 06
```
