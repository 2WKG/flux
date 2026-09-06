# 00 — Overview: Flux — State-Configurable Grid Resilience Analysis

> **State scope:** Flux can ingest public context for a selected U.S. state when
> its declared source artifacts and configuration are supplied. Topology-backed
> analysis remains available only for a state with a validated topology contract.
> The repository's only topology adapter is Texas / ACTIVSg2000 / ERCOT, and it
> requires its source artifacts and build. The checked-in
> five-bus preview represents no state. [`10-minnesota-demo.md`](10-minnesota-demo.md)
> is planning authority for a Minnesota demonstration; it does not create a
> Minnesota fixture or topology. [`10-duckdb-contract.md`](10-duckdb-contract.md)
> remains the geography-neutral storage contract.

Status: frozen for the weekend build. Product name: **Flux** (amendment A8; the repository and package stay `flux`).
Source pitch: `docs/pitch/hackathon-pitches-and-designs.md` (v2, 3 Sept 2026, "Two ideas").
Every other spec in this directory conforms to the shared contract restated here.

**Authority lattice (D-0).** Four documents used to claim the top of it in four different ways
(`CLAUDE.md`, this file, `README.md`, `10-minnesota-demo.md`, `10-duckdb-contract.md`). One order
now, highest first, and `CLAUDE.md` states the same one:

1. **Executable source, migrations, generated wiring, and tests** are the fact. Where prose and
   code disagree, the code wins and the prose is corrected with the change.
   [`spec-code-reconciliation.md`](spec-code-reconciliation.md) is the standing ledger of the known
   disagreements and how each was resolved.
2. **[`10-minnesota-demo.md`](10-minnesota-demo.md) and
   [`10-duckdb-contract.md`](10-duckdb-contract.md), inside what they explicitly supersede** —
   Minnesota geography, scenarios, model mode, the storage/identity contract, and demo acceptance
   language.
3. **This file** for the rest of the shared technical contract: table names, column names, tool
   signatures, scenario IDs, and the route inventory in §4.2. It wins over specs 01–09 and over
   the design and build documents, and it is not limited to the four items the previous wording
   listed.
4. **Downstream feature specs (01–09), design documents, and runbooks.**

---

## 1. Purpose

Build a demoable, end-to-end planning layer that connects three questions on one map:

1. **Where will the grid fail?** — a learned county-level outage model (LightGBM on EAGLE-I + weather).
2. **What does that failure cascade into?** — a physics cascade on a synthetic Texas grid (pandapower DC power flow, iterative overload tripping), tagged with critical loads (DoD installations, hospitals, water).
3. **Where should the next gigawatt of firm generation go?** — a siting engine that scores every candidate site on NRC-style safety exclusions AND on measured grid-strength value (loss-of-load reduction, congestion relief, black-start reach) by re-running the cascade with the unit online.

Plus one line-upgrade screen inside Idea 1 ("which existing wires to upgrade": DLR vs. reconductor
ranking, spec 08) and a Claude tool-calling copilot that narrates, plans, and cites — and never computes.

### The decision (already made — do not relitigate)

The pitch is **two ideas** (pitch v2). Idea 1 (Flux) is the headline. The line-upgrade screen
(spec 08) stays inside Idea 1 — it is not a separate idea. The backup is **Speed-to-Power: large-load
verification + grid headroom ranking** (spec 09); its "wire half" REUSES spec 08's
`line_upgrade_scores` + `line_upgrade_detail` tables and the `top_lines` tool, so no line-scoring code
is duplicated whichever pitch leads.

| Item | Decision |
|---|---|
| Headline | Idea 1 — **Flux**: grid digital twin + outage prediction + nuclear siting |
| Embedded screen | Line-upgrade ranking, one screen inside the twin (`08-line-upgrade-screen.md`); also the wire half of the backup |
| Backup pitch | Idea 2 — Speed-to-Power: large-load verification (load half, `dc_*` tables) + grid headroom ranking (wire half = spec 08), separate deck (`09-backup-idea2-datacenter-load.md`) |
| Geographic scope | **State-configurable public context.** Each selected state needs declared, validated source artifacts. The repository's only topology adapter is the ACTIVSg2000 synthetic grid, ERCOT balancing authority, and 254 Texas counties; it requires its source artifacts and build. |
| Other-state topology | Not implied by state-context ingestion. A state needs a validated network and explicit model contract before Flux can show topology, flow, cascade, or siting results there. |
| Topology honesty | Synthetic topology, stated plainly on the slide and in the copilot system prompt. Real topology is CEII; architecture has a slot for it. |
| LLM | Claude via the Anthropic SDK, model id `claude-sonnet-5` for tool loops. |

---

## 2. Inputs (tables/files)

The overview owns no data. It defines the shared contract that every unit reads and writes.

### 2.1 Repo layout (shared contract — do not rename)

```
flux/
├── pyproject.toml               # uv-managed, Python 3.12, one root project; deps for every python dir
├── uv.lock
├── scripts/
│   └── data/download.sh         # every raw download, idempotent, writes data/raw/<source>/
├── data/
│   ├── raw/<source>/            # UNTRACKED (.gitignore). e.g. data/raw/eaglei/, data/raw/activsg2000/
│   ├── duck/grid.duckdb         # THE database. One file. Every unit reads/writes here.
│   └── parquet/                 # column stores for big time series (weather_hourly, eaglei_outages)
├── pipelines/                   # python ingest → DuckDB (spec 01)
├── twin/                        # pandapower model build + cascade loop (spec 03)
├── models/outage/               # LightGBM training + inference (spec 02)
├── siting/                      # safety exclusions + grid-value delta (spec 04)
├── causal/                      # pgmpy/DoWhy layer (spec 07)
├── copilot/                     # FastAPI + Claude tool-calling (spec 05); also serves read APIs to web/
├── web/                         # Vite + React + deck.gl + MapLibre, pnpm (spec 06)
└── docs/specs/                  # this directory
```

Rules:
- `data/raw/` is gitignored. `data/duck/grid.duckdb` and `data/parquet/` are gitignored too but are the
  hand-off artifact between units; whoever finishes an ingest posts the DuckDB file to the shared drive / box.
- No PostGIS this weekend. All geometry is WKB blobs or `lon`/`lat` columns in DuckDB, EPSG:4326.
  DuckDB `spatial` extension is allowed for `ST_*` functions inside pipelines.
- One `pyproject.toml` at root. No per-directory Python packages. Import paths are `pipelines.*`, `twin.*`,
  `models.outage.*`, `siting.*`, `causal.*`, `copilot.*`.

### 2.2 DuckDB tables (shared contract — exact names and columns)

All geometry as WKB (`geom_wkb BLOB`) or `lon DOUBLE, lat DOUBLE`, EPSG:4326. Timestamps are `TIMESTAMP` in UTC.

