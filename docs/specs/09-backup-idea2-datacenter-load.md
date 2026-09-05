# 09 — Backup: Speed-to-Power (large-load verification + grid headroom ranking)

> **Scope order:** Minnesota is the current case ([`10-minnesota-demo.md`](10-minnesota-demo.md)); Texas is second; further states follow. Texas references below describe the second case, not the current one.

Status: **backup** (pitch v2 "Idea 2"). Not on the weekend critical path. Built only if (a) the judges
signal they want something narrower/nearer-term, (b) the format allows two entries, or (c) the Idea 1
(Flux) critical path is green by Day 2 noon and a pair is free. The deck for this pitch (≥ 6 slides)
IS built regardless (00-overview §10). This spec is written so one pair can build a demoable slice in
~10 hours on the shared stack without touching the Idea 1 tables.

Pitch v2 folded the former Idea 2 (data-center load verification) and Idea 3 (line-upgrade ranking)
into ONE backup: "Speed-to-Power". It has two halves that meet in the Grid Impact Score:

- **Load half** — which large-load requests are real (registry, entity resolution, reality model,
  phantom ratio, stranded cost). Owned by this spec; tables `dc_*`; tools §4.6.
- **Wire half** — which existing wires to upgrade first (IEEE 738 DLR uplift, reconductoring, MW per
  dollar, FERC RM24-6 screen, SPARK flag). **Owned by spec 08** and REUSED here unchanged: tables
  `line_upgrade_scores` + `line_upgrade_detail`, tool `top_lines(region, tech, n)`, the `/lines/top`
  route and the `line_upgrades` map layer. This spec adds only a per-line card tool `line_profile(line_id)`
  (§4.6) that reads `line_upgrade_detail`. Nothing about line scoring is re-specified here; if 08 and
  this file disagree on a line column, 08 wins.

Conforms to 00-overview §2 (repo layout, Python/Node conventions, DuckDB file, Claude tool-loop).
All load-half tables are namespaced `dc_*` so they coexist in `data/duck/grid.duckdb` with the Idea 1
tables. The Idea 1 tool `score_site(site_id, unit_mw, scenario_id)` is NOT reused; the load-half site
scorer is `score_dc_site(lat, lon, params)` to avoid the name collision (the pitch text's
`score_site(lat, lon, params)` means this tool).

---

## 1. Purpose

For every utility / ISO large-load queue, reconcile four numbers — **announced**, **queued**,
**forecast**, **operating** — and expose the gap as a *phantom ratio*. Detect the same project or
developer appearing in multiple queues. Estimate the stranded-cost exposure of building for phantom
load. Score any proposed data-center site 0–100 on grid impact with a plain-English "what would make
this a 90". Give regulators a copilot that answers "which three projects should Virginia review most
skeptically?" with citations to the filings.

And the wire half (by reference to spec 08): for every high-voltage line in the region, rank the
cheapest megawatts of new capacity (DLR vs. reconductor, MW per $M, FERC screen, SPARK eligibility) so
the Grid Impact Score's "what would make this a 90" can name a **specific line upgrade** — not only a
curtailment or storage commitment — and the copilot can answer the second clause of "which three
projects should Virginia review most skeptically, **and which two line upgrades would unblock the real
ones**?" The one-question framing (pitch v2 honest answer): where does real load connect fastest? The
load half says which requests are real; the wire half says where the headroom is; the score joins them.

Geographic scope if built this weekend: **ERCOT first** (the Large Load Interconnection Status report
is a single public spreadsheet; spec 08's `line_upgrade_scores` is ERCOT-first too, so the two halves
overlap on the same region), PJM second (public load-forecast large-load adjustments), national
map only from Cleanview announced projects as a scale layer.

---

## 2. Inputs (tables/files)

### 2.1 Raw sources → `data/raw/<source>/`

