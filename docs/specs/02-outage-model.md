# 02 — County outage model (LightGBM on EAGLE-I, Layer 3)

Status: build spec, weekend scope. Texas first; the model is county-generic so P1 national is
"add rows", not "add code". Depends on `01-data-ingest.md` tables: `eaglei_outages`,
`county_customers` (helper), `weather_hourly`, `storm_events`, `hazard_static`, `nri_hazards`
(helper), `counties`, `scenarios`, `nws_alerts` (helper), optional `utility_reliability`.

## Purpose

Given a county and a 6-hour window, predict (a) the probability that a material outage occurs
and (b) the expected fraction of customers out, so the map can light up counties before the
storm and the copilot can answer `predict_outage(county, horizon)` with a number, a driver, and
a calibration statement. Validated by replaying held-out storms (Uri 2021, Beryl 2024, Helene
2024) against what EAGLE-I recorded. The physics cascade (spec 03) consumes the per-county
probabilities as line-failure priors; this spec does not do power flow.

## Inputs

| Table | Columns used | Notes |
|---|---|---|
| `eaglei_outages` | `county_fips, ts, customers_out` | 15-min; label source |
| `county_customers` | `county_fips, total_customers` | from `MCC.csv` (2022 model) / 2024 `total_customers` |
| `weather_hourly` | `wind_ms, gust_ms, temp_c, ice_mm, precip_mm` | HRRR county-hour means (or ISD fallback) |
| `storm_events` | `ts_begin, ts_end, type, magnitude` | NOAA Storm Events, county-expanded |
| `hazard_static` | `nri_score, wildfire_hazard, seismic_pga` | static per county |
| `nri_hazards` | `WFIR_RISKS, ISTM_RISKS, SWND_RISKS, HRCN_RISKS, WNTW_RISKS` | static per county |
| `counties` | `pop, state, geom_wkb` (→ centroid lat, coastal flag) | |
| `utility_reliability` + `utility_county` | `saidi_wo_med` customer-weighted per county-year | P1 only; NULL-safe |
| `nws_alerts` | `event, severity, onset, ends, county_fips_list` | `forecast_72h` only |
| `scenarios` | `scenario_id, ts_start, ts_end` | defines replay windows |

Training coverage: P0 = Texas, 2021 + 2024 EAGLE-I (≈ 254 counties × 2 years × 1,460 windows ≈
740k rows before filtering). P1 = Texas 2018–2025 and the Helene states (FL, GA, NC, SC, TN, VA)
2018–2025, which is what makes Helene a legitimate hold-out.

## Outputs

1. `data/parquet/outage_features.parquet` — one row per `(county_fips, window_start)`; schema in §Algorithm.
2. `models/outage/artifacts/lgbm_pout.txt`, `lgbm_frac.txt` (LightGBM native), `calibrator.pkl` (isotonic), `feature_list.json`, `metrics.json`, `train_manifest.json` (git sha, data sha256s, split definition).
3. Table `outage_predictions(scenario_id, county_fips, ts, p_out, customers_at_risk, driver)` — `ts` = window start (6-h aligned UTC); `driver ∈ {ice, wind, heat, wildfire, flood, other}`; `customers_at_risk = frac_hat × total_customers`.
4. Table `outage_eval(scenario_id, county_fips, ts, y_out, frac_actual, p_out, frac_hat)` (helper) so the demo can draw predicted-vs-actual side by side.
5. Tool `predict_outage` in `copilot/tools/predict_outage.py` (signature in §Interfaces) backed by the same artifacts.

## Algorithm or Design

### Windows and labels (`models/outage/labels.py`)

- Window = 6 h, aligned to 00/06/12/18 UTC. For each county `c` and window `w`:
  - `max_out(c,w)` = max `customers_out` over the 15-min samples in `w` (EAGLE-I reports a level, not events; max is robust to the reporting gaps).
  - `frac_out(c,w) = max_out / total_customers(c)`, clipped to [0, 1]. Counties with `total_customers < 500` or NULL are dropped (tiny co-ops make the fraction noisy).
  - Binary label `y_out(c,w) = frac_out ≥ 0.05` ("material outage", ≥5% of customers). Secondary threshold 0.20 ("severe") is stored for the copilot's phrasing but not trained separately.
  - Rows where the county has **no EAGLE-I sample at all** in the window are labelled NULL and excluded (coverage gap ≠ zero outage). `coverage_history.csv` state coverage < 60% for the year → whole state-year excluded.
