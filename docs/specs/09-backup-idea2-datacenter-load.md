# 09 — Backup pitch: Data-Center Load Verification and Grid Impact Scoring (Idea 2)

Status: **backup**. Not on the weekend critical path. Built only if (a) the judges signal they want
something narrower/nearer-term, (b) the format allows two entries, or (c) the Idea 1 critical path
is green by Day 2 noon and a pair is free. The deck for this pitch (≥ 6 slides) IS built regardless
(00-overview §10). This spec is written so one pair can build a demoable slice in ~10 hours on the
shared stack without touching the Idea 1 tables.

Conforms to 00-overview §2 (repo layout, Python/Node conventions, DuckDB file, Claude tool-loop).
All Idea 2 tables are namespaced `dc_*` so they coexist in `data/duck/grid.duckdb` with the Idea 1
tables. The Idea 1 tool `score_site(site_id, unit_mw, scenario_id)` is NOT reused; Idea 2's site
scorer is `score_dc_site(lat, lon, params)` to avoid the name collision.

---

## 1. Purpose

For every utility / ISO large-load queue, reconcile four numbers — **announced**, **queued**,
**forecast**, **operating** — and expose the gap as a *phantom ratio*. Detect the same project or
developer appearing in multiple queues. Estimate the stranded-cost exposure of building for phantom
load. Score any proposed data-center site 0–100 on grid impact with a plain-English "what would make
this a 90". Give regulators a copilot that answers "which three projects should Virginia review most
skeptically?" with citations to the filings.

Geographic scope if built this weekend: **ERCOT first** (the Large Load Interconnection Status report
is a single public spreadsheet), PJM second (public load-forecast large-load adjustments), national
map only from Cleanview announced projects as a scale layer.

---

## 2. Inputs (tables/files)

### 2.1 Raw sources → `data/raw/<source>/`

| Source | What | Where | Confidence |
|---|---|---|---|
| ERCOT Large Load Interconnection Status report (monthly) | queued MW by project, county, stage, requested energization date | `https://www.ercot.com/gridinfo/load/large_load` [UNVERIFIED exact URL; page exists as of 2025] → `data/raw/ercot_ll/` | High that data exists; medium on URL |
| ERCOT "Batch Zero" list (SB6 / 2026) | projects admitted under the new large-load batch process | ERCOT large-load page [UNVERIFIED] → `data/raw/ercot_ll/` | Medium |
| PJM Load Forecast Report 2026 — large-load adjustments by transmission owner | forecast MW attributed to data centers per TO | `https://www.pjm.com/planning/resource-adequacy-planning/load-forecast-dev-process` [UNVERIFIED exact file] → `data/raw/pjm_lf/` | High data exists |
| SPP HILLGA (High-Impact Large Load) | queued MW | SPP website [UNVERIFIED] → `data/raw/spp_hillga/` | Low; skip unless trivially available |
| Cleanview US data-center map (free tier) | announced projects: developer, site, MW, status | `https://cleanview.co` [UNVERIFIED free-tier export format] → `data/raw/cleanview/` | Medium; may require manual CSV export |
| EEI large-customer project & tariff list (Aug 2026) | announced projects + tariff terms by utility | EEI publication [UNVERIFIED download] → `data/raw/eei/` | Medium |
| FERC Form 714 (via PUDL) | utility peak-demand forecasts | PUDL parquet on S3 `s3://pudl.catalyst.coop/` [UNVERIFIED exact key] → `data/raw/pudl/` | High |
| FERC Form 1 (via PUDL) | transmission + generation plant cost per MW (for cost model) | PUDL parquet → `data/raw/pudl/` | High |
| EIA-860 / 861 / 930 | operating plants, utility sales, hourly BA load | shared with spec 01 (`data/raw/eia/`) | High |
| Duke Nicholas Institute "Rethinking Load Growth" (Feb 2025) | per-BA curtailment-headroom tables (MW headroom at 0.25/0.5/1.0 % curtailment) | PDF appendix tables → `data/raw/duke_headroom/headroom.csv` (hand-transcribed if needed) | High |
| gridstatus (pip) | LMP with congestion component, per ISO | `gridstatus` Python library → `data/raw/gridstatus/` | High |
| LBNL Queued Up 2026 | historical queue→COD conversion rates by stage (generation prior) | LBNL site → `data/raw/lbnl_queued_up/` | High |
| FERC docket RM26-4 + six Section 206 show-cause responses; PJM CIFP decision; ERCOT SB6 rules | regulatory corpus for `cite` | FERC eLibrary PDFs → `data/raw/regs_dc/` | Medium |

