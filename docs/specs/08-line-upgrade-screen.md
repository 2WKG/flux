# 08 — Line Upgrade Screen ("which existing wires to upgrade")

Status: draft · Scope: ONE screen inside the twin; Texas/ERCOT first, PJM as the clean
congestion-attribution reference · Owner: lines team

## Purpose

Answer "which lines first?" for grid-enhancing technologies. For every transmission line in the
twin, estimate (a) the congestion it causes in $/yr, (b) the extra MW a dynamic line rating (DLR)
would unlock given local wind/temperature climatology via IEEE 738, (c) the extra MW
reconductoring with advanced conductors would unlock and what it costs per mile (LBNL REFA /
GridLab), then rank by **MW unlocked per $M**, apply the FERC DLR ANOPR screen, and flag DOE
SPARK eligibility. Persist to `line_upgrade_scores`; expose `top_lines(region, tech, n)` to the
copilot; render as one map layer + one table + one line card.

Modules: `pipelines/congestion.py`, `twin/dlr.py` (IEEE 738), `twin/reconductor.py`,
`pipelines/line_upgrade.py` (ranking + screen + writer), `copilot/tools_lines.py`.

## Inputs

| Input | Source | Notes |
|---|---|---|
| `lines(line_id, from_bus, to_bus, base_kv, r_pu, x_pu, rate_a_mw, length_km, geom_wkb)` | DuckDB (spec 01) | Synthetic ACTIVSg2000 lines. |
| HIFLD transmission lines (archived) | `data/raw/hifld/Electric_Power_Transmission_Lines.*` (DataLumos / Data Rescue archive), Texas clip | Columns used: `VOLTAGE`, `OWNER`, `TYPE` (AC/DC), geometry. Joined to synthetic `lines` by nearest-geometry + kV class (Hausdorff ≤ 5 km, same kV class) to attach `owner` and a real-line "twin of record". Match rate is reported; unmatched lines keep `owner = NULL`. |
| FERC Form 1 conductor data | PUDL `core_ferc1__yearly_transmission_lines_sched422` (**[UNVERIFIED exact table name]** — Form 1 schedule 422 "Transmission Line Statistics": conductor size/material, length, voltage, per utility) | Joined by `(owner, kV, length ± 20 %)` to attach `conductor_material`, `conductor_kcmil`. Fallback when no match: assume ACSR sized by kV class (`138→477 kcmil Hawk`, `230→795 Drake`, `345→2×954 Rail` **[UNVERIFIED — typical Texas practice]**). |
| Congestion (ERCOT) | gridstatus `Ercot`/`ErcotAPI`: verified endpoints `SHADOW_PRICES_DAM_ENDPOINT='/np4-191-cd/dam_shadow_prices'` and `SHADOW_PRICES_SCED_ENDPOINT='/np6-86-cd/shdw_prices_bnd_trns_const'` (SCED binding transmission constraint shadow prices); `get_shadow_prices_dam()` exists; `get_lmp_by_settlement_point()` exists. ERCOT publishes no LMP congestion component — gridstatus notes congestion ≈ LMP − hub/bus average. | 2024 calendar year, `data/raw/gridstatus/ercot_*`. |
| Congestion (PJM, reference) | gridstatus `PJM.get_transmission_constraints_day_ahead_hourly()` (verified method) + LMP fields `congestion_price_rt`, `total_lmp_rt`, `marginal_loss_price_rt` (verified) | PJM monitored-facility names are the tractable ones; used to VALIDATE the constraint→line mapper on one known case (PPL DLR corridor) — not part of the Texas ranking. |
| Weather climatology | `weather_hourly(county_fips, ts, wind_ms, gust_ms, temp_c, …)` for a full year (`data/parquet/weather_hourly_2024/`), plus NREL WIND Toolkit as stretch | Per-line: hourly wind/temp from the counties of the two end buses (line centroid county if available via `geom_wkb`). |
| Costs | LBNL REFA v2 documentation (`refa.lbl.gov`, `REFA_v2_documentation.pdf` — verified exists; per-mile numbers **[UNVERIFIED until read]**); GridLab 2024 "Reconductoring with Advanced Conductors" technical report (verified: reconductoring < half the per-mile cost of new build; industry range $1–8 M/mile depending on voltage) | Stored in `data/raw/costs/refa_costs.yaml` with a `source_page` field per number. |
| DLR cost anchor | PPL: ~$1 M for 18 sensors on ~31 miles of three 230 kV segments (verified from FERC/TD World coverage) → ~$32 k/mile; we use **$40 k/mile** installed + $5 k/mile/yr O&M. | |
| Policy | FERC DLR ANOPR RM24-6 (June 27 2024; verified: wind-forecast ratings required only on lines that are BOTH heavily congested AND in windy areas; the "$500 k/yr" figure is the pitch's reading **[UNVERIFIED]**); DOE SPARK NOFO (March 12 2026, $1.9 B, IIJA; awards $10–250 M; ≥ 50 % non-federal cost share, 25 % for small utilities; priorities: transfer capability, reliability, large-load growth — verified) | |

## Outputs

- DuckDB `line_upgrade_scores(line_id, congestion_usd_yr, dlr_uplift_mw, reconductor_uplift_mw, dlr_cost_usd, reconductor_cost_usd, mw_per_musd, ferc_screen_pass, spark_eligible)` — one row per line.
  - `mw_per_musd` = best of `dlr_uplift_mw / (dlr_cost_usd/1e6)` and `reconductor_uplift_mw / (reconductor_cost_usd/1e6)`; the winning tech is derivable and also stored in the side table below.
- Side table `line_upgrade_detail(line_id, owner, conductor_material, conductor_kcmil, static_rating_mw, aar_rating_mw, dlr_p50_mw, dlr_hours_above_static, best_tech, payback_yr, congestion_method, region)` — not in the shared contract; additive, keeps the contract table narrow.
- `data/parquet/line_upgrade_scores.parquet` for the deck.gl `PathLayer` (color = `mw_per_musd`).
- `TopLine` dicts from `top_lines`.

## Algorithm or Design

### 1. Line inventory (`pipelines/line_upgrade.py::build_inventory`)

Start from `lines` (synthetic). Attach `owner` from HIFLD by geometry match; attach conductor
from Form 1 where owner matches; else kV-class default. Write `line_upgrade_detail` skeleton.
Region = `'ERCOT'` for all Texas lines (`buses.ba_code='ERCO'`); national rows (scale slide only)
carry their BA.

### 2. Congestion attribution (`pipelines/congestion.py`)

**ERCOT (approximate, stated as such):**
1. Pull 2024 SCED binding-constraint shadow prices (`/np6-86-cd/shdw_prices_bnd_trns_const`):
   columns include constraint name, contingency, shadow price ($/MW), limit, and the
   from/to station names **[UNVERIFIED column set — inspect the first pull]**.
2. Constraint → line: parse the constraint name for the two station names + kV; fuzzy-match
   station names to HIFLD substation names (`data/raw/hifld/substations`), get the real line,
   then map to the synthetic `line_id` matched in step 1. Confidence tiers: `exact`,
   `fuzzy≥0.85`, `unmapped`. `congestion_method` records the tier.
3. `congestion_usd_yr(line) = Σ_intervals shadow_price × constraint_limit_mw × (5/60)`
   (shadow price × binding flow × interval hours — the standard "congestion rent" approximation
   **[UNVERIFIED that ERCOT's file gives the binding flow; else use `limit`]**).
4. Unmapped constraint dollars are NOT spread across lines; they are reported as
   `unattributed_usd_yr` in the run summary so the demo can say what fraction was mapped.
5. Where ERCOT constraints do not map at all, fall back to a **twin-derived congestion proxy**:
   hours in the 2024 replay (spec 03 base runs, no outages) with `loading_percent > 90` ×
   a $20/MWh shadow price **[UNVERIFIED constant]**, clearly tagged `congestion_method='twin_proxy'`.

**PJM (clean reference):** `get_transmission_constraints_day_ahead_hourly()` gives monitored
facility + shadow price; facility names are `STATION1-STATION2 kV` and map to HIFLD by name.
Used only for acceptance 4 (PPL corridor), not the Texas ranking.

### 3. DLR uplift (`twin/dlr.py`) — IEEE 738 steady-state

Heat balance (verified form): `q_c + q_r = I²·R(T_c) + q_s` → `I = sqrt((q_c + q_r − q_s) / R(T_c))`.

- `q_c` = max(natural, forced) convection; forced convection per IEEE 738 §4.4.3 (low- and
  high-wind formulas with the wind-direction factor `K_angle`, film temperature properties);
  `q_r = 17.8 · D · ε · [((T_c+273)/100)⁴ − ((T_a+273)/100)⁴]` W/m; `q_s = α · Q_se · sin(θ) · A'`
  with a fixed clear-sky mid-day `Q_se` by season (we do not model cloud cover; the FERC ANOPR
  asks for solar-position + cloud forecasts, so we state this simplification).
- Conductor library `twin/conductors.yaml`: `{name, kcmil, diameter_m, R_ac_25C, R_ac_75C, T_max_C}` for
  Hawk, Drake, Rail (ACSR), and ACCC/ACSS equivalents. Anchor: Drake 795 ACSR ≈ 900 A at 75 °C
  under the classic rating assumptions (0.61 m/s wind, 40 °C ambient — verified vendor spec).
- Ratings per line:
  - `static_rating_mw` = `rate_a_mw` from the case (the twin's own rating).
  - `static_738_a` = ampacity at 0.61 m/s, 40 °C, full sun, `T_max` (calibration point;
    `calib = rate_a_mw / (√3·kV·static_738_a)` scales the 738 model to the case's rating so
    synthetic ratings and physics agree).
  - `aar_rating_mw(h)` = ambient-adjusted: 738 at 0.61 m/s and hourly `temp_c`.
  - `dlr_rating_mw(h)` = 738 at hourly `wind_ms` (capped at 5 m/s, minimum 0.61 m/s, wind angle
    assumed 45° → `K_angle` mid value), hourly `temp_c`, solar by hour-of-day.
  - `dlr_uplift_mw` = P50 over the year of `max(0, dlr_rating_mw(h) − static_rating_mw)`;
    `dlr_hours_above_static` = count of hours with uplift > 5 % (both stored; the card shows the
    distribution). Expected range 10–40 % uplift; a P50 > 60 % triggers a warning (fails acceptance 5).
- `dlr_cost_usd` = `length_mi × $40 k + $60 k` (sensor + integration floor); `dlr_opex_usd_yr = length_mi × $5 k`.

### 4. Reconductoring uplift (`twin/reconductor.py`)

- `reconductor_uplift_mw = static_rating_mw × (m − 1)` with `m` by existing conductor:
  ACSR → ACCC/ACSS-class **1.5–2.0×** (GridLab 2024: "up to double" — verified; we use 1.8 for
  ACSR ≤ 795 kcmil, 1.6 for larger, 1.2 if already ACSS/ACCC, capped by substation/terminal
  equipment at 2.0×).
- `reconductor_cost_usd = length_mi × cost_per_mile(kV)` from `refa_costs.yaml`; placeholder
  values until REFA doc is read: `138 kV $0.9 M/mi, 230 kV $1.3 M/mi, 345 kV $2.0 M/mi`
  **[UNVERIFIED — fill from REFA v2 documentation; industry range $1–8 M/mi is verified]** plus
  15 % for terminal upgrades.
- `payback_yr = cost / max(congestion_usd_yr × relief_share, 1)` with `relief_share =
  min(1, uplift_mw / binding_overload_mw)` where `binding_overload_mw` is the mean exceedance
  when the line binds (from the congestion pull or twin proxy).

### 5. Ranking, screen, flags

- `mw_per_musd = max(dlr_uplift_mw/(dlr_cost/1e6), reconductor_uplift_mw/(reconductor_cost/1e6))`;
  `best_tech = argmax`. Sorted descending within `region`.
- `ferc_screen_pass = (congestion_usd_yr ≥ 500_000) AND (mean annual wind_ms at line ≥ 3.0)`
  — the ANOPR's "heavily congested AND windy" test (verified concept); both numbers are our
  operationalization **[UNVERIFIED thresholds — the ANOPR asked for comment on them]** and live in
  `params.yaml` with a note.
- `spark_eligible = (best_tech in {dlr, reconductor}) AND (reconductor_cost_usd or dlr_cost_usd
  ≥ $10 M when aggregated by owner-corridor) AND region is a US BA` — SPARK awards are $10–250 M
  projects with ≥ 50 % cost share (verified), so single short lines are eligible only as part of
  an owner-level bundle; the flag is computed on the owner's top-N bundle and propagated to
  member lines. Card prints "SPARK: eligible as part of <owner> bundle ($X M, 50 % cost share)".

### 6. Screen (front end contract, one screen)

- Map layer: `lines` geometry colored by `mw_per_musd` quantiles; filters: region, tech,
  `ferc_screen_pass`, `spark_eligible`.
- Regional top-10 table = `top_lines(region, tech, 10)`.
- Line card: static / AAR / DLR P50 ratings, uplift distribution sparkline, DLR vs reconductor
  cost/uplift/payback, congestion $ and method tier, owner, conductor, screens, and the twin
  hook: "what does losing this line cascade into" → spec 03 `run_cascade([line_id], …)`.

## Interfaces

```python
# pipelines/congestion.py
def pull_ercot_shadow_prices(year: int = 2024, raw_dir: Path = Path("data/raw/gridstatus")) -> pandas.DataFrame
def pull_pjm_constraints(year: int = 2024, raw_dir: Path = ...) -> pandas.DataFrame
def map_constraints_to_lines(constraints: pandas.DataFrame, region: str,
                             hifld_subs: geopandas.GeoDataFrame, line_match: pandas.DataFrame) -> pandas.DataFrame
    # columns: constraint_name, line_id | None, method in {exact, fuzzy, unmapped}, score
def congestion_usd_by_line(mapped: pandas.DataFrame) -> tuple[pandas.Series, float]   # (usd_yr by line_id, unattributed_usd_yr)
def twin_proxy_congestion(duck_path: Path, usd_per_mwh: float = 20.0) -> pandas.Series

# twin/dlr.py
@dataclass(frozen=True)
class Conductor: name: str; kcmil: int; diameter_m: float; r_ac_25c_ohm_m: float; r_ac_75c_ohm_m: float; t_max_c: float; emissivity: float = 0.8; absorptivity: float = 0.8
def ieee738_ampacity_a(cond: Conductor, wind_ms: float, temp_amb_c: float, t_cond_c: float,
                       wind_angle_deg: float = 45.0, solar_w_m2: float = 1000.0, elevation_m: float = 300.0) -> float
def hourly_ratings_mw(line_id: str, cond: Conductor, weather: pandas.DataFrame, base_kv: float,
                      rate_a_mw: float) -> pandas.DataFrame   # columns ts, static_mw, aar_mw, dlr_mw
def dlr_summary(ratings: pandas.DataFrame) -> dict   # dlr_uplift_mw (P50), p10, p90, hours_above_static
def dlr_cost_usd(length_km: float) -> float

# twin/reconductor.py
def reconductor_multiplier(material: str, kcmil: int | None) -> float
def reconductor_uplift_mw(rate_a_mw: float, material: str, kcmil: int | None) -> float
def reconductor_cost_usd(length_km: float, base_kv: float, costs: dict) -> float

# pipelines/line_upgrade.py
def build_inventory(duck_path: Path = ..., hifld_dir: Path = ..., pudl_dir: Path = ...) -> pandas.DataFrame
def score_lines(region: str = "ERCOT", year: int = 2024, write: bool = True) -> pandas.DataFrame   # -> line_upgrade_scores + detail
def ferc_screen(congestion_usd_yr: float, mean_wind_ms: float, usd_threshold: float = 500_000.0, wind_threshold_ms: float = 3.0) -> bool
def spark_flags(scores: pandas.DataFrame, min_bundle_usd: float = 10e6) -> pandas.Series

# copilot/tools_lines.py — exact contract signature
def top_lines(region: str, tech: Literal["dlr","reconductor","any"], n: int = 10) -> list[dict]
    # region in {"ERCOT","PJM",...} or a Texas county name/FIPS (filters by end-bus county);
    # tech filters best_tech (any = no filter); returns rows of line_upgrade_scores ⋈ detail sorted by mw_per_musd desc
```

CLI: `uv run python -m pipelines.congestion --iso ercot --year 2024`, `uv run python -m pipelines.line_upgrade --region ERCOT`.

## Acceptance criteria

1. `build_inventory()` covers every `lines` row; HIFLD owner match rate for ≥ 230 kV lines is
   reported and ≥ 50 % (synthetic vs real geometry — a lower rate is allowed but printed, never hidden).
2. `ieee738_ampacity_a(Drake, 0.61, 40, 75)` returns 900 A ± 5 % (classic Drake anchor); ampacity
   is monotone increasing in wind speed and decreasing in ambient temperature over a 0.5–5 m/s,
   −10–45 °C sweep.
3. For every line, `aar_mw` and `dlr_mw` ≥ `static_mw` at the calibration conditions, and
   `dlr_uplift_mw` P50 is within 5–50 % of `static_rating_mw` for ≥ 90 % of lines (values outside
   are listed, not silently clipped).
4. PJM reference: the PPL 230 kV corridor where DLR cut congestion from ~$66 M to ~$1.6 M
   **[UNVERIFIED corridor name — pitch figure]** appears in `top_lines("PJM","dlr",10)` on 2023
   data (i.e., the year before its DLR went live) OR the test documents why the mapper missed it.
   This is the "our model would have flagged it" demo line; if it cannot be reproduced the demo
   line is cut, not faked.
5. ERCOT congestion attribution: ≥ 40 % of 2024 SCED shadow-price dollars map to a `line_id` at
   `exact` or `fuzzy` tier; the unattributed remainder is printed in the run summary and shown
   on the screen's footer.
6. `line_upgrade_scores` has no NULL `mw_per_musd` for rated lines; `ferc_screen_pass` is true
   for at least one and fewer than 20 % of ERCOT lines; `spark_eligible` lines all belong to an
   owner bundle ≥ $10 M.
7. `top_lines("ERCOT","any",10)` returns 10 rows sorted by `mw_per_musd` desc in < 200 ms (pure
   DuckDB read); `tech="dlr"` returns only rows with `best_tech="dlr"`.
8. Every cost/threshold constant in `params.yaml`/`refa_costs.yaml` carries a `source` string;
   a constant without a source fails the params-loading test.
9. **Break-it probe (must turn red):** replace `ieee738_ampacity_a` with `lambda *a, **k: 900.0`
   (wind-blind). The test asserts that a windy line (mean wind ≥ 6 m/s) has strictly higher
   `dlr_uplift_mw` than a calm line (≤ 2 m/s) with the same conductor and rating, and MUST FAIL
   under the mutation. Second probe: set `usd_threshold = 0` in `ferc_screen`; the test asserts
   `ferc_screen_pass` count < 20 % and MUST FAIL.

## Demo hook

Inside the twin, after the cascade beat: "the twin also tells you which existing wires to
upgrade." Toggle the line-upgrade layer over Texas; lines re-color by MW per $M; top-10 table for
ERCOT; click #1 → card with DLR vs reconductor; flip the FERC screen ("the rule is stalled, nobody
has run it — we did") and the SPARK flag ("$1.9 B, selections were due August 2026 — this is the
lead list"). Copilot: `top_lines("ERCOT","any",10)` → "the ten cheapest MW of capacity in ERCOT
and which technology gets them", citing the ANOPR and SPARK NOFO. National map colored by
`mw_per_musd` is the scale slide only if the national inventory exists by Day 2 evening.

## Risks / unknowns

- Constraint→line mapping is the known hard part (pitch says so). ERCOT is approximate by
  design; the `congestion_method` tier and the unattributed fraction are shown, never hidden.
- gridstatus ERCOT API needs an ERCOT public API key (`ERCOT_API_USERNAME/PASSWORD`
  **[UNVERIFIED env names — check gridstatus `ErcotAPI` docs]**); pull on Day 1 and cache raw.
- Synthetic lines vs real HIFLD geometry: the owner/conductor join is heuristic; the card labels
  the twin line and its "real twin of record" separately.
- REFA per-mile costs and the ANOPR's exact thresholds are placeholders until the documents are
  read (both < 30 min tasks, listed in the time-box).
- IEEE 738 simplifications (fixed solar, 45° wind angle, no cloud cover) bias DLR uplift upward
  at night/overcast; P50 over a year and the 60 % sanity cap bound the damage.
- Form 1 schedule 422 coverage is IOU-only; Texas munis/co-ops (Austin Energy, CPS, LCRA) fall
  to the kV-class default — stated on the card.

## Weekend time-box

| Task | Hours |
|---|---|
| Inventory: HIFLD clip + geometry match + Form 1 join / defaults | 2.0 |
| ERCOT shadow-price pull + constraint→line mapper + $ per line + twin proxy fallback | 3.0 |
| IEEE 738 module + conductor library + Drake calibration + hourly ratings over 2024 weather | 2.5 |
| Reconductoring uplift + REFA costs (read doc, fill yaml) | 1.0 |
| Ranking, FERC screen (read ANOPR thresholds), SPARK bundle flag, writer | 1.5 |
| `top_lines` tool + parquet for the map | 0.5 |
| Acceptance tests incl. both break-it probes | 1.5 |
| **Total** | **12 h** (Day 1 afternoon congestion pull can run in the background; rest is Day 2) |
| Stretch: PJM PPL synthetic-control DLR effect; national inventory for the scale slide | +3 h |