- Horizon: features are built from data **up to the window start** (nowcast, h=0) and, for the forecast path, from HRRR forecast fields valid in the window. Training uses HRRR analysis (`f00`) values in the window itself as a stand-in for "a perfect 6-h forecast"; the honest caveat is stated in `metrics.json.notes` and the demo.

### Feature table (`models/outage/features.py` → `outage_features`)

| Column | Definition |
|---|---|
| `county_fips`, `window_start` | keys |
| `y_out`, `frac_out`, `total_customers` | labels / denominators (NULL for forecast rows) |
| `wind_max`, `wind_mean`, `gust_max` | over the 6 h window from `weather_hourly` |
| `gust_max_24h`, `gust_max_prev6` | rolling max over the prior 24 h / previous window |
| `temp_min`, `temp_mean`, `temp_min_48h` | °C |
| `hours_below_0`, `hours_below_m10` | count in the prior 48 h |
| `ice_sum_6h`, `ice_sum_48h` | mm freezing-rain accumulation |
| `precip_sum_6h`, `precip_sum_72h` | mm |
| `heat_index_max` | from `temp_c` + assumed RH 50% when RH absent (heat driver) |
| `storm_event_any`, `storm_event_type_*` | one-hot for `Winter Storm, Ice Storm, Extreme Cold/Wind Chill, High Wind, Thunderstorm Wind, Tornado, Hurricane, Tropical Storm, Flash Flood, Wildfire, Excessive Heat` overlapping the window ± 6 h |
| `storm_magnitude_max` | knots for wind types, else NULL |
| `nri_score, wildfire_hazard, seismic_pga, WFIR_RISKS, ISTM_RISKS, SWND_RISKS, HRCN_RISKS, WNTW_RISKS` | static |
| `pop_log`, `customers_log`, `cust_density` | log10 pop, log10 customers, customers / county area km² |
| `coastal` | county polygon touches the Gulf (`ST_DWithin` 5 km of coastline `[derived from TIGER coastal flag]`) |
| `lat, lon` | county centroid |
| `month, hour_utc, dow` | seasonality (month as categorical) |
| `frac_out_prev6`, `frac_out_prev24_max` | autoregressive terms — **used only in the nowcast model**, zeroed in the forecast model (see two heads below) |
| `saidi_wo_med_trend` | P1; NULL → LightGBM native NaN handling |
| `ba_code` | categorical |

Two feature sets are produced from the same table: `FEATURES_NOWCAST` (all) and `FEATURES_FORECAST` (drops `frac_out_prev*` and `storm_event_*`, because Storm Events is retrospective).

### Models (`models/outage/train.py`)

- **Head A — `p_out`**: `lightgbm.LGBMClassifier(objective='binary', n_estimators=2000, learning_rate=0.03, num_leaves=63, min_child_samples=100, subsample=0.8, colsample_bytree=0.8, reg_lambda=5, scale_pos_weight=auto, early_stopping_rounds=100)`; categorical `month, ba_code`.
- **Head B — `frac_out | y_out=1`**: `LGBMRegressor(objective='tweedie', tweedie_variance_power=1.3, …)` trained only on positive rows; prediction `frac_hat = p_out × E[frac | out]`.
- **Calibration**: isotonic regression on the validation fold (2023 Texas if P1; else a random 15% of training windows stratified by month — flagged as weaker in `metrics.json`).
- Trained twice: `nowcast` and `forecast` feature sets, artifacts suffixed `_nowcast` / `_forecast`. The demo replay and `predict_outage(horizon>0)` use `forecast`; the live "what is happening now" layer uses `nowcast`.
- Seeds fixed; training on P0 data is < 3 min on a laptop.

### Split (`models/outage/split.py`)

Held-out windows — never in train or calibration — defined as the scenario windows ± 3 days:
- `uri_2021`: 2021-02-10 .. 2021-02-23, all Texas counties.
- `beryl_2024`: 2024-07-04 .. 2024-07-14, Texas counties.
- `helene_2024`: 2024-09-22 .. 2024-10-03, FL/GA/NC/SC/TN/VA (P1) — with P0 data (Texas only) this hold-out is empty and is reported as `not_evaluated`.
Additionally, all windows from **2024-07-01 onward in Texas** are excluded from training for Beryl to avoid leakage via the autoregressive features; the training set is therefore 2021 (minus Uri window) + 2024-01-01..2024-06-30 (P0) or 2018–2023 + 2024 H1 + 2025 (P1).

### Metrics (`models/outage/evaluate.py` → `metrics.json`)