### 2.2 Shared tables read from Idea 1 (spec 01)

`counties`, `buses`, `lines`, `ba_load_hourly`, `hazard_static` (not needed but available).

---

## 3. Outputs (tables/files/API)

### 3.1 DuckDB tables (all in `data/duck/grid.duckdb`, prefix `dc_`)

```
dc_projects(
  project_id      TEXT PRIMARY KEY,   -- source-scoped: "ercot:LL-2024-0123", "cleanview:987", "pjm:DOM-2026-07"
  source          TEXT,               -- ercot_ll | ercot_batch0 | pjm_lf | spp_hillga | cleanview | eei | eia860
  developer_raw   TEXT,
  developer_norm  TEXT,               -- normalised (lowercase, legal suffixes stripped, alias table applied)
  site_name       TEXT,
  lon             DOUBLE, lat DOUBLE, -- NULL allowed; county centroid fallback flagged in geo_quality
  county_fips     TEXT,
  state           TEXT,
  utility         TEXT,               -- serving utility / TO name, normalised
  iso             TEXT,               -- ERCOT | PJM | SPP | MISO | CAISO | NYISO | ISONE | none
  mw              DOUBLE,             -- requested / announced / forecast / operating MW as reported
  stage           TEXT,               -- announced | screening | study | agreement | construction | energized | withdrawn
  filed_date      DATE,
  target_date     DATE,               -- requested energization / COD
  colocated_gen_mw DOUBLE,            -- bring-your-own generation, 0 if none stated
  storage_mw      DOUBLE,
  curtailable_share DOUBLE,           -- 0..1 if stated, NULL otherwise
  min_demand_share  DOUBLE,           -- tariff minimum-demand commitment (e.g. 0.85 AEP Ohio), NULL otherwise
  geo_quality     TEXT,               -- exact | county_centroid | utility_centroid
  raw_json        TEXT                -- original row for audit
)

dc_entities(
  entity_id       TEXT PRIMARY KEY,   -- "ent_<hash>"; one row per resolved real-world project
  developer_norm  TEXT,
  county_fips     TEXT,
  mw_est          DOUBLE,             -- median of member MW
  n_sources       INT,
  n_queues        INT,                -- distinct (iso, utility) pairs → "shopping" if > 1
  member_project_ids_json TEXT,
  resolution_score DOUBLE,            -- 0..1 confidence the members are one project
  flag            TEXT                -- none | duplicate | shopping
)

dc_utility_ledger(
  utility         TEXT,
  iso             TEXT,
  announced_mw    DOUBLE,
  queued_mw       DOUBLE,
  forecast_mw     DOUBLE,             -- utility/ISO forecast attributable to data centers
  operating_mw    DOUBLE,
  expected_real_mw DOUBLE,            -- Σ p_operate × mw × load_factor over queued entities
  expected_real_mw_lo DOUBLE,         -- 10th pct
  expected_real_mw_hi DOUBLE,         -- 90th pct
  phantom_ratio   DOUBLE,             -- forecast_mw / expected_real_mw   (NULL if expected_real_mw = 0)
  phantom_mw      DOUBLE,             -- max(0, forecast_mw - expected_real_mw)
  stranded_cost_usd DOUBLE,           -- from dc_cost_params
  delay_months_real_loads DOUBLE,     -- see §4.5
  as_of           DATE
)

dc_conversion_params(
  stage           TEXT,               -- announced | screening | study | agreement | construction
  iso             TEXT,               -- or '*' for default
  p_operate       DOUBLE,             -- base probability of reaching energized
  p_lo DOUBLE, p_hi DOUBLE,
  median_months_to_energize DOUBLE,
  source          TEXT                -- "LBNL Queued Up 2026 (generation prior)" | "ERCOT LL stage history" | "assumption"
)

dc_cost_params(
  utility         TEXT,               -- or '*' default
  capacity_cost_usd_per_mw    DOUBLE, -- generation capacity cost to serve 1 MW firm (FERC Form 1 / IRP)
  transmission_cost_usd_per_mw DOUBLE,
  source          TEXT
)

dc_headroom(
  ba_code         TEXT,
  curtail_pct     DOUBLE,             -- 0.25 | 0.5 | 1.0  (Duke tables)
  headroom_mw     DOUBLE
)

dc_site_scores(
  score_id        TEXT PRIMARY KEY,
  lon DOUBLE, lat DOUBLE, county_fips TEXT, ba_code TEXT, utility TEXT,
  params_json     TEXT,               -- the ScoreParams used
  score           DOUBLE,             -- 0..100
  components_json TEXT,               -- {flexibility, byog, load_factor, headroom, congestion, service_type, tariff} each 0..1 + weight
  fixes_json      TEXT,               -- ordered list of {change, new_score, delta, months_faster}
  created_at      TIMESTAMP
)
```