| Table | Columns | Written by | Read by |
|---|---|---|---|
| `buses` | `bus_id, name, base_kv, lon, lat, county_fips, ba_code` | 01 | 03, 04, 06, 08 |
| `lines` | `line_id, from_bus, to_bus, base_kv, r_pu, x_pu, rate_a_mw, length_km, geom_wkb` | 01 | 03, 06, 08 |
| `gens` | `gen_id, bus_id, fuel, pmax_mw, eia_plant_id` | 01 | 03, 04, 06 |
| `loads` | `load_id, bus_id, p_mw_nominal` | 01 | 03 |
| `counties` | `county_fips, name, state, pop, geom_wkb` | 01 | 02, 03, 04, 06, 07 |
| `critical_loads` | `cl_id, kind[dod\|hospital\|water], name, lon, lat, bus_id, county_fips` | 01 | 03, 04, 06 |
| `eaglei_outages` | `county_fips, ts, customers_out` | 01 | 02, 06, 07 |
| `weather_hourly` | `county_fips, ts, wind_ms, gust_ms, temp_c, ice_mm, precip_mm` | 01 | 02, 03, 07, 08 |
| `storm_events` | `event_id, ts_begin, ts_end, county_fips, type, magnitude` | 01 | 02, 07 |
| `hazard_static` | `county_fips, nri_score, wildfire_hazard, seismic_pga` | 01 | 02, 04, 07 |
| `ba_load_hourly` | `ba_code, ts, demand_mw` | 01 | 03 |
| `site_candidates` | `site_id, name, kind[coal_retired\|coal_retiring\|nuclear_existing\|doe_federal\|dod], lon, lat, county_fips, bus_id, capacity_slot_mw` | 01 | 04, 06 |
| `scenarios` | `scenario_id, name, kind[historical\|forecast\|synthetic], ts_start, ts_end` | 01 | all |
| `outage_predictions` | `scenario_id, county_fips, ts, p_out, customers_at_risk, driver` | 02 | 03, 05, 06 |
| `cascade_runs` | `run_id, scenario_id, hour, tripped_element_ids_json, lost_load_mw, counties_dark_json, critical_loads_lost_json` | 03 (and 04 for counterfactual runs) | 04, 05, 06 |
| `site_scores` | `site_id, scenario_id, unit_mw, safety_score, safety_flags_json, grid_value_score, lol_reduction_mwh, congestion_relief_pct, blackstart_reach_mw` | 04 | 05, 06 |
| `line_upgrade_scores` | `line_id, scenario_id, congestion_usd_yr, dlr_uplift_mw, reconductor_uplift_mw, dlr_cost_usd, reconductor_cost_usd, mw_per_musd, ferc_screen_pass, spark_eligible, ranking_version, contract_version, computed_at, simulation_run_id, grid_input_sha256, weather_input_sha256, cost_params_sha256, source_kind` — key `(line_id, scenario_id)`; `source_kind` is explicit fixture/observed/simulated/heuristic provenance and legacy NULL is unavailable, see A10 | 08 | 05, 06 |
| `physical_inventory_schema_meta` | `key, value` — `key='contract_version'` holds `pipelines.physical_inventory.CONTRACT_VERSION` | 11 | 11 |
| `physical_inventory_manifests` | `artifact_id, contract_version, geography_id, artifact_version, canonical_json, inventory_mode[physical_observed\|fixture\|synthetic], electrical_model_mode[none\|source_backed\|synthetic\|aggregate], created_at, content_sha256` | 11 | 11, read APIs |
| `physical_inventory_sources` | `artifact_id, source_id, authority, source_ref, source_version, retrieved_at, license_or_terms, content_sha256` — key `(artifact_id, source_id)` | 11 | 11, read APIs |
| `physical_assets` | `artifact_id, asset_id, asset_class, asset_kind, source_id, source_record_id, geometry_geojson, geometry_crs, geometry_precision_m, geometry_accuracy_basis, geometry_derivation_method, geometry_status[source\|derived\|unavailable]` — key `(artifact_id, asset_id)` | 11 | 11, read APIs |
| `physical_asset_terminals` | `artifact_id, terminal_id, asset_id, source_id, source_record_id` — key `(artifact_id, terminal_id)` | 11 | 11, read APIs |
| `physical_connectivity_edges` | `artifact_id, edge_id, from_terminal_id, to_terminal_id, source_id, source_record_id` — key `(artifact_id, edge_id)` | 11 | 11, read APIs |
| `physical_coverage` | `artifact_id, asset_class, scope_id, status[complete\|partial\|unknown\|unavailable], observed_count, denominator_count, unknown_count, unavailable_count, denominator_basis, source_scope, reason` — key `(artifact_id, asset_class, scope_id)` | 11 | 11, read APIs |

`element_ids` (the `run_cascade` input) are plain element id strings as they appear in `lines.line_id` /
`buses.bus_id` / `gens.gen_id`. `cascade_runs.tripped_element_ids_json` is owned by spec 03: an ordered
list of `{"element_id", "kind": line|trafo|gen|bus, "stage", "cause": weather|overload|island|forced}`.
`cascade_runs.run_id` is also owned by 03: `f"{scenario_id}-s{seed}-{sha8(forced_out)}"`; the baseline
run for a scenario is seed 0 with no forced outages.

### 2.3 Scenario IDs (shared contract)

| `scenario_id` | `kind` | `ts_start` | `ts_end` | Demo use |
|---|---|---|---|---|
| `uri_2021` | historical | 2021-02-13T00:00Z | 2021-02-20T23:00Z | The hero replay. Held out from training. |
| `beryl_2024` | historical | 2024-07-07T00:00Z | 2024-07-12T23:00Z | Second holdout, hurricane/wind driver. |
| `helene_2024` | historical | 2024-09-25T00:00Z | 2024-09-30T23:00Z | Third holdout (mostly outside Texas — accuracy shown as a table, not the map). |
| `forecast_72h` | forecast | run time | +72h | "Next 72 hours" live-look layer. Weather from NWS/HRRR forecast if reachable, else a synthetic winter-front designed to look like a forecast. Labelled honestly. |

Exact `beryl_2024` / `helene_2024` windows are set by spec 01; the above are the defaults if 01 is silent.

**Legacy scope note (D-5).** These four scenario IDs and the ERCOT/ACTIVSg2000 run order in §4.2
below are the **legacy Texas path**, which [`README.md`](README.md) already declares superseded by
[`10-minnesota-demo.md`](10-minnesota-demo.md) as *planning* authority. They stay here, unchanged,
because they are what the code runs: `BUILT_LAYERS = frozenset({"buses"})`
(`copilot/routes/layers.py:44`) serves the Texas `buses` table,
`SYNTHETIC_TOPOLOGY_LABEL = "synthetic (ACTIVSg2000)"` (`layers.py:59`, `scenarios.py:32`) is the
only topology label any route emits, and **no `mn_*` read route exists**. Minnesota supersedes
these as *plan*; it does not yet supersede them as *behaviour*. Do not present either as the
other.

### 2.4 Copilot tools (shared contract — exact signatures)

All return JSON-serializable `dict`. Implemented in `copilot/tools/*.py`; the copilot never imports
pandapower or LightGBM directly, it calls into `twin/`, `models/outage/`, `siting/`.

```python
def predict_outage(county_fips: str, scenario_id: str, horizon_h: int = 72) -> dict
def run_cascade(element_ids: list[str], scenario_id: str, hour: int) -> dict
def score_site(site_id: str, unit_mw: int, scenario_id: str) -> dict
def top_lines(region: str, tech: Literal["dlr", "reconductor", "any"], n: int = 10) -> dict
def sql(query: str | None = None, template_id: str | None = None) -> dict
                                          # legacy query or registered template; read-only DuckDB; row cap 200
def cite(query: str, k: int = 5) -> dict  # retrieval over regulatory PDFs
# added by amendment A8 (nine tools total):
def compare_interventions(scenario_id: str, intervention_ids: list[str]) -> dict   # ids "site:<site_id>" | "line:<line_id>"
def top_critical_elements(region: str, n: int = 10) -> dict                          # ranks by cascade reach from cascade_runs
def causal_query(...) -> dict                                                        # spec 07 owns the signature
# helper, not a model-facing tool: resolve_site(lat, lon) -> site_id (A8)
```

