# 04 — Siting Engine (`siting/`)

Status: draft · Scope: Texas-first (ERCOT / ACTIVSg2000) · Owner: siting team

## Purpose

Rank places to put the next firm (nuclear) gigawatt in Texas with **two independent scores** per
candidate site: a **safety/buildability score** (an open-data re-implementation of the OR-SAGE /
STAND exclusion-and-avoidance criteria) and a **grid-value score** (drop a 300 MW or 1 GW unit at
the site's bus in the twin, re-run the stress scenarios from spec 03, and measure loss-of-load
reduction, congestion relief, and black-start reach). Attach a **regulatory-path label** to each
site. Expose `score_site(site_id, unit_mw, scenario_id)` to the copilot and persist everything to
`site_candidates` / `site_scores`.

Three modules: `siting/candidates.py`, `siting/safety.py`, `siting/grid_value.py`, plus
`siting/rank.py` (combination + label) and `siting/tools.py` (copilot wrapper).

## Inputs

| Input | Source | Notes |
|---|---|---|
| Retired / retiring coal units, existing nuclear | EIA-860 via PUDL (`data/raw/pudl/` — `core_eia860__scd_generators`, `core_eia860__scd_plants`) filtered `state='TX'`, `prime_mover/fuel` coal, `operational_status in (retired, proposed retirement)`, `retirement_date` ≥ 2010 or planned ≤ 2032 | Gives plant lat/lon, nameplate (→ `capacity_slot_mw`), `eia_plant_id`. |
| DOE federal sites | Static CSV `data/raw/siting/doe_federal_sites.csv` (INL, Oak Ridge, Paducah, Savannah River — DOE's July 2025 selections for AI data-center + energy projects, verified) | None are in Texas; they are loaded for the national scale slide and the `kind='doe_federal'` code path, and for Pantex (Amarillo, TX) as the one Texas DOE/NNSA site **[UNVERIFIED whether Pantex is in scope of any DOE authorization; label it `doe_federal` with a caveat]**. |
| DoD installations | Public DoD installation boundaries (`data/raw/dod/`; the "Military Installations, Ranges, and Training Areas" public layer) filtered to Texas, area ≥ 5 000 acres (Fort Cavazos/Hood, Fort Bliss, JBSA, Dyess, Sheppard, Corpus NAS, Red River AD) | Also the `critical_loads(kind='dod')` source in spec 01. |
| Population | Census block-group or tract population + geometry (`data/raw/census/`) | For the 20-mile density criterion. |
| Seismic | USGS NSHM 2023 PGA (2 % in 50 yr) raster or county summary → `hazard_static.seismic_pga` | |
| Floodplain | FEMA NFHL 100-yr zones (`data/raw/fema_nfhl/`, Texas subset) — fallback: FEMA NRI riverine/coastal flood risk index at county level if NFHL download is too large | |
| Cooling water | NHDPlus flowlines with mean annual flow (`data/raw/nhd/`), major reservoirs (NHD waterbody ≥ 2 km²), Gulf coast | |
| Protected land | PAD-US (GAP status 1–2 + all federal designations) | |
| Slope | USGS 3DEP 1-arc-second DEM → slope at site and within 1 km | |
| Wildfire | USFS Wildfire Hazard Potential → `hazard_static.wildfire_hazard` | |
| State moratorium | Static table `data/raw/siting/state_moratoria.csv` (state, status, statute) — Texas: none | |
| Twin | spec 03 `run_scenario`, `run_cascade` | For grid value. |
| DuckDB | `buses`, `lines`, `gens`, `loads`, `counties`, `critical_loads`, `scenarios`, `hazard_static`, `cascade_runs` | |

## Outputs

- `site_candidates(site_id, name, kind[coal_retired|coal_retiring|nuclear_existing|doe_federal|dod], lon, lat, county_fips, bus_id, capacity_slot_mw)` — `bus_id` = nearest twin bus with `base_kv ≥ 138` within 40 km; else NULL and the site is `unconnected` (still safety-scored, grid-value NULL).
- `site_scores(site_id, scenario_id, unit_mw, safety_score, safety_flags_json, grid_value_score, lol_reduction_mwh, congestion_relief_pct, blackstart_reach_mw)` — one row per (site, scenario, unit size). `scenario_id='all'` rows hold the scenario-averaged values used for ranking.
  - `safety_flags_json`: list of `{"criterion": str, "kind": "exclusion"|"avoidance", "value": float, "threshold": float, "passed": bool, "source": str}`.
- `data/parquet/site_scores.parquet` and `site_cards/<site_id>.json` (for the front end: three reasons, three risks, regulatory path, DoD installations covered).
- `SiteScore` dataclass returned by `score_site`.

## Algorithm or Design

### `siting/candidates.py`

1. Coal: from PUDL generators, group by plant; `kind = coal_retired` if all coal units retired,
   `coal_retiring` if any unit has a planned retirement ≤ 2032; `capacity_slot_mw` = sum of
   retired/retiring nameplate (a proxy for the interconnection/right-of-way slot). Expect ~15–25
   Texas plants (Gibbons Creek, Oklaunion, Monticello, Big Brown, Sandow, Coleto Creek, Pirkey,
   Martin Lake, Welsh, W.A. Parish coal units, San Miguel, Limestone, Oak Grove, Twin Oaks,
   Fayette/Sam Seymour, J.K. Spruce, Harrington, Tolk …) **[UNVERIFIED individual statuses — the
   PUDL pull is authoritative, not this list]**.
2. Nuclear existing: Comanche Peak, South Texas Project (`capacity_slot_mw` = 1200 per proposed
   added unit slot).
3. DOE federal, DoD: from the static/boundary sources above; DoD `lon,lat` = boundary centroid.
4. `bus_id` assignment: KD-tree over `buses` filtered `base_kv >= 138`; take nearest within 40 km.
5. Idempotent upsert into `site_candidates` keyed by `site_id` (`f"{kind}:{eia_plant_id or slug}"`).

### `siting/safety.py` — OR-SAGE / STAND on open layers

OR-SAGE (ORNL/TM-2012/403, "Updated Application of Spatial Data Modeling and Geographical
Information Systems (GIS) for Identification of Potential Siting Options for Various Electrical
Generation Sources") defines site selection & evaluation criteria (SSEC) as **exclusionary**
(hard fail) or **avoidance** (penalty); its criteria list verified from the ORNL abstract:
population density, slope, seismic, cooling water proximity, hazardous facilities proximity,
protected lands, floodplains, landslide hazard. STAND (INL/ANL/ORNL/UMich, used in DOE's Sept
2024 "Evaluation of Nuclear Power Plant and Coal Power Plant Sites for New Nuclear Capacity",
verified) extends this with socioeconomic and proximity parameters. Each criterion below names its
open source; thresholds marked **[UNVERIFIED]** are our reading of the OR-SAGE / EPRI 2002 /
Reg Guide 4.7 values and must be checked against ORNL/TM-2012/403 Table 1 before the demo
(the PDF is downloaded at `data/raw/siting/ORNL-TM-2012-403.pdf`; verification is task 1 of
this module):

| # | Criterion | Kind | Rule (site passes if …) | Open source |
|---|---|---|---|---|
| S1 | Population density | exclusion | pop density within 20-mile radius ≤ 500 people/sq mi (Reg Guide 4.7 guideline; pitch contract) | Census tracts, area-weighted |
| S2 | Population center | avoidance | no place ≥ 25 000 residents within 4 miles (10 CFR 100 "population center distance" ≈ 1⅓ × EAB **[UNVERIFIED distance]**) | Census places |
| S3 | Seismic | exclusion | PGA (2 % in 50 yr) < 0.30 g **[UNVERIFIED — OR-SAGE uses SSE-based ≥ 0.3 g exclusion]** | USGS NSHM 2023 |
| S4 | Floodplain | exclusion | site not inside 100-yr floodplain | FEMA NFHL / NRI fallback |
| S5 | Cooling water | avoidance | a stream with mean flow ≥ 50 000 gpm (~113 cfs) or a reservoir ≥ 2 km² or coast within 20 miles **[UNVERIFIED flow threshold; OR-SAGE uses a per-MW makeup-water rule]** | NHDPlus |
| S6 | Protected land | exclusion | site not within PAD-US GAP 1–2 or national park/wilderness/wildlife refuge | PAD-US |
| S7 | Slope | exclusion | mean slope within 1 km ≤ 12 % (EPRI 2002 large-reactor guidance, verified in search results) | 3DEP DEM |
| S8 | Wildfire | avoidance | USFS WHP class ≤ "moderate" | USFS WHP |
| S9 | Hazardous facilities | avoidance | no airport, military ordnance, or LNG/chem facility within 5 miles **[UNVERIFIED distance]** | HIFLD/OSM |
| S10 | Landslide | avoidance | not in USGS landslide-susceptibility "high" | USGS |
| S11 | State moratorium | exclusion | state has no new-nuclear moratorium (Texas: pass) | static table |
| S12 | Wetlands | avoidance | site footprint (1 km²) < 25 % NWI wetlands | USFWS NWI |

Scoring: `safety_score = 0` if any exclusion fails; else
`100 × ∏(avoidance passed ? 1 : penalty_i)` with `penalty = {S2: 0.6, S5: 0.5, S8: 0.8, S9: 0.7, S10: 0.8, S12: 0.9}`.
Every criterion emits one `safety_flags_json` entry with the measured value, threshold and source
so the card can say "population density 61 /sq mi within 20 mi (limit 500)".

Population-density special case: under the NRC's July 2026 proposed rule (verified: >550 pages;
proposed 10 CFR 53.530 allows siting at higher density "based on assessments of societal risk
in comparison with societal benefits"), an S1 failure is downgraded from exclusion to
avoidance (`penalty 0.4`) and the site's regulatory path is labelled `nrc_tier2_societal_risk`
(see labels below). The Tier 1/Tier 2 nomenclature is the pitch's term **[UNVERIFIED as the
rule's own wording]**; the card prints the §53.530 language.

### `siting/grid_value.py` — the number nobody else produces

For `(site, unit_mw, scenario_id)`:

1. `net_with = add_unit(net, bus_id, unit_mw)` — `pp.create_gen(net, bus, p_mw=unit_mw,
   vm_pu=1.0, max_p_mw=unit_mw, min_p_mw=0.3*unit_mw, name=site_id, element_id=f"gen:{site_id}")`
   with fuel `nuclear` (so spec 03's cold-weather derate treats it as nuclear).
   Dispatch: existing generators are scaled down pro-rata by `unit_mw` so total gen still equals
   total load (DC PF constraint); this is the honest "displaces marginal gen" assumption.
2. `base = run_scenario(scenario_id, seed=0, net=base_net, write=False)`
   `with_ = run_scenario(scenario_id, seed=0, net=net_with, write=False)` — (amendment A1 in 00-overview: after ranking, re-run the #1 site with `write=True`, `run_id="uri_2021-s0-cf-<site_id>-1000"`, `counterfactual_site_id=<site_id>` so the UI toggle has a row) — **same seed, so the
   weather sample is identical** and the difference is purely the do-operation.
3. `lol_reduction_mwh = Σ_h (base.lost_load_mw − with_.lost_load_mw)` (hourly rows, 1 h steps).
4. `congestion_relief_pct = 100 × (1 − Σ_h Σ_lines max(0, loading_with − 90) / Σ_h Σ_lines max(0, loading_base − 90))`
   — relief of the >90 %-loading exceedance mass on the base case; 0 if base has none.
5. `blackstart_reach_mw` = load (MW, base scaled at scenario peak hour) at buses reachable from the
   site's bus through in-service ≥ 138 kV lines within 3 hops AND within `unit_mw` cumulative
   load (a greedy BFS that "energizes" nearest load first). Proxy for cranking-path reach; it is
   a graph metric, not a transient-stability claim, and the card says so.
6. `critical_loads_protected` = DoD/hospital/water `cl_id`s that are in
   `base.critical_loads_lost` but not `with_.critical_loads_lost`.
7. `grid_value_score` (0–100) = `40 × z(lol_reduction_mwh) + 30 × z(congestion_relief_pct) +
   20 × z(blackstart_reach_mw) + 10 × min(1, len(critical_loads_protected)/3)` where `z` is
   min–max over all candidate sites for the same `(scenario_id, unit_mw)`; `scenario_id='all'`
   averages over `uri_2021`, `beryl_2024`, `helene_2024` (Helene did not touch Texas — its
   ERCOT-scaled run is near-zero LOL and is kept so the scoring code is scenario-agnostic;
   ranking weight for Helene in Texas = 0 in `params.yaml`).

Runtime (spec 03 measured 0.84 s per pandapower DC solve): 3 scenarios × ≤ 25 sites × 2 unit
sizes × full 168-h replay ≈ 500+ solves each → hours with pandapower. So:
(a) grid value uses **stress hours only** via `run_scenario(..., hours=stress_hours(sid, 12))`:
the 12 hours with highest `base.lost_load_mw` per scenario (pre-computed from spec 03's baseline
`cascade_runs`) → 12 × ~4 stages ≈ 50 solves ≈ 40 s per site-scenario with pandapower, ~2 s with
`solver="lightsim"` (spec 03's default);
(b) the base run per (scenario, hours) is computed once and shared across all sites;
(c) results are cached in `site_scores` and `score_site` re-runs only on cache miss or `force=True`.
Whole Texas batch target: **< 20 min with lightsim**; with pandapower fall back to 6 stress hours
and 1 unit size (1 GW) for the demo batch (~25 × 3 × 20 s ≈ 25 min), stated in the run summary.

### `siting/rank.py` — combination + regulatory path

`combined = safety_score^0.5 × grid_value_score^0.5` (geometric mean; a zero safety score
zeros the site). Ties broken by `lol_reduction_mwh`.

Regulatory-path label (one per site, first match):

| Label | Rule | Basis (verified unless marked) |
|---|---|---|
| `doe_authorized_federal_land` | `kind='doe_federal'` | DOE's 2025 RFAs for INL/ORR/SRS/Paducah pair reactors with data centers on federal land; EO 14301/14302 direct DOE authorization pathways **[UNVERIFIED that DOE authorization substitutes for NRC licensing for commercial units]** |
| `advance_act_brownfield` | `kind in (coal_retired, coal_retiring)` and S1–S7 pass | ADVANCE Act §206-ish brownfield/retired-fossil pathway (Act requires NRC to develop a pathway for timely licensing at brownfield and retired fossil sites — verified) + 55 % hourly-fee reduction for advanced reactor applicants (verified) |
| `nrc_tier1_low_density` | S1 passes and S2 passes, non-federal | Existing preference for low-population siting (Reg Guide 4.7); pitch's "Tier 1" |
| `nrc_tier2_societal_risk` | S1 or S2 fails but all other exclusions pass | Proposed 10 CFR 53.530 societal risk-benefit alternative (verified) |
| `dod_installation` | `kind='dod'` | Army Janus microreactor program / Project Pele context **[UNVERIFIED program details]**; card notes DoD sites may use DOE/DoD authorization |
| `excluded` | any non-population exclusion fails | — |

Site card: three biggest reasons = top-3 positive contributors among `{lol_reduction_mwh,
congestion_relief_pct, blackstart_reach_mw, critical_loads_protected, capacity_slot_mw, S5 pass}`;
three biggest risks = failed/penalized flags plus `unconnected` if applicable. Citations are
strings the copilot can paste: `10 CFR 100.21`, `Reg Guide 4.7 rev 3`, `ORNL/TM-2012/403`,
`DOE 2024 Evaluation of NPP and CPP Sites`, `ADVANCE Act of 2024`, `EO 14302`, `NRC proposed
rule July 2026 (10 CFR 53.530)`.

## Interfaces

```python
# siting/candidates.py
def build_candidates(state: str = "TX", duck_path: Path = Path("data/duck/grid.duckdb"),
                     pudl_dir: Path = Path("data/raw/pudl")) -> pandas.DataFrame   # also upserts site_candidates
def assign_bus(lon: float, lat: float, min_kv: float = 138.0, max_km: float = 40.0) -> str | None

# siting/safety.py
@dataclass(frozen=True)
class SafetyFlag: criterion: str; kind: Literal["exclusion","avoidance"]; value: float; threshold: float; passed: bool; source: str
@dataclass(frozen=True)
class SafetyResult: site_id: str; safety_score: float; flags: list[SafetyFlag]; population_downgraded: bool
def score_safety(site_id: str, lon: float, lat: float, layers: SitingLayers,
                 proposed_rule_mode: bool = True) -> SafetyResult
def load_layers(raw_dir: Path = Path("data/raw")) -> SitingLayers     # loads/caches all rasters + vectors once
def population_density_within(lon: float, lat: float, radius_mi: float, tracts) -> float   # exposed for tests

# siting/grid_value.py
@dataclass(frozen=True)
class GridValueResult:
    site_id: str; scenario_id: str; unit_mw: int
    lol_reduction_mwh: float; congestion_relief_pct: float; blackstart_reach_mw: float
    critical_loads_protected: list[str]; grid_value_score: float | None; hours_evaluated: list[int]
def add_unit(net: pandapowerNet, bus_id: str, unit_mw: int, site_id: str) -> pandapowerNet
def stress_hours(scenario_id: str, n: int = 12) -> list[int]
def score_grid_value(site_id: str, unit_mw: int, scenario_id: str, base_net: pandapowerNet | None = None,
                     hours: list[int] | None = None) -> GridValueResult      # grid_value_score None until normalized in batch
def blackstart_reach(net: pandapowerNet, bus_id: str, unit_mw: int, max_hops: int = 3, min_kv: float = 138.0) -> float

# siting/rank.py
@dataclass(frozen=True)
class SiteScore:
    site_id: str; scenario_id: str; unit_mw: int; safety: SafetyResult; grid: GridValueResult
    combined: float; regulatory_path: str; reasons: list[str]; risks: list[str]; citations: list[str]
def score_all(unit_sizes: tuple[int, ...] = (300, 1000), scenarios: tuple[str, ...] = ("uri_2021","beryl_2024","helene_2024"),
              force: bool = False) -> list[SiteScore]     # batch; writes site_scores incl. scenario_id='all'
def regulatory_path(kind: str, safety: SafetyResult) -> str
def write_site_scores(scores: list[SiteScore], duck_path: Path = ...) -> int

# siting/tools.py — copilot wrapper (exact contract signature)
def score_site(site_id: str, unit_mw: int, scenario_id: str) -> dict
    # cache hit → site_scores row + card; miss → score_safety + score_grid_value (stress hours) + rank, persist, return asdict(SiteScore)
```

CLI: `uv run python -m siting.candidates`, `uv run python -m siting.rank --unit 1000 --scenario all`.

## Acceptance criteria

1. `build_candidates("TX")` yields ≥ 12 coal sites, exactly 2 `nuclear_existing`, ≥ 5 `dod`
   rows; every row has `county_fips` in `counties` and, for ≥ 80 % of rows, a non-null `bus_id`
   within 40 km.
2. `score_safety` on Comanche Peak and STP returns `safety_score > 0` with S1, S3, S4, S6, S7
   passing (existing licensed sites must not be excluded by our re-implementation — a
   sanity anchor). A synthetic point in downtown Houston (29.76, −95.37) fails S1 with
   `population_downgraded=True` under `proposed_rule_mode=True` and `safety_score == 0` with
   `proposed_rule_mode=False`.
3. Every `safety_flags_json` entry has a non-empty `source` and a numeric `value`; no criterion is
   silently skipped — a missing layer raises `MissingLayerError`, it does not "pass".
4. `score_grid_value` for the same `(site, unit, scenario)` run twice gives identical numbers
   (inherits spec 03 determinism); base and with-unit runs use the same seed (asserted by
   comparing `cause="weather"` trip sets at hour 0, which must be equal).
5. Adding a 1 GW unit never increases `lost_load_mwh` summed over stress hours by more than 1 %
   (a "unit made things worse" result flags a dispatch/scaling bug, not a finding).
6. Batch `score_all()` over Texas completes in < 20 min and writes ≥ 1 row per
   (site, scenario ∈ {3 scenarios + 'all'}, unit ∈ {300, 1000}).
7. Ranking sanity: the top-3 by `combined` for `unit=1000, scenario='all'` all have
   `regulatory_path != 'excluded'` and non-null `bus_id`; the card lists ≥ 1 reason and ≥ 1 risk
   with a citation string.
8. `score_site("coal_retired:XXXX", 1000, "uri_2021")` returns in < 15 s on a cache miss with
   `solver="lightsim"` (< 60 s with pandapower, 6 stress hours) and < 0.5 s on a hit; the
   returned dict round-trips through `json.dumps`.
9. **Break-it probe (must turn red):** replace `add_unit` with a no-op (return the base net
   unchanged). The test asserts `lol_reduction_mwh > 0` for the top-ranked site at Uri and MUST
   FAIL under the mutation — proving grid value is a real intervention, not a constant. Second
   probe: swap the PAD-US layer for an empty GeoDataFrame; the test asserts a known protected-land
   point (Big Bend NP, 29.25, −103.25) fails S6 and MUST FAIL under the mutation.

## Demo hook

Demo beat 4: "30 Texas coal sites ranked" table (site_scores, `scenario='all', unit=1000`),
click #1 → safety card (flags with values/thresholds) → counterfactual replay: Uri with the site
online, the Fort Cavazos/Hood panel stays green, "X MWh of load loss avoided" from
`lol_reduction_mwh`, customer-hours = `Σ_h Δcustomers_out`. Beat 5: copilot answers "why this
site over the one near Houston?" from two `score_site` calls: S1 density values, S5 cooling
water, `congestion_relief_pct`, citing 10 CFR 100 and the proposed §53.530.

## Risks / unknowns

- OR-SAGE numeric thresholds must be read out of ORNL/TM-2012/403 (7.4 MB PDF; WebFetch could not
  parse it) — 30 min task, blocks S3/S5/S9 numbers being citable.
- Layer downloads (NFHL, NHDPlus, 3DEP, PAD-US) are large; Texas clips only, and each has a
  county-level fallback named above. Never let a missing layer pass silently (acceptance 3).
- Grid value is only as good as spec 03's fragility priors; the delta between two runs with
  the same seed is robust to that, but absolute MWh is not — the card shows both the delta and
  the base.
- DC dispatch assumption (pro-rata displacement) ignores unit commitment; a nuclear unit's real
  value in Uri was availability under cold, which we model via the derate table.
- "Tier 1/Tier 2" is pitch vocabulary; use the rule's own §53.530 language on the card.
- Pantex and DoD authorization pathways are legally fuzzy — label with caveats, do not assert.

## Weekend time-box

| Task | Hours |
|---|---|
| Candidates from PUDL + DoD + static CSVs, bus assignment | 2.0 |
| Read OR-SAGE thresholds from the ORNL PDF; layer download/clip (TX) | 2.0 |
| `safety.py` 12 criteria + flags + proposed-rule downgrade | 3.0 |
| `grid_value.py` (add_unit, stress hours, 3 metrics, cache) | 3.0 |
| `rank.py` + regulatory labels + site cards + `score_site` | 1.5 |
| Acceptance tests incl. both break-it probes | 1.5 |
| **Total** | **13 h** (Day 2 morning is the critical path; start candidates + layers Day 1 evening) |
| Stretch: DoWhy/synthetic-control "firm generation near X shortened restoration" from EAGLE-I | +3 h |