### 3.2 Files

- `causal/dc_conversion_dag.json` — the DAG and estimated effects (stretch; §4.7).
- `data/raw/regs_dc/` chunk index reused by the shared `cite()` machinery with corpus tag `dc`.

### 3.3 API (added to the same FastAPI app in `copilot/`, prefix `/dc/` — spec 05 uses no `/api/` prefix)

```
GET  /dc/utilities                       → [dc_utility_ledger rows]  (map colouring)
GET  /dc/utility/{utility}               → ledger row + top entities + duplicates
GET  /dc/duplicates?developer=&iso=      → [dc_entities where flag != 'none']
POST /dc/score  {lat, lon, params}       → score_dc_site(...) result
GET  /dc/projects?iso=&stage=&bbox=      → GeoJSON of dc_projects
POST /ask                                    → same SSE endpoint as Idea 1 (spec 05); tools selected by corpus tag
```

---

## 4. Algorithm / Design

### 4.1 Layer 1 — Registry ingest (`pipelines/dc/ingest_*.py`)

One module per source, each producing rows in the `dc_projects` schema. Normalisation:

- `developer_norm`: lowercase → strip punctuation → strip legal suffixes (`llc, inc, corp, lp, ltd, holdings`) → apply alias table `pipelines/dc/aliases.yaml` (e.g. `"amazon data services" → "amazon"`, `"microsoft corp" → "microsoft"`, `"qts", "quality technology services" → "qts"`, `"vantage data centers" → "vantage"`). Hand-curated; ~40 entries is enough for ERCOT + PJM.
- `stage`: per-source mapping table to the 7 canonical stages. ERCOT LL report statuses (e.g. "Planning Studies", "Approved for Energization", "Energized") [UNVERIFIED exact status vocabulary] map via `pipelines/dc/stage_map.yaml`.
- `county_fips`: from county name + state via `counties`; if only a city is given, geocode to county with a static city→county table; set `geo_quality`.

### 4.2 Layer 2 — Entity resolution (`pipelines/dc/resolve.py`)

Blocking + pairwise scoring, no ML:

1. **Block** on `state` (and `iso` when both known).
2. **Pair score** `s = 0.40·name + 0.25·geo + 0.20·mw + 0.15·date`, where
   - `name` = Jaro-Winkler(`developer_norm_a`, `developer_norm_b`) (rapidfuzz), and 1.0 if both normalise to the same alias;
   - `geo` = 1 if same `county_fips`; else `max(0, 1 − haversine_km / 80)` when both have exact coords; else 0.5 if adjacent counties, 0 otherwise;
   - `mw` = `1 − |mw_a − mw_b| / max(mw_a, mw_b)`, clipped to [0, 1]; pairs where either MW is NULL get 0.5;
   - `date` = `max(0, 1 − |filed_date_a − filed_date_b| / 540 days)`; NULL → 0.5.
3. **Link** pairs with `s ≥ 0.72`; connected components → `dc_entities`. `resolution_score` = mean pair score within the component.
4. **Flag**: `duplicate` if `n_sources > 1` within the same `(iso, utility)`; `shopping` if `n_queues > 1` (same developer + MW within 25 % across different utilities/ISOs).
5. Every component with `resolution_score < 0.85` is written to `data/parquet/dc_resolution_review.parquet` for a human to eyeball. Demo table shows only `≥ 0.85`.