SQL deployments may register fixed, deployment-owned templates. Every `sql`
call supplies exactly one of `query` or `template_id`; the input boundary
rejects an empty call and a call carrying both. In registry
mode, the caller supplies one advertised `template_id` matching
`^[a-z][a-z0-9_]{0,63}$`; raw `query` text is rejected before database access.
Each template declares its complete approved-view relation set, which is
validated against the parsed statement at registry construction. A deployment
without a registry retains legacy `query` input and answers a `template_id`
with an explicit unavailable result naming the missing registry. Only a
deployment-owned template may contain positional `?` markers. Its caller may
send at most 25 finite JSON scalar values; the executor checks exact arity and
binds them before execution. Legacy free-form `query` text cannot contain
placeholders or values.

`cite` corpus (in `data/raw/regs/`, chunked by spec 05): 10 CFR Part 100; DOE coal-to-nuclear reports
(Sept 2022, Sept 2024); EO 14299, 14300, 14301, 14302 (May 2025); NRC July 2026 proposed rule
"Modernizing Reactor Licensing, Safety Oversight, and Siting Practices" (proposed 1 July 2026; 91 FR 44560,
16 July 2026, FR Doc. 2026-14341; revises 10 CFR Part 100 with a Tier 1 / Tier 2 siting framework and a
societal risk-benefit assessment for higher-density sites) [VERIFIED 2026-09-05]; FERC DLR ANOPR RM24-6.

---

## 3. Outputs

- This file, `README.md`, and specs 01–09.
- The **demo** (section 5) and the **definition of demo-ready** (section 10).

---

## 4. Design — six layers + web + copilot

```
 ┌────────────────────────────────────────────────────────────────────────────────────────────┐
 │                                   web/  (Vite + React + deck.gl + MapLibre)                │
 │   [Map: lines/buses/counties]  [Outage choropleth]  [Cascade playback]  [Siting cards]     │
 │   [Line-upgrade screen (08)]   [Critical-load panel]  [Ask box]  [Counterfactual toggle]   │
 └───────────────▲──────────────────────────────────────────────────────────▲─────────────────┘
                 │ GET /layers/{name}  (GeoJSON / Arrow)                     │ POST /ask (SSE)
 ┌───────────────┴──────────────────────────────────────────────────────────┴─────────────────┐
 │                          copilot/  (FastAPI + Anthropic SDK, claude-sonnet-5)              │
 │   Read APIs for the map        │   Tool loop: predict_outage · run_cascade · score_site    │
 │   (thin SELECTs on DuckDB)     │              top_lines · sql · cite · causal_query (07)    │
 │                                │              compare_interventions · top_critical_elements │
 │                                │   Model narrates + plans. Tools compute. Never the reverse │
 └────┬───────────┬───────────────┬────────────────┬───────────────┬──────────────────────────┘
      │           │               │                │               │
 ┌────▼────┐ ┌────▼─────┐ ┌───────▼───────┐ ┌──────▼──────┐ ┌──────▼──────┐   ┌──────────────┐
 │ L3      │ │ L4       │ │ L5            │ │ Idea-3      │ │ L6-causal   │   │ cite() RAG   │
 │ models/ │ │ twin/    │ │ siting/       │ │ screen (08) │ │ causal/ (07)│   │ regs PDFs    │
 │ outage/ │ │ cascade  │ │ exclusions +  │ │ IEEE-738 +  │ │ pgmpy DAG + │   │ 10 CFR 100,  │
 │ LightGBM│ │ pandapowr│ │ grid-value Δ  │ │ reconductor │ │ DoWhy effect│   │ DOE C2N, EOs │
 │  (02)   │ │  (03)    │ │  (04)         │ │             │ │             │   │ RM24-6       │
 └────┬────┘ └────┬─────┘ └───────┬───────┘ └──────┬──────┘ └──────┬──────┘   └──────────────┘
      │           │               │                │               │
 ┌────▼───────────▼───────────────▼────────────────▼───────────────▼──────────────────────────┐
 │                       data/duck/grid.duckdb   +   data/parquet/                             │
 │  L1 twin tables: buses · lines · gens · loads · counties · critical_loads · site_candidates │
 │  L2 load+weather: ba_load_hourly · weather_hourly · storm_events · hazard_static            │
 │  truth: eaglei_outages        scenarios                                                     │
 │  derived: outage_predictions · cascade_runs · site_scores · line_upgrade_scores             │
 └───────────────────────────────────────▲─────────────────────────────────────────────────────┘
                                         │
 ┌───────────────────────────────────────┴─────────────────────────────────────────────────────┐
 │  pipelines/ (01)  ←  scripts/data/download.sh  ←  data/raw/<source>/                        │
 │  ACTIVSg2000 · HIFLD(archived) · EIA-860 via PUDL · EIA-930 · EAGLE-I · NOAA StormEvents    │
 │  HRRR/ERA5 · FEMA NRI · USFS wildfire · USGS NSHM · Census TIGER · DoD boundaries · HIFLD   │
 │  hospitals · EIA-860 retirements (coal sites) · DOE federal sites · regulatory PDFs         │
 └─────────────────────────────────────────────────────────────────────────────────────────────┘

 Layer map:  L1 grid model (01+03 build)   L2 load & weather (01)   L3 outage model (02)
             L4 cascade physics (03)       L5 siting engine (04)    L6 copilot (05) + causal (07)
             web (06)                      line-upgrade screen (08)
```

### 4.1 Unit dependency graph (which spec depends on which table)

```
01-data-ingest ──writes──> buses, lines, gens, loads, counties, critical_loads, eaglei_outages,
                           weather_hourly, storm_events, hazard_static, ba_load_hourly,
                           site_candidates, scenarios
      │
      ├──> 02-outage-model      reads eaglei_outages, weather_hourly, storm_events, hazard_static, counties, scenarios
      │         └──writes──> outage_predictions
      │
      ├──> 03-cascade-sim       reads buses, lines, gens, loads, ba_load_hourly, critical_loads, counties,
      │         │               weather_hourly (line failure probs), outage_predictions (optional seed)
      │         └──writes──> cascade_runs
      │
      ├──> 04-siting-engine     reads site_candidates, hazard_static, counties, buses, gens; CALLS twin (03) for Δ
      │         └──writes──> site_scores; persists the demo counterfactual cascade run(s) to cascade_runs (id agreed with 03, see §5 beat 4)
      │
      ├──> 08-line-upgrade      reads lines, weather_hourly, (cascade_runs for congestion proxy)
      │         └──writes──> line_upgrade_scores
      │
      ├──> 07-causal-layer      reads eaglei_outages, weather_hourly, hazard_static, storm_events
      │         └──writes──> causal/artifacts/*.json  (no shared table; exposed via copilot sql()/API)
      │
      └──> 05-copilot           reads EVERYTHING; wraps 02/03/04/07/08 as tools (nine, A8); serves web
                └──> 06-frontend  reads copilot HTTP APIs only. Never opens DuckDB.
```

Critical path: **01 → 03 → 04 → 06 (siting screen)**. Everything else can slip; those four cannot.

Unblocking rule: every unit that reads a table from 01 must be able to run on a **fixture** DuckDB
(`pipelines/fixtures/make_fixture_db.py`, spec 01 owns it) with ~20 buses, 30 lines, 5 counties and
one synthetic scenario, so 02–08 can start before real ingest finishes.

### 4.2 Interfaces (exact function/route signatures the overview pins)

Copilot HTTP surface — **spec 05 owns the route names**; restated here so 06 builds against the same
list. The DuckDB read surface carries no `/api/` prefix and its map data comes through one
`GET /layers/{name}` endpoint; the published physical-inventory release is a separate versioned
artifact surface under `/api/v1/grid/layers/{layer}` (2WKG-89) and is the only prefixed route.