Per hold-out scenario and overall:
- `auc` (ROC), `pr_auc`, `brier`, `ece` (10-bin expected calibration error), reliability-diagram bins.
- `mae_customers` = mean |customers_at_risk − max_out| over county-windows; `mae_customers_top50` on the 50 counties with the largest actual outage.
- `peak_statewide_err` = |Σ_c customers_at_risk − Σ_c max_out| / Σ_c max_out at the worst window.
- `hit_rate_top20`: of the 20 counties with the highest actual `frac_out` at the peak window, how many are in the top 20 predicted.
- Baseline comparison (same file): climatology (`p = county base rate by month`) and the heuristic model below.

### `predict_outage` tool (`copilot/tools/predict_outage.py`; schema registered in spec 05 `copilot/tools/schemas.py`)

1. Inputs exactly as spec 05 declares: `county_fips: str` (the LLM resolves names via `sql` over `counties` first), `scenario_id ∈ {uri_2021, beryl_2024, helene_2024, forecast_72h}`, `horizon_h: int = 72` (rounded up to a 6-h multiple, max 72).
2. Windows = every 6-h window in `[scenario.ts_start, ts_start + horizon_h]` for historical scenarios, `[now, now + horizon_h]` for `forecast_72h`.
3. If `outage_predictions` already has the rows → serve them (cheap, deterministic, citable). Else build the feature rows via `features.build_rows(con, county_fips, window_starts, feature_set)` and score with the `forecast` head.
4. `driver` = argmax of SHAP contribution at the peak window grouped into {ice: ice_*, hours_below_*, temp_*, ISTM; wind: wind_*, gust_*, SWND, HRCN; heat: heat_index_max; wildfire: wildfire_hazard, WFIR; flood: precip_*; other} using `lightgbm.Booster.predict(pred_contrib=True)`; `storm_event_*` contributions weighted × 0.5.
5. Returns spec 05's shape `{county_fips, county_name, scenario_id, horizon_h, peak_p_out, peak_ts, customers_at_risk, driver, series:[{ts, p_out, customers_at_risk}]}` (series ≤ 24 points) **plus** `top_features:[{name, value, contribution}]` (3), `calibration_note`, `model_version`, `model_kind: 'lightgbm'|'heuristic'`. The LLM narrates; it never computes.

### `forecast_72h` path (`models/outage/forecast.py`)

1. `pipelines.hrrr.load_hrrr_forecast(run=latest, horizon_h=48)` fills `weather_hourly` for `forecast_72h` with `fxx=1..48` (hours 49–72 copy hour 48 and set a `stale` flag in a helper table `forecast_meta`).
2. `pipelines.nws.snapshot_alerts("TX")` → `alerts_to_features(ts)` produces per-county flags `ice_flag, wind_flag, fire_flag, heat_flag`; these **replace** the missing `storm_event_*` one-hots in the forecast feature set (mapping: Winter Storm Warning/Ice Storm Warning → `storm_event_type_Winter Storm`; High Wind Warning/Hurricane Warning/Tropical Storm Warning → `High Wind`/`Hurricane`; Red Flag Warning → `Wildfire`; Excessive Heat Warning → `Excessive Heat`). A version of the forecast head is trained with these flags derived from Storm Events (`storm_event_*` mapped to the same four flags) so train/serve features match.
3. `predict_scenario(con, "forecast_72h")` writes 12 windows × 254 counties into `outage_predictions`; the web map reads `p_out` per window; the copilot's "top-N counties at risk in the next 72 h" is `SELECT … ORDER BY customers_at_risk DESC` over that table.
4. Refreshed by `uv run python -m models.outage.forecast --refresh` (cron-able; ~2 min).

### Fallback heuristic model (`models/outage/heuristic.py`) — used if EAGLE-I is late or the LightGBM AUC on Uri < 0.70

A transparent, hand-tuned logistic on the same features so the map is never empty and every screen still works:

```
logit(p) = -4.0
         + 1.6 * clip((gust_max - 15) / 10, 0, 2)          # wind: 15 m/s onset, saturates ~35 m/s
         + 2.2 * clip(ice_sum_48h / 5, 0, 2)                # 5 mm freezing rain ≈ +2.2
         + 1.2 * clip((0 - temp_min_48h) / 10, 0, 2)        # deep cold (Uri-type generation loss proxy)
         + 0.8 * clip((heat_index_max - 40) / 5, 0, 1)
         + 0.6 * clip(precip_sum_72h / 100, 0, 1.5)
         + 0.5 * (nri_score / 100) + 0.4 * (WFIR_RISKS / 100)
         + 1.0 * storm_event_any
frac_hat = p * (0.08 + 0.35 * clip(ice_sum_48h / 10, 0, 1) + 0.25 * clip((gust_max - 25) / 15, 0, 1))
```
`driver` = the term with the largest contribution. Coefficients are constants in `heuristic.py::COEF` and are the *only* thing a team member tunes; the same `evaluate.py` scores it so the slide can show "learned vs heuristic" honestly. If EAGLE-I never arrives, the heuristic is `authoritative` and the slide says so.