Aggregation rule (the "latent variable" point from the pitch, simplified): an entity contributes its
**median** MW once to `queued_mw`, never the sum of its members.

### 4.3 Layer 3 — Reality model (`models/dc/reality.py`)

Per entity, `p_operate` and `load_factor`:

```
p_operate(entity) = clip( base(stage, iso)
                          × m_colo      (1.25 if colocated_gen_mw ≥ 0.5·mw else 1.0)
                          × m_tariff    (1.30 if min_demand_share ≥ 0.75 else 1.0)
                          × m_shopping  (1/n_queues if flag == 'shopping' else 1.0)
                          × m_track     (developer_track_record: 1.15 if developer has ≥1 energized entity, 0.85 if ≥3 withdrawn, else 1.0),
                          0.02, 0.98 )
```

`base(stage, iso)` from `dc_conversion_params`. Weekend defaults (labelled `source='assumption'` unless
replaced by ERCOT stage-history counts on Day 1):

| stage | p_operate | lo | hi | months |
|---|---|---|---|---|
| announced | 0.20 | 0.10 | 0.35 | 48 |
| screening | 0.30 | 0.18 | 0.45 | 36 |
| study | 0.45 | 0.30 | 0.60 | 30 |
| agreement | 0.70 | 0.55 | 0.85 | 18 |
| construction | 0.92 | 0.85 | 0.98 | 9 |
| energized | 1.00 | — | — | 0 |
| withdrawn | 0.00 | — | — | — |

These are informed by LBNL Queued Up generation conversion (~20 % of queued generation reaches COD)
[DOCUMENTED-EXTERNAL, order of magnitude only] and are deliberately shown with intervals in the UI.

`load_factor` default 0.75 for hyperscale, 0.60 for colocation, 0.85 if `min_demand_share` stated
(use the stated share). `expected_real_mw = Σ p_operate × mw_est × load_factor`. Intervals by
Monte-Carlo (2 000 draws, Beta-distributed `p_operate` between lo/hi) → `expected_real_mw_lo/hi`.

Utility-level `forecast_mw`: PJM per-TO large-load adjustment; ERCOT from the LL report's total
"forecasted" column or ERCOT's long-term load forecast data-center component [UNVERIFIED which
file]; others from FERC 714 delta vs 2022 baseline attributed to data centers (crude; labelled).

### 4.4 Layer 4 — Grid Impact Score (`models/dc/impact.py`)

```python
class ScoreParams(TypedDict, total=False):
    mw: float                    # required
    curtailable_share: float     # 0..1, share of load that can be shed on request
    curtail_response_min: float  # minutes to respond (EPRI DCFlex: <15 fast, 15–60 medium, >60 slow)
    curtail_hours_yr: float      # committed curtailment hours per year
    byog_mw: float               # co-located generation
    storage_mw: float
    storage_hours: float
    load_factor: float           # 0..1
    service_type: str            # "firm" | "non_firm" | "interim"
    min_demand_share: float      # 0..1
    collateral_usd_per_mw: float
```

Seven components, each mapped to [0, 1], combined with fixed weights summing to 1.0:

| Component | Weight | Mapping |
|---|---|---|
| `flexibility` | 0.25 | `curtailable_share × r(response)` where `r = 1.0 (<15 min), 0.7 (15–60), 0.4 (>60)`; then `× min(1, curtail_hours_yr / 200)`. Rationale: Duke shows ~100 GW of headroom at 0.5 % curtailment (~44 h/yr) [DOCUMENTED-EXTERNAL]. |
| `byog` | 0.15 | `min(1, (byog_mw + 0.5·storage_mw·min(1, storage_hours/4)) / mw)` |
| `load_factor` | 0.10 | `1 − |load_factor − 0.85| / 0.85` (flat, predictable load scores best; very low LF is a phantom signal) |
| `headroom` | 0.20 | `min(1, headroom_mw(ba, curtail_pct*) / mw)` where `curtail_pct*` is the smallest Duke tier the site's `curtail_hours_yr` supports (0.25 % ≈ 22 h, 0.5 % ≈ 44 h, 1.0 % ≈ 88 h); 0 tier if no curtailment → use 0.25 % table × 0.25 |
| `congestion` | 0.10 | `1 − clip(local_lmp_congestion_spread_usd_mwh / 20, 0, 1)` using gridstatus 2025 mean absolute congestion component at the nearest pricing node [UNVERIFIED node mapping; fallback: ISO-zone mean] |
| `service_type` | 0.10 | firm 0.4 · interim 0.7 · non_firm 1.0 (non-firm relieves the system; FERC ordered PJM to create these) |
| `tariff` | 0.10 | `0.6·min(1, min_demand_share/0.85) + 0.4·min(1, collateral_usd_per_mw / 100_000)` |