```
GET  /health                                   → {ok, duckdb_path, tables, corpus_chunks, dense, model}
GET  /scenarios                                → [{scenario_id, name, kind, ts_start, ts_end, hours, has_cascade, has_predictions}]
GET  /scenarios/{scenario_id}                  → the same row shape for one scenario, unwrapped; unknown id is a `not_found` 404 failure envelope (`copilot/routes/scenarios.py:248`)
GET  /layers/{name}?scenario_id=&hour=&run_id=&unit_mw=&tech=&res=
       name ∈ {buses, lines, gens, counties, critical_loads, outage_risk, cascade, sites,
               line_upgrades, storm, national_hex, eaglei}          (GeoJSON / Arrow IPC / JSON — see 05)
GET  /cascade?scenario_id=&run_id=                    → one qualified persisted cascade_runs run, unwrapped {run_id, scenario_id, artifact_id, model_mode, geography_id, hours:[{hour, lost_load_mw (MW), …}], provenance:[…], limitations:[…], source_kind, topology, attributes} (05 §Routes, 2WKG-170)
POST /site-score   {site_id, unit_mw, scenario_id}    → one persisted site_scores row, unwrapped {site_id, …, artifact_id, model_mode, limitations, source_kind, topology, provenance} — model metadata joined from mn_artifact_manifests, not from site_scores (05 §Routes, 2WKG-172)
GET  /predictions?scenario_id=&county_fips=&model_kind=&limit=1000 → bare array of qualified persisted prediction rows, filtered in SQL before LIMIT (05 §Routes, 2WKG-104)
GET  /lines/top?region=&tech=any&limit=50&offset=0    → one bounded deterministic page of the persisted line-upgrade ranking as the top_lines dict; limit is capped at TOP_LINES_MAX_LIMIT (50) and the frozen tool input top_lines(region, tech, n) stays unpaginated (05 §Routes, 2WKG-172)
POST /compare      {scenario_id, intervention_ids}    → compare_interventions(...) dict + evidence/comparison_status; persisted deltas only, never derived (05 §Routes, A8, 2WKG-173)
GET  /elements/critical?region=&n=10&offset=0         → top_critical_elements(...) dict incl. scenario_ids, + offset/evidence; partial counts the relation, not the page (05 §Routes, A8, 2WKG-173)
GET  /api/v1/grid/layers/{layer}?state=&version=&bbox=&limit=50&cursor= → one deterministic page of a published physical-inventory release, unwrapped; layer ∈ the release's asset classes or "all"; native geometry plus a WGS84 display copy with transform provenance; total orders on asset_id, cursor bound to (state, version, layer, bbox, release_sha256). The only /api/-prefixed route: it serves a versioned published artifact, not the DuckDB read surface above (05 §Routes, 2WKG-89)
POST /ask          {attempt_id, question, context?, history?} → v1 text/event-stream (see docs/research/sse-event-schema.md)
```

This list is the **twelve routes `copilot/app.py` actually mounts**, regenerated from
`app.openapi()['paths']` and cross-checked against the `@router` decorators and
`copilot/test_read_route_contracts.py:95-250`. Two previously listed routes, `POST /cascade` and
`POST /predict`, **do not exist in any form on `master`** and are removed rather than marked
planned: `GET /cascade` (`copilot/routes/predictions.py:445`) and `GET /predictions`
(`copilot/routes/predictions.py:248`) are the persisted-artifact reads that replaced them, and
nothing computes a cascade or a prediction inside a request. `GET /scenarios/{scenario_id}` was
implemented and never documented here.

The additive Minnesota `GET` routes are persisted-artifact reads with unwrapped
payloads (only failures carry the envelope). `GET /cascade` selects a persisted cascade
only when its model result is validated, its manifest is available with
`model_mode: "topology"`, and its nonempty provenance and limitations are present; it
labels the topology from the persisted provenance (synthetic ACTIVSg2000 or fixture) and
never starts a cascade calculation. Nothing computes a cascade inside a request: the compute route
that used to be described here was never implemented (D-3). `GET /predictions` returns only
persisted predictions whose evaluation is
qualified; absent or unqualified artifacts are unavailable rather than an empty success.