## Interfaces (exact function signatures)

```python
# models/outage/labels.py
def build_labels(con, states: tuple[str, ...], years: list[int], window_h: int = 6,
                 material_frac: float = 0.05, min_customers: int = 500) -> pd.DataFrame: ...
# → county_fips, window_start, max_out, total_customers, frac_out, y_out

# models/outage/features.py
FEATURES_NOWCAST: list[str]; FEATURES_FORECAST: list[str]
def build_features(con, states: tuple[str, ...], ts_start: datetime, ts_end: datetime,
                   window_h: int = 6, include_labels: bool = True,
                   out_path: str = "data/parquet/outage_features.parquet") -> pd.DataFrame: ...
def build_rows(con, county_fips: str, window_starts: list[datetime],
               feature_set: Literal["nowcast","forecast"], scenario_id: str) -> pd.DataFrame: ...

# models/outage/split.py
HOLDOUT_WINDOWS: dict[str, tuple[datetime, datetime, tuple[str, ...]]]  # scenario_id -> (start, end, states)
def split(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, pd.DataFrame]]: ...  # train, calib, holdouts

# models/outage/train.py
@dataclass
class OutageModel:
    clf: lightgbm.Booster; reg: lightgbm.Booster; calibrator: sklearn.isotonic.IsotonicRegression
    feature_set: Literal["nowcast","forecast"]; features: list[str]; version: str
    def predict(self, X: pd.DataFrame) -> pd.DataFrame: ...   # p_out, frac_hat, driver
    def contrib(self, X: pd.DataFrame) -> pd.DataFrame: ...    # SHAP-style per-feature contributions
def train(features_path: str, feature_set: Literal["nowcast","forecast"], seed: int = 7,
          out_dir: str = "models/outage/artifacts") -> OutageModel: ...
def load_model(feature_set: Literal["nowcast","forecast"], out_dir: str = "models/outage/artifacts") -> OutageModel: ...

# models/outage/evaluate.py
def evaluate(model: OutageModel, holdouts: dict[str, pd.DataFrame],
             baselines: dict[str, Callable[[pd.DataFrame], np.ndarray]]) -> dict: ...  # metrics.json content
def write_eval_table(con, scenario_id: str, df: pd.DataFrame) -> int: ...          # outage_eval

# models/outage/predict.py
def predict_scenario(con, scenario_id: str, model: OutageModel | None = None,
                     states: tuple[str, ...] = ("TX",)) -> int: ...                 # rows written to outage_predictions
def driver_of(contrib_row: pd.Series) -> str: ...

# models/outage/forecast.py
def refresh_forecast(con, area: str = "TX", horizon_h: int = 72) -> int: ...

# models/outage/heuristic.py
COEF: dict[str, float]
class HeuristicOutageModel(OutageModel):   # same .predict/.contrib contract, no boosters
    ...

# copilot/tools/predict_outage.py  (signature fixed by spec 05's tool schema)
def predict_outage(county_fips: str, scenario_id: str, horizon_h: int = 72) -> dict:
    """Returns {county_fips, county_name, scenario_id, horizon_h, peak_p_out, peak_ts, customers_at_risk,
    driver, series: list[{ts, p_out, customers_at_risk}], top_features: list[{name, value, contribution}],
    calibration_note, model_version, model_kind: 'lightgbm'|'heuristic'}"""
```

CLI: `uv run python -m models.outage.features --states TX --years 2021 2024`;
`uv run python -m models.outage.train --feature-set forecast`;
`uv run python -m models.outage.evaluate`; `uv run python -m models.outage.predict --scenario uri_2021`;
`uv run python -m models.outage.forecast --refresh`.

## Acceptance criteria