| Source | What | Where | Confidence |
|---|---|---|---|
| ERCOT Large Load Interconnection Status report (monthly, NPRR 1267 approved by PUCT 31 July 2025; ≥ 75 MW projects; aggregated by load zone / TSP / load type) | queued MW by project, county, stage, requested energization date [UNVERIFIED that the public report is per-project rather than aggregated — NPRR 1267 describes "aggregated visibility"] | `https://www.ercot.com/services/rq/large-load-integration` (verified page; the earlier `/gridinfo/load/large_load` URL was wrong) → `data/raw/ercot_ll/` | High that data exists; medium on per-project granularity |
| ERCOT "Batch Zero" list (Texas SB 6, signed 20 June 2025; Batch Zero protocol revisions approved by ERCOT Board 2 June 2026 and PUCT 18 June 2026; ≥ 75 MW; submissions closed 10 July 2026; classification notices 7 Aug 2026; allocations Spring 2027 — verified) | projects admitted under the new large-load batch process | ERCOT large-load page [UNVERIFIED that a public project-level Batch Zero list is posted] → `data/raw/ercot_ll/` | Medium |
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
| FERC docket RM26-4 (DOE §403 ANOPR, 23 Oct 2025) + the six §206 show-cause orders of 18 June 2026 (EL26-67 … EL26-72; responses due 17 Aug 2026 — verified) and the RTO responses; PJM Board CIFP decisional letter (16 Jan 2026 — verified); ERCOT SB6 / Batch Zero rules | regulatory corpus for `cite` | FERC eLibrary PDFs → `data/raw/regs_dc/` | Medium |

### 2.2 Shared tables read from Idea 1 (spec 01)

`counties`, `buses`, `lines`, `ba_load_hourly`, `hazard_static` (not needed but available).

### 2.3 Wire-half tables read from spec 08 (not written here)