Python entry points (owning spec's CLI wins; this list is the run order). This is the **legacy
Texas run order** in the sense of the D-5 note in §2.3: it is what the repository can actually
execute today, and `10-minnesota-demo.md` supersedes it as plan, not as behaviour.

```
uv run python -m pipelines.run_all --texas                                         # 01 [name pinned here; 01 may rename]
uv run python -m models.outage.train --holdout uri_2021 beryl_2024 helene_2024     # 02 [02 may rename]
uv run python -m models.outage.predict --scenario uri_2021                         # 02 [02 may rename]
uv run python -m twin.build                                                        # 03 (build + cache net)
uv run python -m twin.cascade --scenario uri_2021 --seed 0                         # 03 (168-h baseline run)
uv run python -m siting.candidates                                                 # 04 (site_candidates)
uv run python -m siting.rank --unit 1000 --scenario all                            # 04 (site_scores)
uv run python -m causal.fit                                                        # 07 [07 may rename]
<08's scorer>  --region ERCOT                                                       # 08 owns the module path
uv run uvicorn copilot.app:app --port 8000                                          # 05
pnpm --dir web dev                                                                  # 06
```

### 4.3 Truth vocabularies — two axes, not one (D-7)

The repository carries **two** frozen label vocabularies at two different layers, and they are
complementary, not competing. `docs/design/minnesota-gate-0-approval.md:51-66` froze both; this
section names them so a reader of either one alone cannot mistake it for the other.

| Axis | Owner on `master` | Values | Answers |
|---|---|---|---|
| **UI status** (`AssetStatus`) | `web/src/labels.ts:13-22` (`ASSET_STATUS_TOKENS`) | `source_supported` · `source_screened` · `hypothetical` · `synthetic` · `unavailable` · `request_failed` | what the browser renders *about a result*; every token is bound to a real server field by the narrative-IA status table |
| **Artifact truth label** | `data/sources/minnesota-accepted-artifact-inventory.json` `truth_labels`, consumed by `pipelines/minnesota_asset_binding.py:275-292` | `source_backed` · `synthetic` · `unavailable` | what a piece of *evidence is*, at the inventory/binding layer |

Consequences, all of them checkable:

- `web/src/labels.ts:5-6` says "there is no `source_backed` token anywhere in the vocabulary". That
  is true **of the UI-status axis only**. `web/src/ask/results/types.ts:73`
  (`geometry: "source_backed" | "synthetic" | "unavailable"`) is the artifact axis, correctly
  spelled, and must not be "fixed" to `source_supported`.
- The 3D contract's `MAT_STATUS` slot binds exactly the **UI** set
  (`data/3d/asset-archetypes-v1.json` `statusMaterials.allowedLabels`).
- `illustrative` is **not** in either frozen set (`minnesota-gate-0-approval.md:68-79`), yet it is
  still shipped in the inventory JSON's `truth_labels` and used as the negative case by six
  pipeline tests. Removing it is a data-and-test change, tracked as a follow-up, not a doc edit.
- The two axes **contradict at the binding seam**:
  `pipelines/tests/test_minnesota_asset_binding.py:53` binds `truth_label: "source_backed"` while
  `:208-216` asserts `source_supported` is *rejected*. That is a real behavioural question about
  which axis the binder speaks, and it is filed as its own bug, not resolved here.

### 4.4 `request_failed` is a display token with an open cause set (D-8)

`request_failed` (UI axis, above) is the token the browser renders; it is **not** a cause. Three
vocabularies sit under it, and no document previously said so:

| Layer | Vocabulary | Where |
|---|---|---|
| HTTP failure code (closed, four values) | `unavailable` · `invalid_input` · `not_found` · `internal_error` | `copilot/api/envelope.py:24-29`; see [`../api/envelopes.md`](../api/envelopes.md) |
| Server per-route cause | `details.reason` — seven for `/layers` (`copilot/routes/layers.py:98-112`), ~20 more named in spec 05; **all of them are `unavailable`, none is `request_failed`** | route modules |
| Browser cause (open, eleven values) | `FailureKind` = `loading` · `empty` · `partial` · `unavailable` · `malformed` · `version_mismatch` · `network_failure` · `cancelled` · `timeout` · `oversized` · `failed` | `web/src/failure-states/types.ts:24-35`; bound to the frozen tokens at `:42-54` — seven collapse to `request_failed`, `unavailable` maps to itself, and `loading`/`empty`/`partial` map to `null` because they are not request outcomes |

The SSE terminal-error set is the one place the docs and the code already agree, in the same order:
`docs/research/sse-event-schema.md:126-127` = `web/src/chat/ChatDock.tsx:24-33` =
`web/src/failure-states/adapters.ts:38-46` = `web/src/ask/run-state/types.ts:72-81`.

**Open question — see [`spec-code-reconciliation.md`](spec-code-reconciliation.md) OQ-1.** Whether
"a stream that ended without a terminal event is `request_failed`, not `unavailable`"
(`docs/design/texas-demo-narrative-ia.md:98`) is normative is undecided; nothing implements it
today.

---

## 5. Demo script → units (5 minutes)

| # | Beat (spoken) | On screen | Serving unit(s) | Data path |
|---|---|---|---|---|
| 1 | "This is the grid as public data lets us see it." National → zoom to Texas. | National static slide → interactive Texas map: lines coloured by kV, buses, county outlines. | 06, 01 | `lines`, `buses`, `counties` |
| 2 | "Load Winter Storm Uri." Outage model lights counties; compare to actual. | Choropleth `p_out` at 2021-02-15T06Z, toggle to `eaglei_outages` actual; a small accuracy chip (AUC / hit-rate). | 02, 06 | `outage_predictions`, `eaglei_outages` |
| 3 | "Trigger the cascade." Lines trip in sequence; a defense installation turns red at hour N. | Cascade playback scrubber; critical-load panel; "Fort Hood (Fort Cavazos) loses supply at hour 3" [UNVERIFIED which installation actually flips — pick the first DoD load lost in the real run]. | 03, 06 | `cascade_runs`, `critical_loads` |
| 4 | "Open siting." 30 Texas coal sites ranked; pick #1; safety card; counterfactual replay: installation stays green, X million customer-hours avoided. | Site list sorted by `grid_value_score`; safety flags card; toggle baseline vs counterfactual run. | 04, 03, 06 | `site_scores`, `cascade_runs` (baseline `uri_2021-s0-<sha8>` vs the counterfactual run for the chosen site). **Resolved (amendment A1):** spec 04's scoring loop keeps `write=False`, but after ranking it re-runs the #1 site's counterfactual (1000 MW, `uri_2021`, all 168 h) with `write=True`, `run_id = "uri_2021-s0-cf-<site_id>-1000"` and `cascade_runs.counterfactual_site_id = <site_id>`; the UI toggle selects that row. |
| 4b | "The twin also tells you which existing wires to upgrade." | Line-upgrade screen: top-10 ERCOT lines by `mw_per_musd`; FERC screen toggle; SPARK flag. | 08, 06 | `line_upgrade_scores` |
| 5 | Ask: "Why this site over the one near Houston?" | Copilot streams; tool calls visible (`score_site` ×2, `cite`); answer cites 10 CFR 100 §100.21 population-density criterion. | 05, 04 | tools |
| 5b | (if time) "How much of Harris County's outage risk is weather vs. under-investment?" | Copilot calls `sql` on `causal/artifacts` + narrates the decomposition. | 07, 05 | causal artifacts |
| 6 | Zoom out: "This scales. CEII slot." | National scale slide (static). | slide | — |

---

## 6. Acceptance criteria (overview-level)

1. `docs/specs/README.md` lists 00–11 and every file exists.
2. Every spec 01–11 uses only table names, column names, scenario IDs, and tool signatures from section 2 of this file (grep check: no spec introduces a new table without adding it to the table in §2.2 via a PR to this file).
3. `uv run python -m pipelines.fixtures.make_fixture_db` produces a `grid.duckdb` on which `twin.cascade`, `models.outage.predict`, `siting.rank`, and `copilot.app` all start without error (Day 1 noon gate).
4. The critical path 01→03→04→06 is green by Day 2 noon (see §7).
5. The six demo beats in §5 each have a named owner and a rehearsed click path by Day 2 18:00.
6. The "honest answers" (§8) are in the copilot system prompt verbatim so the model never overclaims.
7. Definition of demo-ready (§10) is fully checked before the final rehearsal.

---

## 7. Weekend plan (hour-by-hour, owners TBD)

Team size assumed 4–6. Owners are `TBD` — fill in at kickoff. Times are local.

### Day 1

| Time | Unit | Task | Owner | Gate |
|---|---|---|---|---|
| 08:00–08:30 | all | Kickoff. Read 00 + your spec. Assign owners. `uv sync`, `pnpm install`. | TBD | Everyone can run `uv run python -c "import duckdb, pandapower, lightgbm"`. |
| 08:30–09:30 | 01 | `scripts/data/download.sh` written; ACTIVSg2000 + Census TIGER counties + EIA-860 (PUDL parquet) downloading. Fixture DB script first. | TBD | Fixture DB exists (`make_fixture_db.py`). |
| 08:30–09:30 | 03 | pandapower model loader from fixture DB; DC power flow runs. | TBD | `twin.build` on fixture. |
| 08:30–09:30 | 06 | Vite + deck.gl + MapLibre skeleton with OpenFreeMap tiles; Texas viewport; empty layers wired to `/layers/{name}` stubs. | TBD | Map renders. |
| 08:30–09:30 | 05 | FastAPI skeleton; `/layers/{buses,lines,counties}` thin SELECTs against fixture DB; Anthropic SDK tool-loop with `sql` + `cite` stubs. | TBD | `curl /layers/buses` returns GeoJSON. |
| 09:30–12:00 | 01 | Real ingest: `buses`, `lines`, `gens`, `loads` from ACTIVSg2000 (bus lon/lat → county_fips via spatial join); `counties`; `scenarios`. | TBD | Row counts: ~2000 buses, ~3200 lines, 254 counties. |
| 09:30–12:00 | 02 | EAGLE-I Texas 2014–2025 → `eaglei_outages` (parquet). Feature builder on fixture weather. | TBD | Parquet written; feature frame shape printed. |
| 09:30–12:00 | 08 | IEEE 738 ampacity function + reconductor uplift table + REFA cost constants; unit tests on 3 hand-checked lines. | TBD | Tests green. |
| 09:30–12:00 | 04 | Exclusion layer loaders (NRI, USGS PGA, population density from Census, wildfire) → `hazard_static`; `site_candidates` from EIA-860 coal retirements + nuclear + DoD. | TBD | ≥30 Texas coal sites in `site_candidates`. |
| **12:00** | **all** | **Gate A: fixture-DB integration.** Every unit runs end-to-end on the fixture DB. | TBD | §6 criterion 3. |
| 13:00–15:00 | 01 | `weather_hourly` (HRRR or ERA5 county-mean for Uri/Beryl windows), `storm_events`, `ba_load_hourly` (EIA-930 ERCO), `critical_loads`. | TBD | `weather_hourly` covers uri_2021 for all 254 counties. |
| 13:00–17:00 | 02 | Train LightGBM; hold out `uri_2021`, `beryl_2024`, `helene_2024`; write `outage_predictions` for all four scenarios. | TBD | AUC on Uri holdout printed; ≥0.75 target [UNVERIFIED achievable]. |
| 13:00–17:00 | 03 | Cascade loop on real ACTIVSg2000: weather-driven line failure probs → trip → DC PF → overload trip → repeat; county + critical-load translation; write `cascade_runs` for `base_uri_2021`. | TBD | A base run with nonzero `lost_load_mw` and ≥1 DoD load lost. |
| 13:00–17:00 | 06 | Outage choropleth + actual toggle + time scrubber; cascade playback layer reading `cascade_runs`. | TBD | Beats 2 and 3 click through on fixture data. |
| 13:00–17:00 | 05 | Tools wired: `predict_outage`, `run_cascade` calling 02/03; `cite` corpus chunked and embedded (PDFs downloaded). | TBD | Ask "what tools do you have" → lists all nine (A8). |
| 15:00–17:00 | 04 | Safety scorer (`safety_score`, `safety_flags_json`) on all Texas candidates. | TBD | 30 rows in `site_scores` with safety only. |
| 15:00–17:00 | 07 | pgmpy DAG fit on EAGLE-I + weather + hazard for Texas counties; write `causal/artifacts/decomposition.json`. | TBD | One county decomposition prints. |
| 17:00–19:00 | 03+04 | Grid-value delta: inject `unit_mw` gen at `site.bus_id`, re-run cascade on stress hours, compute `lol_reduction_mwh`, `congestion_relief_pct`, `blackstart_reach_mw`. | TBD | One `GridValueResult` with `lol_reduction_mwh > 0`; one persisted counterfactual run in `cascade_runs`. |
| 17:00–19:00 | 08 | `line_upgrade_scores` for all ERCOT lines ≥138 kV using twin loading as congestion proxy. | TBD | Top-10 table prints. |
| **19:00** | **all** | **Gate B: real-data integration.** Swap fixture DB for real DB; all APIs serve. | TBD | Beats 1–3 work on real data. |
| 19:00–22:00 | all | Overflow. 04 finishes all-site grid-value; 06 siting cards; 05 `score_site`, `top_lines` wired. | TBD | — |

### Day 2

| Time | Unit | Task | Owner | Gate |
|---|---|---|---|---|
| 08:00–10:00 | 04 | `siting.rank` for `uri_2021` at 300 MW and 1000 MW over all candidates (stress-hour cascade re-runs; ~30 sites × 2 sizes × 1 scenario; full-168-h persisted run only for the top site). | TBD | `site_scores` complete; ranking is stable. |
| 08:00–10:00 | 06 | Siting screen: ranked list, safety card, counterfactual toggle, critical-load panel. | TBD | Beat 4 clicks through. |
| 08:00–10:00 | 05 | System prompt with honest answers; `score_site` comparison prompt tuned; SSE streaming; tool-call display. | TBD | Beat 5 answer cites 10 CFR 100. |
| 08:00–10:00 | 08 + 06 | Line-upgrade screen in web; FERC screen toggle; SPARK flag. | TBD | Beat 4b clicks. |
| 08:00–10:00 | 02 | Accuracy chip: AUC / precision@k per held-out storm; `forecast_72h` predictions. | TBD | Chip on screen. |
| 10:00–12:00 | 07 | Copilot exposure of decomposition; counterfactual replay narrative. | TBD | Beat 5b. |
| **12:00** | **all** | **Gate C: full demo click-through on real data, start to finish, by someone who didn't build it.** | TBD | §10 checklist ≥ 80%. |
| 13:00–15:00 | all | Fix list from Gate C. Polish: colours, legends, labels. National scale slide rendered. | TBD | — |
| 15:00–16:00 | 03/04 | Customer-hours-avoided number for the closing slide computed and cross-checked by two people. | TBD | Number is reproducible from `cascade_runs`. |
| 16:00–17:00 | all | Deck: pitch + 6 beats + honest answers + scale slide. Backup Speed-to-Power deck (spec 09 §demo; wire-half slides reuse the 08 screen). | TBD | — |
| 17:00–18:00 | all | Rehearsal 1, timed. | TBD | ≤ 5:30. |
| 18:00–19:00 | all | Fix. Freeze code. Tag `demo-freeze`. | TBD | — |
| 19:00–20:00 | all | Rehearsal 2 on frozen tag, from a cold start (`uv run`, `pnpm dev`, browser). | TBD | §10 fully checked. |

Stretch (only after Gate C): DoWhy effect of past hardening on outage duration (07); Grid2Op operator
agent (03); `forecast_72h` from live NWS alerts (01/02); Beryl replay on the map.

---

## 8. Honest answers (verbatim into the copilot system prompt and the deck)

1. **"Your topology is fake."** — Yes. The electrical topology is ACTIVSg2000, a synthetic Texas grid built by Texas A&M to be statistically realistic. Real topology is Critical Energy/Electric Infrastructure Information (CEII). Synthetic grids are the research standard (DOE, Microsoft GridSFM, Texas A&M). The architecture is a slot: replace `buses`/`lines`/`gens` under a data-use agreement and nothing downstream changes.
2. **"Palantir will do this."** — Palantir's Chain Reaction is workflow and ontology. It has no power-flow physics and no siting engine. We are the engine they would want to partner with or buy.
3. **"Nuclear takes a decade."** — The siting decision is being made now: Army Janus microreactor program (26 Aug 2026: five vendors, up to $2.2 B, first five installations incl. Fort Hood, TX → General Atomics), DOE federal AI/energy sites (INL, Oak Ridge, Paducah, Savannah River — July 2025), ten large reactors under construction by 2030 under EO 14302 (23 May 2025). The tool is for the decision, not the construction.
4. **"Is the outage model any good?"** — It is a county-level LightGBM trained on EAGLE-I 2014–2025 with three storms held out. We show the held-out score on screen. It predicts *where and how many*, not *which pole*.
5. **"Is the cascade real?"** — It is DC power flow with iterative overload tripping on a synthetic grid, with weather-driven initial failure probabilities. It is the standard academic cascade model, not an RTO-grade EMS. Hour-by-hour element order is illustrative; the aggregate lost-load and critical-load exposure is the claim.
6. **"Your siting safety score is not an NRC review."** — Correct. It re-implements the published OR-SAGE/STAND screening criteria on open layers (population density within 20 miles, seismic PGA, floodplain, cooling water, protected land, wildfire, state moratorium flag). It is a screener, like DOE's 2022 tool, but ours has a grid model under it.
7. **"Which states can Flux cover?"** — Public context can be ingested for a selected U.S. state when its declared local source artifacts are supplied. The repository's Texas topology adapter has an ACTIVSg2000 / ERCOT path because ERCOT has public hourly load and Uri is well documented, but it still requires its source artifacts and build. Another state needs its own validated topology and model contract before Flux can present topology, flow, cascade, or siting results. The checked-in five-bus preview is not a state model.
8. **"Line-upgrade numbers?"** — Congestion dollars are a twin-loading proxy, not RTO shadow prices (we did not map ERCOT constraint names to lines this weekend). DLR uplift is IEEE 738 on county-mean wind. Reconductor uplift and costs are LBNL REFA / GridLab assumptions. All three are labelled as estimates.
9. **"The copilot hallucinates."** — The model never computes. Every number in an answer came from a tool call the judge can see on screen, and every regulatory claim comes from `cite()` with the page reference.

---

## 9. Judge hooks (which beat lands which judge)

| Judge / firm | Hook | Beat |
|---|---|---|
| Second Front (Sweatt, Bosquez, Utt) | CEII-ready, air-gappable: one DuckDB file, no cloud dependency, runs in a utility/RTO/DoD enclave; path to accreditation. | 1, 6 |
| a16z / Dept. of War (Cronin, Booher) | Critical-infrastructure defense without being a weapons program; Janus, Project Pele, EO 14299 make "which base first" a live procurement question. | 3, 4 |
| FAI (Levine, Dauber) | NRC July 2026 siting rule invites societal risk-benefit quantification; Brookhaven GridFM (1 Sept 2026) shows government wants a national model — we are the decision layer. | 4, 5 |
| Craft Ventures (Murray) | Buyers: utilities, RTOs, developers, DOE, hyperscalers. Enverus/Pearl Street prove siting market; GridCARE $64M proves appetite. | 4, 4b |
| Forterra / Dirac / KAIROS | Real systems product with physics under it, not a chatbot. Tool calls are visible. | 3, 5 |
| White House anti-fraud (McCarthy), OPM (Hennecken) | Backup pitch (Speed-to-Power, Idea 2) — see spec 09. | backup |

---

## 10. Definition of demo-ready (checklist)

- [ ] `git tag demo-freeze` exists; the demo runs from a fresh clone + shared `grid.duckdb` file in < 5 minutes of setup.
- [ ] `uv run uvicorn copilot.app:app` and `pnpm --dir web dev` both start with no warnings that matter.
- [ ] Map loads in < 3 s on the demo laptop, offline tiles cached or OpenFreeMap reachable (test on venue wifi AND a phone hotspot).
- [ ] Beat 2: Uri choropleth at 2021-02-15T06Z shows predicted vs actual; accuracy chip shows a real held-out number.
- [ ] Beat 3: cascade playback runs ≥ 6 hours of trips; ≥ 1 DoD critical load flips to lost; the panel names it.
- [ ] Beat 4: ≥ 30 Texas sites ranked; #1 has a safety card with flags; counterfactual toggle shows the DoD load staying `ok` and `lol_reduction_mwh` > 0.
- [ ] Beat 4b: line-upgrade top-10 for ERCOT renders; FERC screen toggle changes the list.
- [ ] Beat 5: the copilot question "Why this site over the one near Houston?" returns within 20 s, shows ≥ 2 tool calls, cites 10 CFR 100 with a section number.
- [ ] Every number on the closing slide (customer-hours avoided, MWh reduction) is reproducible with one `sql()` query pasted in the copilot.
- [ ] Honest answers §8 are in the copilot system prompt and on a backup slide.
- [ ] National scale slide exists as a PNG in the deck.
- [ ] Backup Speed-to-Power deck exists (≥ 6 slides) even if no load-half (`dc_*`) code shipped; its wire-half slides are screenshots of the spec 08 screen.
- [ ] Someone who did not build it has clicked through all six beats without help.
- [ ] Rehearsed twice, timed ≤ 5:30, once from cold start.

---

## 11. Risks / unknowns

| Risk | Likelihood | Mitigation |
|---|---|---|
| EAGLE-I download requires Globus/ORNL account approval and is slow | High | Request access Friday night; fall back to the published Texas Uri subset [UNVERIFIED that a subset exists]; if nothing by Day 1 noon, 02 trains on `storm_events`-derived pseudo-outages and we say so. |
| ACTIVSg2000 bus coordinates → county join has gaps | Medium | Nearest-county fallback; log count of buses assigned by fallback. |
| Cascade re-runs for siting too slow (30 sites × 2 sizes × 168 h) | Medium | DC PF is ms-scale; cap hours to the 24 h peak window of Uri; parallelise with multiprocessing; precompute Day 1 night. |
| HRRR reanalysis for Feb 2021 is large / hard to subset | High | ERA5 county-mean via a small subset; or NOAA ISD station data interpolated to counties; 01 decides, 02 consumes the same columns. |
| Archived HIFLD lines unreachable | Medium | The demo map uses ACTIVSg2000 line geometry (synthetic lat/lon are provided by the dataset). HIFLD only for the national scale slide; OSM `power=line` as fallback. |
| `claude-sonnet-5` tool loop slow with nine tools + SSE | Low | Cap tool iterations at 6; pre-warm one answer for beat 5 as a cached transcript fallback. |
| NRC July 2026 proposed siting rule PDF not locatable | Low | Located: Federal Register 2026-14341 (16 July 2026), NRC ADAMS ML26176A438. Fallback: cite 10 CFR 100 + Reg Guide 4.7 and mention the proposed rule verbally. |
| Nobody on the team has run pandapower before | Medium | 03 starts on fixture DB at 08:30; the DC PF example in pandapower docs is 10 lines. |

---

## 12. Weekend time-box (hours)

| Unit | Day 1 | Day 2 | Total |
|---|---|---|---|
| 00 overview + 09 backup + README | 1 (already written) | 1 (deck) | 2 |
| 01 data ingest | 9 | 1 | 10 |
| 02 outage model | 7 | 2 | 9 |
| 03 cascade sim | 9 | 2 | 11 |
| 04 siting engine | 7 | 4 | 11 |
| 05 copilot | 7 | 3 | 10 |
| 06 frontend | 9 | 5 | 14 |
| 07 causal layer | 3 | 2 | 5 |
| 08 line-upgrade screen | 5 | 2 | 7 |
| integration, deck, rehearsal | 2 | 7 | 9 |

## Contract amendments (2026-09-05, after the four writers reconciled)

These are decisions, not proposals. Every spec is read as if these were in its contract block.

- **A1 — counterfactual runs.** `cascade_runs` gains a nullable column `counterfactual_site_id TEXT` (NULL for baseline runs). Counterfactual `run_id` convention: `<scenario_id>-s<seed>-cf-<site_id>-<unit_mw>`. Spec 04 persists the #1 ranked site's `uri_2021` counterfactual with `write=True`; all other scoring runs stay `write=False`.
- **A2 — one Python environment.** There is exactly one `pyproject.toml`, at the repo root (uv, Python 3.12). Spec 05's `copilot/pyproject.toml` is withdrawn; `copilot/` is a package inside the root env.
- **A3 — `site_candidates.kind` enum is the contract's:** `coal_retired | coal_retiring | nuclear_existing | doe_federal | dod`. Spec 05's assumed `federal | defense` values map to `doe_federal | dod`. Texas has no INL/ORR/SRS/Paducah, so `doe_federal` holds only Pantex (flagged) in the Texas-first demo.
- **A4 — additive tables accepted:** `line_upgrade_detail(...)` (spec 08, per-line card fields) and `corpus_chunks(...)` (spec 05, retrieval chunks, written at ingest time only). Spec 01's ingest runbook must create both.
- **A5 — additive copilot surface accepted:** routes `GET /health` (and a compute-style predict route, **never implemented** — see D-3 in [`spec-code-reconciliation.md`](spec-code-reconciliation.md); the persisted read `GET /predictions` is what exists); layer names `eaglei`, `storm`, `national_hex`; `score_site` return adds `critical_loads_protected` and `regulatory_path`. The six tool signatures in the contract are unchanged.
- **A6 — `tripped_element_ids_json` entries are objects** `{element_id, stage, cause}`, not bare strings (spec 03); every consumer (05, 06) parses them as objects.
- **A7 — cascade solver default (rewritten after the 03/04 fact-check, `docs/specs/verification/03-04.md`):** pandapower `rundcpp` is the default and the only solver in scope, run hourly with **no stride** (spec 03). Measured: warm `pp.rundcpp` is 9–14 ms per solve, so a 168-hour `uri_2021` replay is ~6–12 s with plain pandapower. Budgets unchanged: 120 s per scenario, 10 s per copilot `run_cascade` call. lightsim2grid is **stretch-only and currently incompatible**: `init_from_pandapower` raises "Unsupported element (Impedance)" on this case (847 branches import as `net.impedance`); `solver="lightsim"` raises `NotImplementedError` until that is fixed.
- **A9 — storage engine is DuckDB (closes the open `[DECISION]`).** `data/duck/grid.duckdb` is the
  contract store. Postgres/PostGIS is not adopted. This records a decision already made in code:
  `pipelines/db.py` ships DuckDB at `SCHEMA_VERSION 1.0.0` with the 19 contract tables, FK
  constraints and per-table provenance columns. The Parquet mirrors under `data/parquet/` remain the
  demo-day hand-off. `docs/plans/data-collection-and-curation-plan.md` §2 asked for this to be an
  amendment before any lane depended on it; the dependency landed first, so it is recorded here.
- **A8 — product name Flux, tool-name mapping, and two new contract tools (from the prior product briefing).**
  - **Name.** The product is **Flux**. Use it in titles, decks, the copilot identity line, and prose wherever the project is named. The repository, package paths, and DuckDB file stay `flux` / as in §2.1.
  - **Tool-name mapping.** The description's copilot tool list uses different names and argument shapes from this contract. The contract names below are the ones implemented; the description names are aliases in prose only, never in code.

    | Prior briefing tool | Contract tool (this file) | Note |
    |---|---|---|
    | `predict_outage(county, horizon)` | `predict_outage(county_fips, scenario_id, horizon_h)` | county is a FIPS string; scenario is explicit |
    | `run_cascade(element_ids, scenario)` | `run_cascade(element_ids, scenario_id, hour)` | hour is explicit |
    | `score_site(latitude, longitude, capacity)` | `score_site(site_id, unit_mw, scenario_id)` | ad-hoc lat/lon is resolved to a `site_candidates` row by the helper `resolve_site(lat: float, lon: float) -> dict` (`{site_id, name, distance_km}`; nearest candidate, error if > 25 km) before `score_site` is called; `capacity` → `unit_mw ∈ {300, 1000}` |
    | `compare_interventions(scenario, intervention_ids)` | `compare_interventions(scenario_id, intervention_ids)` | **new**, below |
    | `top_critical_elements(region, count)` | `top_critical_elements(region, n)` | **new**, below |
    | `top_line_upgrades(region, technology, count)` | `top_lines(region, tech, n)` | rename only |
    | `sql(query)` | `sql(query | template_id)` | Exactly one of legacy query text or a deployment-owned registered template. |
    | — | `cite(query, k)` | contract-only (retrieval) |
    | — | `causal_query(...)` | contract-only; spec 07 owns the signature and implementation; registered here so the tool count is consistent |

  - **New tool 1.**
    ```python
    def compare_interventions(scenario_id: str, intervention_ids: list[str]) -> dict
    ```
    `intervention_ids` are prefixed: `site:<site_id>` (a `site_candidates` row; unit size defaults to 1000 MW, override with `site:<site_id>@300`) or `line:<line_id>` (a `lines` row upgraded to its `line_upgrade_detail.dlr_p50_mw` rating, or `reconductor_uplift_mw` if `best_tech = reconductor`). For each id the tool runs spec 03's `run_scenario` pair — baseline (seed 0, no intervention, the persisted `<scenario_id>-s0-<sha8>` row is reused) versus with-intervention (`write=False`, stress hours only, same seed) — and returns:
    ```
    {scenario_id, baseline_run_id,
     interventions: [{intervention_id, kind: site|line, run_id,
                      lol_reduction_mwh, customer_hours_avoided, critical_loads_protected: [cl_id]}],
     assumptions: [str]}
    ```
    Ordered by `lol_reduction_mwh` desc. `customer_hours_avoided` = Σ over hours of (baseline − intervention) customers dark, computed inside the tool from `counties_dark_json` × `counties.pop` customer share — never by the model. Route: `POST /compare`. Timeout 30 s.
  - **New tool 2.**
    ```python
    def top_critical_elements(region: str, n: int = 10) -> dict
    ```
    Ranks elements by **cascade reach** read from persisted `cascade_runs` (no live solve): for every element that appears as a `cause = weather|forced` entry in any `tripped_element_ids_json` of a run for the region's scenarios, attribute that run's `lost_load_mw` and `critical_loads_lost_json` to it; rank by lost load. `region` ∈ `"ERCOT"`, `"TX"`, or a county FIPS (filters by the element's bus county). Returns:
    ```
    {region, n, scenario_ids: [str],
     elements: [{element_id, kind: line|bus|gen, lost_load_mw, critical_loads_lost: [cl_id], runs: int}]}
    ```
    Route: `GET /elements/critical`. Timeout 5 s. If fewer than `n` elements have any persisted cascade, return what exists with `{"partial": true}` — do not fabricate.
  - **Tool count.** With A8 the contract has **nine** tools: `predict_outage`, `run_cascade`, `score_site`, `top_lines`, `sql`, `cite`, `compare_interventions`, `top_critical_elements`, `causal_query`. A5's "six tool signatures unchanged" still holds — the six are unchanged; three are added. Spec 05 registers all nine; `resolve_site` is an internal helper called by spec 05's `score_site` route/tool wrapper, not a model-facing tool.
- **A10 — SSE transport.** `POST /ask` uses the v1 event names, envelopes,
  ordering, terminal behavior, heartbeats, and POST-resume identity defined in
  `docs/research/sse-event-schema.md`. Spec 05 and the web client consume that
  single transport contract; no route or client invents a second event shape.

- **A11 — line-upgrade artifacts are scenario-scoped (2WKG-179/182; `pipelines/db.py` `SCHEMA_VERSION 2.0.0`).**
  `line_upgrade_scores` and `line_upgrade_detail` are keyed by `(line_id, scenario_id)`, not `line_id`:
  the same branch is ranked separately for a historical replay, a forecast, or a declared aggregate
  period, and rows from different scenarios coexist. Both tables gain the typed calculation-contract
  columns `ranking_version TEXT`, `contract_version TEXT`, `computed_at TIMESTAMP`,
  `simulation_run_id TEXT` (nullable), `grid_input_sha256`, `weather_input_sha256` (nullable), and
  `cost_params_sha256` (sha256 hex, CHECK-constrained), ahead of the shared provenance columns.
  `simulation_run_id` is set only when the congestion input was a Flux twin run; observed and proxy
  inputs persist `NULL` and must not imply a run. `contract_version` here is the pydantic
  `pipelines.line_upgrade_contracts.CONTRACT_VERSION` (`1.0.0`), distinct from
  `schema_meta.contract_version` (the DuckDB `SCHEMA_VERSION`, now `2.0.0`, superseding the `1.0.0`
  recorded in A9). The index `line_upgrade_scores_scenario_rank (scenario_id, mw_per_musd, line_id)`
  is a scenario equality-filter aid for `top_lines`, not an ORDER BY accelerator. There is no
  in-place migration from a `1.0.0` `grid.duckdb`: `ensure_schema` refuses it with a named error
  before running any DDL; delete `data/duck/grid.duckdb` and re-run the ingest. `top_lines` and any
  reader of these tables must filter by `scenario_id`.

- **A12 — additive `physical_*` inventory namespace (spec 11).** The seven
  `physical_*` tables above are registered by this amendment, satisfying §6
  acceptance criterion 2 for [11-physical-inventory-contract.md](11-physical-inventory-contract.md).
  They are additive: no existing table, column, scenario id, or tool signature
  changes, and `pipelines/db.py`'s `SCHEMA_VERSION` is untouched — the namespace
  carries its own `physical_inventory_schema_meta.contract_version`
  (`pipelines.physical_inventory.CONTRACT_VERSION`, `1.0.0`), and
  `ensure_physical_inventory_schema` refuses any other recorded version rather
  than migrating in place. Artifact identity is
  `<geography_id>:physical-inventory:<semver>`, which deliberately differs from
  spec 10's `mn:<artifact_kind>:<sha256-16>`; the divergence and its reason are
  recorded in both specs, and spec 11 owns no `mn_*` table and no Minnesota
  artifact envelope.