`score = 100 × Σ weight_i × component_i`, rounded to integer.

**"What would make this a 90"** (`fixes_json`): greedy search over a fixed menu of changes, applied
one at a time, re-scoring each, ordered by `delta` desc, stopping when `score ≥ 90` or menu exhausted:

```
menu = [
  ("commit 200 h/yr curtailment, <15 min",  set curtailable_share=max(0.5, cur), curtail_response_min=10, curtail_hours_yr=200),
  ("add storage = 25% of MW, 4 h",           storage_mw += 0.25*mw, storage_hours=4),
  ("add on-site generation = 50% of MW",     byog_mw += 0.5*mw),
  ("accept non-firm / interim service",      service_type="non_firm"),
  ("sign 85% minimum-demand tariff",         min_demand_share=0.85),
  ("post collateral $100k/MW",               collateral_usd_per_mw=100_000),
]
```

`months_faster` per fix: `flexibility`/`service_type` fixes → 18 months (interim service avoids
full transmission study queue; assumption, labelled); storage/BYOG → 12; tariff → 0 (affects
phantom, not speed). These are demo assumptions, stated as such on the card.

### 4.5 Layer 5 — Cost model (`models/dc/cost.py`)

```
phantom_mw            = max(0, forecast_mw − expected_real_mw)
stranded_cost_usd     = phantom_mw × (capacity_cost_usd_per_mw + transmission_cost_usd_per_mw)
delay_months_real_loads = phantom_mw / (queue_throughput_mw_per_month(iso))
```

Defaults in `dc_cost_params` (`source='assumption; FERC Form 1 / IRP order of magnitude'`):
`capacity_cost_usd_per_mw = 1_500_000` (CCGT-class firm capacity), `transmission_cost_usd_per_mw = 500_000`.
`queue_throughput_mw_per_month(iso)` = energized MW over the last 24 months / 24 from `dc_projects`;
fallback 250 MW/month. Every number carries its `source` string to the UI.

### 4.6 Layer 6 — Copilot tools (`copilot/tools/dc.py`)

Exact signatures; all return JSON-serializable dicts; the model never computes.

```python
def phantom_ratio(utility: str) -> dict
    # → {utility, iso, announced_mw, queued_mw, forecast_mw, operating_mw,
    #    expected_real_mw, lo, hi, phantom_ratio, phantom_mw, as_of, sources: [...]}

def duplicates(developer: str) -> dict
    # → {developer_norm, entities: [{entity_id, mw_est, n_queues, flag, resolution_score,
    #    members: [{project_id, source, iso, utility, mw, stage, filed_date}]}]}

def score_dc_site(lat: float, lon: float, params: dict) -> dict
    # params validated against ScoreParams (pydantic); → {score, components: {...}, fixes: [...],
    #    ba_code, utility, county_fips, headroom_mw_used, congestion_usd_mwh_used, assumptions: [...]}

def cost_exposure(utility: str) -> dict
    # → {utility, phantom_mw, stranded_cost_usd, delay_months_real_loads, params_used: {...}}

# shared from Idea 1 (00-overview §2.4): sql(query), cite(query, k) — cite() here uses corpus tag "dc"
```

System prompt addendum: "You are a regulatory analyst's assistant. Every MW, dollar, probability,
and score you state must come from a tool result in this conversation. Conversion probabilities are
estimates with intervals; always state the interval. When asked which projects to scrutinise, rank
by `flag == 'shopping'`, then low `resolution_score`, then low `p_operate`, and cite the filing."