`line_upgrade_scores(line_id, congestion_usd_yr, dlr_uplift_mw, reconductor_uplift_mw, dlr_cost_usd,
reconductor_cost_usd, mw_per_musd, ferc_screen_pass, spark_eligible)` (00-overview §2.2) and
`line_upgrade_detail(line_id, owner, conductor_material, conductor_kcmil, static_rating_mw,
aar_rating_mw, dlr_p50_mw, dlr_hours_above_static, best_tech, payback_yr, congestion_method, region)`
(00 amendment A4; spec 08 §Design). Both must be populated by `pipelines.line_upgrade --region ERCOT`
before this pitch's beats 3–4 work; spec 08's Day 1 17:00–19:00 slot already produces them for Idea 1.

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
  fixes_json      TEXT,               -- ordered list of {change, new_score, delta, months_faster, line_id?}  (line_id set for wire-half fixes)
  serving_line_ids_json TEXT,         -- wire half: the ≤ 2 nearest ≥ 138 kV lines (from `lines` geometry) whose line_upgrade_scores rows feed `congestion` and the line-upgrade fix
  created_at      TIMESTAMP
)
```

Wire-half outputs (`line_upgrade_scores`, `line_upgrade_detail`, the `line_upgrades` layer, the
regional top-10 table) are spec 08's outputs and are not re-declared here.

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
GET  /dc/line/{line_id}                  → line_profile(...) result (per-line card; reads line_upgrade_detail ⋈ line_upgrade_scores)
POST /ask                                    → same SSE endpoint as Idea 1 (spec 05); tools selected by corpus tag
# wire half, reused from spec 05/08 unchanged:
GET  /lines/top?region=&tech=any&n=10    → top_lines(...)            (spec 05 route, spec 08 tool)
GET  /layers/line_upgrades?tech=         → line_upgrade_scores ⋈ lines GeoJSON  (spec 05 layer)
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

These are informed by LBNL Queued Up 2026 generation conversion — of all capacity requesting
interconnection 2000–2020, only **13 %** had reached commercial operation by end-2025 and 75 % was withdrawn
(the earlier "~20 %" was the older project-count statistic) [DOCUMENTED-EXTERNAL, order of magnitude only]
and are deliberately shown with intervals in the UI.

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
    curtail_response_min: float  # minutes to respond (<15 fast, 15–60 medium, >60 slow — OUR bins; [UNVERIFIED that EPRI DCFlex / Flex MOSAIC (23 Mar 2026) uses these cut-points — its public page names magnitude/timing/duration/frequency dimensions but the numeric tiers are only in the technical brief, not read])
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
| `flexibility` | 0.25 | `curtailable_share × r(response)` where `r = 1.0 (<15 min), 0.7 (15–60), 0.4 (>60)`; then `× min(1, curtail_hours_yr / 200)`. Rationale: Duke "Rethinking Load Growth" (11 Feb 2025) shows 76–126 GW of headroom across the 22 largest BAs at 0.25–1.0 % curtailment (~22–88 h/yr), ~100 GW at 0.5 %; ERCOT 10 GW and PJM 18 GW at 0.5 % [DOCUMENTED-EXTERNAL, verified from Utility Dive / RTO Insider coverage of the report]. |
| `byog` | 0.15 | `min(1, (byog_mw + 0.5·storage_mw·min(1, storage_hours/4)) / mw)` |
| `load_factor` | 0.10 | `1 − |load_factor − 0.85| / 0.85` (flat, predictable load scores best; very low LF is a phantom signal) |
| `headroom` | 0.20 | `min(1, headroom_mw(ba, curtail_pct*) / mw)` where `curtail_pct*` is the smallest Duke tier the site's `curtail_hours_yr` supports (0.25 % ≈ 22 h, 0.5 % ≈ 44 h, 1.0 % ≈ 88 h); 0 tier if no curtailment → use 0.25 % table × 0.25 |
| `congestion` | 0.10 | `1 − clip(local_lmp_congestion_spread_usd_mwh / 20, 0, 1)` using gridstatus 2025 mean absolute congestion component at the nearest pricing node [UNVERIFIED node mapping; fallback: ISO-zone mean]. Wire-half fold: if the site's `serving_line_ids` have `line_upgrade_scores` rows, use `max(congestion_usd_yr)` over them normalised by the region's 90th-percentile `congestion_usd_yr` as the spread proxy instead (labelled `congestion_method = "twin-loading proxy (spec 08)"`, same caveat as 00 honest answer 8). |
| `service_type` | 0.10 | firm 0.4 · interim 0.7 · non_firm 1.0 (non-firm relieves the system; FERC ordered PJM to create an interim, curtailable NITS product for co-located load — compliance filing due 17 Feb 2026 — verified) |
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
  # wire half (spec 08 data): one entry per serving line with a line_upgrade_scores row, best_tech from line_upgrade_detail
  (f"{best_tech} on {line_id}",              congestion component recomputed with that line's congestion_usd_yr
                                             reduced by uplift_mw / static_rating_mw (clipped 0..1); fix carries line_id),
]
```

`months_faster` per fix: `flexibility`/`service_type` fixes → 18 months (interim service avoids
full transmission study queue; assumption, labelled); storage/BYOG → 12; tariff → 0 (affects
phantom, not speed); named line upgrade → 18 if `best_tech = dlr` (months-scale deployment, FERC
RM24-6 framing), 12 if `reconductor` (assumption; REWIRE-style categorical exclusion not assumed).
These are demo assumptions, stated as such on the card. The demo card's fix set is "commit 200 h/yr
curtailment + DLR on the two serving lines → 54 → 91, 18 months sooner" (pitch v2 beat 4).

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

# wire half — new here, reads spec 08's side table only:
def line_profile(line_id: str) -> dict
    # → {line_id, from_bus, to_bus, kv, owner, conductor_material, conductor_kcmil,
    #    static_rating_mw, aar_rating_mw, dlr_p50_mw, dlr_hours_above_static,
    #    congestion_usd_yr, congestion_method, dlr_uplift_mw, reconductor_uplift_mw,
    #    dlr_cost_usd, reconductor_cost_usd, mw_per_musd, best_tech, payback_yr,
    #    ferc_screen_pass, spark_eligible, region, sources: [...]}
    # line_upgrade_detail ⋈ line_upgrade_scores ⋈ lines on line_id; 404-shaped error if 08 has not scored it