1. `outage_features.parquet` for TX 2021+2024 has ≥ 600k rows, ≤ 2% NULL in every weather column inside scenario windows, and no `frac_out > 1`.
2. Positive rate of `y_out` over TX 2021 is between 0.5% and 5%; during `uri_2021` ≥ 40% of Texas county-windows at 2021-02-15 12Z..18Z are positive (sanity anchor to the real event).
3. Leakage check: no `window_start` inside any `HOLDOUT_WINDOWS` range appears in the train or calibration frames (asserted in `split()`; test `models/outage/tests/test_split.py`).
4. `train(feature_set="forecast")` finishes in < 5 min on P0 data and writes all artifacts + `train_manifest.json` with data hashes.
5. Uri hold-out (forecast head): `auc ≥ 0.80`, `brier ≤ 0.12`, `ece ≤ 0.06`, `hit_rate_top20 ≥ 10/20`, `peak_statewide_err ≤ 0.40`. If AUC < 0.70 the build flips `model_kind` to `heuristic` and says so in `metrics.json`.
6. Beryl hold-out: `auc ≥ 0.75` (wind-driven, coastal; different physics from Uri — this is the "it generalises across drivers" number).
7. Helene: `not_evaluated` under P0 with an explicit reason; under P1 `auc ≥ 0.75`.
8. Both heads beat climatology on Brier for every evaluated hold-out; metrics for the heuristic are in the same `metrics.json`.
9. `outage_predictions` for `uri_2021` has 254 counties × 28 windows (7 days × 4) and `driver='ice'` or `'other'` (cold) for ≥ 70% of positive-predicted county-windows on 2021-02-15/16.
10. `predict_outage("48453", "uri_2021", 72)` (Travis) returns in < 300 ms from the table, and `predict_outage("48453", "forecast_72h", 24)` in < 2 s including feature build; both return the full spec-05 shape, `series` ≤ 24 points, and `top_features` of length 3.
11. `refresh_forecast` writes 12 windows × 254 counties and the NWS flag mapping is unit-tested against a fixture alert GeoJSON (`models/outage/tests/fixtures/alerts_TX.geojson`).
12. `outage_eval` for `uri_2021` renders predicted-vs-actual choropleths in `web/` with a per-county residual; the demo screenshot is checked into `docs/specs/assets/uri_pred_vs_actual.png` `[produced during the weekend, not now]`.

## Demo hook

Demo step 2: "Load the Winter Storm Uri weather." The map animates `outage_predictions.p_out` across the 28 Uri windows; a toggle flips to `outage_eval.frac_actual` (EAGLE-I) and a scorecard shows `AUC 0.8x · Brier 0.0x · top-20 hit 1x/20` from `metrics.json`. The copilot's `predict_outage("48201", "uri_2021", 72)` (Harris) cites the peak window, driver (ice/cold), and the calibration note. Step 3 hands `p_out` to the cascade as line-failure priors.

## Risks / unknowns

- **EAGLE-I coverage gaps** in 2021 Texas (some co-ops not scraped) depress labels; the NULL-not-zero rule and `coverage_history.csv` filter mitigate, but `mae_customers` will be biased low. State it.
- **Uri was a generation-shortfall + load-shed event, not only wires-down**: a weather→wires model under-predicts Austin/Houston rolling blackouts. `temp_min_48h`/`hours_below_m10` act as proxies; the cascade spec's generation-outage scenario is the physically honest layer. The demo should say "the model learns what Uri looked like on the ground, the twin explains why".
- **HRRR analysis in training vs forecast at serve time** — optimistic skill. Mitigation: report Uri metrics also with HRRR `f06..f12` fields if time permits `[P1]`.
- **Class imbalance + spatial autocorrelation** inflate AUC; `hit_rate_top20` and `peak_statewide_err` are the honest numbers — lead with them.
- Storm Events zone→county expansion smears winter-storm rows across whole zones (many counties) — fine for training, noisy as a "driver" explanation; the driver logic prefers weather features over the one-hots by weighting `storm_event_*` contributions × 0.5.
- If HRRR is late, ISD interpolation (spec 01 S7b) drops `ice_mm` quality; the `ice` driver degrades to "cold".

## Weekend time-box (hours)

| Task | Hours |
|---|---|
| labels + features (DuckDB SQL, window aggregation) | 2.5 |
| split + train (two heads, calibration) | 1.5 |
| evaluate + metrics.json + `outage_eval` | 1.5 |
| `predict_scenario` for uri/beryl + `outage_predictions` | 1.0 |
| `predict_outage` tool + driver attribution | 1.0 |
| `forecast_72h` refresh (HRRR forecast + NWS mapping) | 1.5 |
| heuristic model + comparison row | 1.0 |
| **Total** | **10** (P1 national/Helene +3) |