### 4.7 Causal layer (stretch, `causal/dc_conversion.py`)

DAG: `developer_type → p_operate`, `min_demand_share → p_operate`, `colocated_gen → p_operate`,
`iso_rules → p_operate`, `headroom → p_operate`, `stage → p_operate`, with `stage` also a
mediator of `filed_date`. Estimate the effect of `min_demand_share ≥ 0.75` on `energized` with
DoWhy backdoor adjustment on the `dc_projects` rows that have terminal states. Only meaningful if
the ERCOT stage history yields ≥ 100 terminal rows [UNVERIFIED]. Output: one sentence for the deck,
"minimum-demand tariffs raise conversion probability by X points (95 % CI …)", or, if underpowered,
the honest line "our sample is too small to estimate this; here is the DAG we would estimate it on."

Policy counterfactual (slide, not code): re-run `expected_real_mw` for Virginia with every entity
given `min_demand_share = 0.85` → `phantom_mw` falls by Y GW. This IS computable with §4.3 alone.

---

## 5. Interfaces (exact function/route signatures)

Python:

```python
# pipelines/dc/ingest_ercot.py
def ingest_ercot_large_load(raw_dir: Path, con: duckdb.DuckDBPyConnection) -> int   # rows written
# pipelines/dc/ingest_pjm.py
def ingest_pjm_load_forecast(raw_dir: Path, con) -> int
# pipelines/dc/ingest_cleanview.py
def ingest_cleanview(raw_dir: Path, con) -> int
# pipelines/dc/resolve.py
def resolve_entities(con, threshold: float = 0.72) -> int                              # entities written
# models/dc/reality.py
def compute_utility_ledger(con, as_of: date, n_draws: int = 2000) -> None
# models/dc/impact.py
def grid_impact_score(lat: float, lon: float, params: ScoreParams, con) -> ScoreResult
def suggest_fixes(lat, lon, params, con, target: int = 90) -> list[Fix]
# models/dc/cost.py
def cost_exposure_for(utility: str, con) -> CostExposure
# copilot/tools/dc.py  — the four tools in §4.6
```

CLI:

```
uv run python -m pipelines.dc.run_all            # ingest all sources present in data/raw/
uv run python -m pipelines.dc.resolve
uv run python -m models.dc.ledger --as-of 2026-09-01
uv run python -m models.dc.score --lat 30.27 --lon -97.74 --mw 500 --curtailable 0.3 ...
```

Routes: §3.3.

---

## 6. Acceptance criteria

1. `dc_projects` has ≥ 200 rows from ≥ 2 sources (ERCOT LL + Cleanview or PJM), every row with a non-null `stage` and `state`.
2. `dc_entities` contains ≥ 5 entities flagged `duplicate` or `shopping` with `resolution_score ≥ 0.85`, and a human has eyeballed them and agrees on ≥ 4.
3. `dc_utility_ledger` has a row for every ERCOT and PJM utility/TO with non-null `forecast_mw`; `phantom_ratio` is NULL only where `expected_real_mw = 0`.
4. `expected_real_mw_lo ≤ expected_real_mw ≤ expected_real_mw_hi` for every row (Monte-Carlo sanity).
5. `grid_impact_score` is deterministic (same inputs → same score) and monotone in each component: increasing `curtailable_share`, `byog_mw`, `storage_mw`, `min_demand_share`, or switching `firm → non_firm` never decreases the score (unit test with 50 random parameter sets).
6. `suggest_fixes` on a 54-ish baseline site reaches ≥ 90 within ≤ 3 fixes, and the demo card shows the `months_faster` figure with its assumption label.
7. `phantom_ratio("Dominion")` (or the ERCOT utility used in the demo) returns in < 1 s and the four MW figures sum consistently with `dc_projects` (`operating_mw ≤ queued_mw + announced_mw`).
8. Copilot answer to "Which three projects should <state>'s commission review most skeptically?" shows ≥ 2 tool calls (`duplicates`, `phantom_ratio` or `sql`) and ≥ 1 `cite` with a docket reference.
9. Every number displayed carries a `source` or `assumption` label in the UI (no unlabeled constants).
10. The Idea 1 tables and tools are untouched: `pytest tests/test_idea1_contract.py` (schema snapshot of the 00-overview tables) still passes after Idea 2 code is added.