# wire half — reused unchanged from spec 08 / 00-overview §2.4: top_lines(region, tech, n)
# shared from Idea 1 (00-overview §2.4): sql(query), cite(query, k) — cite() here uses corpus tag "dc"
```

Tool set when this pitch is active: `phantom_ratio`, `duplicates`, `score_dc_site`, `cost_exposure`,
`line_profile`, `top_lines`, `sql`, `cite` (matches pitch v2 Layer 6, with `score_site(lat, lon, params)`
read as `score_dc_site`). The `cite` corpus for the wire half adds FERC RM24-6, Order 881, and the DOE
SPARK notice [UNVERIFIED that the SPARK notice PDF is posted] under corpus tag `dc`.

System prompt addendum: "You are a regulatory analyst's assistant. Every MW, dollar, probability,
and score you state must come from a tool result in this conversation. Conversion probabilities are
estimates with intervals; always state the interval. When asked which projects to scrutinise, rank
by `flag == 'shopping'`, then low `resolution_score`, then low `p_operate`, and cite the filing.
When asked which upgrades would unblock real loads, call `top_lines` for the region and `line_profile`
for each line you name; state `mw_per_musd` and `best_tech` from the tool, never a payback you computed."

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
# models/dc/impact.py — wire-half join
def serving_lines(lat: float, lon: float, con, k: int = 2, min_kv: float = 138.0) -> list[str]   # nearest line_ids by geometry
# copilot/tools/dc.py  — the four load-half tools in §4.6 + line_profile
def line_profile(line_id: str) -> dict
# wire half reused, not re-implemented: pipelines.line_upgrade.score_lines, copilot.tools_lines.top_lines (spec 08)
```

CLI:

```
uv run python -m pipelines.dc.run_all            # ingest all sources present in data/raw/
uv run python -m pipelines.dc.resolve
uv run python -m models.dc.ledger --as-of 2026-09-01
uv run python -m models.dc.score --lat 30.27 --lon -97.74 --mw 500 --curtailable 0.3 ...
uv run python -m pipelines.line_upgrade --region ERCOT     # wire half — spec 08's CLI, run as-is before beats 3–4
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
11. Wire half: `line_profile(line_id)` for every line in `top_lines("ERCOT","any",10)` returns a dict whose `mw_per_musd`, `best_tech`, `ferc_screen_pass`, `spark_eligible` equal the `line_upgrade_scores`/`line_upgrade_detail` rows byte-for-byte (pass-through, tested by equality; no re-scoring in this spec).
12. `suggest_fixes` on the demo site returns at least one fix with a non-null `line_id`, and that `line_id` is one of the site's `serving_line_ids`.

---

## 7. Demo hook (Speed-to-Power backup demo script, 5 minutes — pitch v2 merged beats)

| # | Beat | On screen | Tool / table |
|---|---|---|---|
| 1 | National map of utilities coloured by phantom ratio; zoom to Dominion / Virginia (or ERCOT if PJM ingest did not land). Four bars: "forecasting 3× what's likely to be built; here's the ratepayer exposure." | `/dc/utilities` choropleth by utility territory (use EIA-861 territory polygons [UNVERIFIED availability]; fallback: county-level with utility majority) → utility card: announced / queued / forecast / operating bars; expected-real band; stranded-cost number with source label. | `dc_utility_ledger`, `phantom_ratio`, `cost_exposure` |
| 2 | Duplicate table: one developer, same 500 MW, three queues. | `dc_entities` filtered `flag='shopping'`, expanded members. | `duplicates` |
| 3 | Toggle to the line layer: "The cheapest capacity in America is already built; it's just under-rated." Click a corridor card: "DLR cut congestion 97 % on the PPL line. Our model would have flagged it." | Spec 08 screen reused: `line_upgrades` layer coloured by `mw_per_musd`; regional top-10 table; line card from `line_profile`. The PPL figure is a slide claim ($66 M → $1.6 M on one line, PPL/PJM) [UNVERIFIED exact figures — cite the PPL/LineVision press source on the slide, do not put it in a tool result]; ERCOT lines are what the live table shows. | `top_lines`, `line_profile`, `line_upgrade_scores`, `line_upgrade_detail` |
| 4 | Score a real proposed site: 54/100. Click "what makes this 90": curtailment commitment + DLR on two named serving lines. Re-score: 91. "That's 18 months faster to power." | Score form → card (components incl. `congestion` from the serving lines) → fixes list with `line_id`s → re-scored card. | `score_dc_site` (+ `serving_lines`, `line_upgrade_scores`) |
| 5 | Copilot: "Which PJM projects should Virginia review most skeptically, and which upgrades unblock the real ones?" | SSE answer with visible tool calls; citation to RM26-4 / the PJM show-cause response for the load half and RM24-6 for the wire half. | `duplicates`, `sql`, `top_lines`, `line_profile`, `cite` |
| 6 | Close: "FERC ordered the load fix in June and DOE is awarding $1.9 B for the wire fix this fall. This is the list for both." (18 June 2026 show-cause orders to all six RTOs/ISOs; responses filed by 17 Aug 2026 — verified. DOE $1.9 B / SPARK award timing [UNVERIFIED — from pitch v2; confirm the notice before the slide]) | Slide. | — |

Judge hooks (combined, pitch v2): White House anti-fraud (McCarthy) — phantom load is
misrepresentation in regulated filings with public cost; entity resolution is anti-fraud tooling.
FAI (Levine, Dauber) — the AI-power-buildout policy fight plus the permitting-reform story (REWIRE Act
categorical exclusion for reconductoring [UNVERIFIED bill status]); the tool produces policy
counterfactuals (§4.7). Craft Ventures (Murray) — buyers are state PUCs, RTOs, utilities, hyperscalers
who need to prove they're real, and GETs vendors (LineVision, Heimdall, TS Conductor, Smart Wires) who
need lead lists; Emerald AI $150 M Series A at $1.05 B (25 Aug 2026 — verified), GridCARE $64 M Series A
(14 May 2026 — verified). Defense judges — real defense/manufacturing loads stuck behind phantom ones,
and capacity without new corridors means hardening supply to installations without decade-long NEPA
fights. OPM (Hennecken) — regulators doing in minutes what takes staff months. Dirac / Forterra /
KAIROS — honest engineering product with physics (IEEE 738, twin loading) under the wire half.

Honest answers: "Cleanview already tracks projects" — it tracks announcements, not reconciliation
against queues/forecasts, and doesn't score sites. "Utilities have this internally" — each sees its
own slice; duplicates hide across utilities. "Your conversion estimates are uncertain" — yes, and we
show the interval; today's number has none. "Constraint-to-line mapping is hard" — yes; spec 08 uses
a twin-loading congestion proxy this weekend (00 honest answer 8) and says so; PJM constraint mapping
is the post-weekend path. "Two products in one" — they're one question: where does real load connect
fastest? The load half says which requests are real; the wire half says where the headroom is; the
score joins them.

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
| Wire half depends on spec 08 finishing `line_upgrade_scores` + `line_upgrade_detail` | 08 is on Idea 1's Day 1 plan regardless; if it slips, beats 3–4 drop the line layer and the line fix, and the deck's wire slides use spec 08's unit-test lines. No line scoring is re-implemented here. |
| Demo site is in Virginia (PJM) but `line_upgrade_scores` is ERCOT-only this weekend | Score a Texas site for beat 4 (serving lines exist), or run beat 4 in ERCOT and beats 1–2 in PJM; say which region each screen is on. |

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
| Wire half: `serving_lines` join, `line_profile` tool, line fix in the menu, RM24-6/Order 881 into corpus `dc` (line scoring itself is spec 08's time, not counted here) | 1 |
| Web: utility map + four-bar card + duplicate table + score form (reuse Idea 1 shell and the spec 08 line screen) | 3 |
| Deck (built regardless) | 1 |
| **Total** | **~15 (≈ 10–11 with two people in parallel)** |