---

## 7. Demo hook (Idea 2 backup demo script, 5 minutes)

| # | Beat | On screen | Tool / table |
|---|---|---|---|
| 1 | National map of utilities coloured by phantom ratio; zoom to ERCOT (or Dominion/Virginia if PJM ingest landed). | `/dc/utilities` choropleth by utility territory (use EIA-861 territory polygons [UNVERIFIED availability]; fallback: county-level with utility majority). | `dc_utility_ledger` |
| 2 | Drill in: four bars. "This utility is forecasting 3× what's likely to be built. Here's the ratepayer exposure." | Utility card: announced / queued / forecast / operating bars; expected-real band; stranded-cost number with source label. | `phantom_ratio`, `cost_exposure` |
| 3 | Duplicate table: one developer, same 500 MW, three queues. | `dc_entities` filtered `flag='shopping'`, expanded members. | `duplicates` |
| 4 | Score a real proposed site: 54/100. Click "what makes this 90": curtailment + storage. Re-score: 91. "18 months faster." | Score form → card → fixes list → re-scored card. | `score_dc_site` |
| 5 | Copilot: "Which PJM projects should Virginia's commission review most skeptically?" | SSE answer with visible tool calls and a citation to RM26-4 / the PJM show-cause response. | `duplicates`, `sql`, `cite` |
| 6 | Close: "FERC ordered the fix in June. This is the fix." | Slide. | — |

Judge hooks: White House anti-fraud (McCarthy) — misrepresentation in regulated filings with public
cost; entity resolution is anti-fraud tooling. FAI — policy counterfactual (§4.7). Craft — PUCs, RTOs,
utilities, hyperscalers as buyers; Emerald $150M, GridCARE $64M. Defense — real defense/manufacturing
loads stuck behind phantom ones. OPM — regulators doing in minutes what takes staff months.

Honest answers: "Cleanview already tracks projects" — it tracks announcements, not reconciliation
against queues/forecasts, and doesn't score sites. "Utilities have this internally" — each sees its
own slice; duplicates hide across utilities. "Your conversion estimates are uncertain" — yes, and we
show the interval; today's number has none.

---

## 8. Risks / unknowns

| Risk | Mitigation |
|---|---|
| ERCOT LL report is a PDF, not a spreadsheet, in some months [UNVERIFIED] | `pdfplumber` table extraction; pick the most recent month that is XLSX. |
| Cleanview free tier has no bulk export | Manual export of the Texas + Virginia subset (~100 rows) on Day 1 morning; document as manual. |
| PJM large-load adjustment is per-TO not per-project | Use it only for `forecast_mw`; project rows come from Cleanview/EEI. |
| Entity resolution false positives embarrass us on beat 3 | Only show `resolution_score ≥ 0.85`; the reviewer parquet exists for the honest answer. |
| Utility service-territory polygons unavailable | County choropleth with majority utility from EIA-861 sales; label the approximation. |
| The Idea 1 `score_site` and Idea 2 `score_site` names collide in the pitch text | Resolved: Idea 2's tool is `score_dc_site`. The deck text should say "score a site" not the function name. |
| Duke headroom tables are per-BA; ERCOT is one BA | Fine for ERCOT; for PJM use the PJM BA row. |

---

## 9. Weekend time-box (hours) — only if activated

| Task | Hours |
|---|---|
| Ingest ERCOT LL + Cleanview (+ PJM if easy) → `dc_projects` | 3 |
| Entity resolution + review parquet | 1.5 |
| Reality model + ledger + Monte-Carlo intervals | 1.5 |
| Grid Impact Score + fixes + unit tests | 2 |
| Cost model | 0.5 |
| Four copilot tools + `cite` corpus tag `dc` (RM26-4 PDFs) | 1.5 |
| Web: utility map + four-bar card + duplicate table + score form (reuse Idea 1 shell) | 3 |
| Deck (built regardless) | 1 |
| **Total** | **~14 (≈ 10 with two people in parallel)** |
