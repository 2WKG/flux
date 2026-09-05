# 03 — Cascade Simulation (`twin/`)

Status: draft · Scope: Texas-first (ACTIVSg2000 / ERCOT) · Owner: twin team

## Purpose

Turn the synthetic Texas grid into a runnable physics twin and answer, for any storm scenario
and hour: **which elements fail, what the failures cascade into, how much load is lost, which
counties go dark, how many customers are affected, and which critical loads (DoD, hospital,
water) lose supply.** This is the do-operator for the whole product: the siting engine (spec 04)
and the copilot's `run_cascade` tool both call it. Everything here is deterministic, seeded, and
bounded in wall-clock time so it can run live on stage.

Two modules:

- `twin/build.py` — ACTIVSg2000 → pandapower net, hourly load scaling, weather → per-line failure
  probabilities.
- `twin/cascade.py` — the drop → DC power flow → trip-overloads → repeat loop, islanding, lost
  load, county/customer/critical-load attribution, and the `cascade_runs` writer.

Grid2Op "operator agent" remediation is an explicit stretch (see end), not on the weekend path.

## Inputs

| Input | Where | Notes |
|---|---|---|
| ACTIVSg2000 case | `case_ACTIVSg2000.m` bundled in the pip package `matpower` under `matpower/data/` (verified by the coordinator; copy to `data/raw/activsg2000/case_ACTIVSg2000.m` so the raw dir is the source of record). Verified import: `from_mpc(path, f_hz=60)` → **2000 buses / 2359 lines / 0 trafos (every branch imports as a line) / 544 gens / 1125 loads / 67 109 MW load**; base-case `pp.rundcpp` = **0.84 s/solve, max line loading 79.9 %**. | Bus lat/lon are NOT in the `.m`; they come from the TAMU PowerWorld `.AUX` (`data/raw/activsg2000/…/Texas2000_June2016.AUX`, `DATA (Bus, [… Latitude, Longitude …])` block), which spec 01 ingests into `buses.lon/lat`. This spec reads geography ONLY from `buses`. |
| `buses`, `lines`, `gens`, `loads` | `data/duck/grid.duckdb` | Produced by spec 01 (ingest). `lines.rate_a_mw` is the MATPOWER `rateA`; `buses.county_fips` is the bus↔county join. |
| `ba_load_hourly(ba_code, ts, demand_mw)` | DuckDB | EIA-930 hourly demand; Texas rows have `ba_code = 'ERCO'`. |
| `weather_hourly(county_fips, ts, wind_ms, gust_ms, temp_c, ice_mm, precip_mm)` | DuckDB | HRRR-derived county-hour weather for each scenario window. |
| `counties(county_fips, name, state, pop, geom_wkb)` | DuckDB | `pop` → customers via a fixed 2.5 persons/customer ratio (documented constant, overridable). |
| `critical_loads(cl_id, kind, name, lon, lat, bus_id, county_fips)` | DuckDB | `bus_id` = nearest bus of ≥ 115 kV within the same county, assigned by spec 01. |
| `scenarios(scenario_id, name, kind, ts_start, ts_end)` | DuckDB | `uri_2021` (2021-02-13..2021-02-20), `beryl_2024`, `helene_2024`, `forecast_72h`. |

## Outputs

- `twin/net_cache/activsg2000.p` — pickled base pandapower net (`pp.to_pickle`), built once; hash of
  the source `.m` file stored alongside so a changed case invalidates the cache.
- DuckDB `cascade_runs(run_id, scenario_id, hour, tripped_element_ids_json, lost_load_mw,
  counties_dark_json, critical_loads_lost_json)` — one row per `(run, hour)`.
  - `tripped_element_ids_json`: ordered list of `{"element_id": str, "kind": "line"|"trafo"|"gen"|"bus", "stage": int, "cause": "weather"|"overload"|"island"|"forced"}`.
  - `counties_dark_json`: list of `{"county_fips": str, "lost_mw": float, "customers_out": int, "fraction_dark": float}`.
  - `critical_loads_lost_json`: list of `{"cl_id": str, "kind": str, "name": str, "hour_lost": int}`.
- `data/parquet/cascade_runs/<run_id>.parquet` — same rows, for the front end's playback layer.
- In-memory `CascadeResult` dataclass (below) returned to callers (siting engine, copilot).

## Algorithm or Design

### `twin/build.py`

1. **Load the case.** pandapower **3.5.3**; the importer is
   `from pandapower.converter.matpower import from_mpc` (there is NO `pandapower.converter.from_mpc`
   — verified) and it needs the `matpowercaseframes` package (installed). Call
   `from_mpc(path, f_hz=60)`; the default `f_hz` is 50.
2. **Element identity.** After conversion, stamp `net.line["element_id"]`, `net.gen["element_id"]`,
   `net.bus["element_id"]` with the contract IDs from DuckDB (`line_id`, `gen_id`, `bus_id`).
   Matching is by MATPOWER row order (`from_mpc` preserves branch order; on this case ALL 2359
   branches import as `line` rows and `net.trafo` is empty — verified — so transformer branches
   are lines with the converter's derived impedance; the loop still handles `net.trafo`
   generically for other cases). Cache metadata stores the counts (2000/2359/0/544/1125) and the
   build fails loudly if they differ.
   **[UNVERIFIED: from_mpc's exact rateA→`max_i_ka` conversion (`rateA / (√3 · vn_kv)`) and
   whether `rateA == 0` yields 0 or a large sentinel. Acceptance test 3 pins this; step 3 overwrites
   it anyway.]**
3. **Ratings.** Overwrite the converter's value: for every line set
   `max_i_ka = rate_a_mw / (sqrt(3) * vn_kv)` from `lines.rate_a_mw`; for trafos set
   `sn_mva = rate_a_mw`. Lines with `rate_a_mw <= 0` get `max_i_ka = 9999` and are tagged
   `unrated=True` (never tripped on overload; counted in acceptance test 3).
4. **Hourly load scaling.** `scale_loads(net, scenario_id, hour)`: read
   `ba_load_hourly` for `ba_code='ERCO'` at `ts = ts_start + hour`; compute
   `k = demand_mw / sum(net.load.p_mw)` using the base-case total, and set
   `net.load.p_mw = p_nominal * k`. Generators are scaled proportionally to `pmax_mw` so the
   slack does not absorb the whole delta (DC PF has no losses, so total gen = total load).
   Missing hour → raise `MissingLoadHourError` (no silent fallback to base case).
5. **Weather → per-element failure probability.** `line_failure_probs(net, scenario_id, hour, kv_thresholds)`:
   - Each line's exposure = weather of the county of `from_bus` and `to_bus` (worst of the two).
   - `p_fail(line, hour) = 1 - exp(-(λ_wind + λ_ice) * length_km)` where
     - `λ_wind = a_kv * max(0, gust_ms - g0_kv)^2`, `λ_ice = b_kv * max(0, ice_mm - i0_kv)`.
     - kV-class parameters (defaults, all tunable in `twin/params.yaml`; values are hackathon
       priors, **[UNVERIFIED]** against utility fragility curves):

       | kV class | g0 (m/s gust) | a (per km per (m/s)²) | i0 (mm ice) | b (per km per mm) |
       |---|---|---|---|---|
       | 69–138 | 25 | 2.0e-5 | 6 | 4.0e-4 |
       | 161–230 | 30 | 1.0e-5 | 10 | 2.5e-4 |
       | 345+ | 35 | 5.0e-6 | 12 | 1.5e-4 |
   - Generators: cold-weather derate for `uri_2021` only — gas/coal units in counties with
     `temp_c < -8` get `p_unavail = 0.35`, wind units `0.5`, nuclear `0.05` (STP Unit 1 did trip
     in Uri, so nuclear is not zero). Marks the twin as honest about Uri's real driver
     (generation loss), not only lines.
   - Sampling: `rng = numpy.random.default_rng(seed ^ hash(scenario_id, hour))`; an element fails
     at hour h if `rng.random() < p_fail` and it has not already failed. Failed elements stay
     failed for the rest of the scenario window (no restoration modelling this weekend).

### `twin/cascade.py` — the loop

```
run_cascade(net, forced_out, scenario_id, hour, seed, budget_s) -> CascadeResult
  1. net = copy; scale_loads(net, scenario_id, hour)
  2. out = forced_out ∪ weather_sample(hour)       # stage 0, cause = forced|weather
  3. set in_service=False for every element in out
  4. loop stage = 1..MAX_STAGES (default 25):
       a. islands = networkx connected components of in-service graph
       b. for each island: if no in-service gen with pmax>0 → whole island is dark
          (cause=island, stage); else if gen capacity < island load → shed load
          pro-rata to make it feasible (recorded as lost_load); if load < min gen → curtail gen
       c. pp.rundcpp(net, check_connectivity=True)   # verified signature; puts unsupplied buses out of service
       d. overloaded = lines/trafos with res.loading_percent > TRIP_PCT (default 100; parameter)
          - loading_percent = i_ka / (max_i_ka · df · parallel) · 100 (pandapower's formula, verified)
          - unrated lines are never in this set
       e. if overloaded is empty → stable, break
       f. trip ALL overloaded elements this stage (simultaneous trip, deterministic; the
          alternative "trip worst-only" is a flag `trip_policy="worst"` for slower/more realistic runs)
       g. append to out with cause=overload, stage
  5. lost_load_mw = sum(base scaled load) − sum(served load)
  6. attribute: served fraction per load → bus → county_fips; customers_out =
     round(pop/2.5 · fraction_dark_county); critical load lost if its bus's served fraction < 0.5
  7. return CascadeResult; writer persists to cascade_runs
```

Scenario runs call `run_cascade` once per hour in the window (Uri = 168 hours), carrying the
`out` set forward so failures accumulate. `run_scenario(scenario_id, seed, forced_out=None)`
returns a list of `CascadeResult` and writes all rows under one `run_id`.

### Speed (designed around the measured 0.84 s/solve)

- `pp.rundcpp` on this net is **0.84 s per solve** (measured, base case). A full Uri replay is
  168 hours × ~3–5 stages ≈ 500–850 solves ≈ **7–12 min** with pandapower alone — too slow for
  the stage, acceptable for an overnight batch. So there are two run modes, both explicit:
  - `solver="lightsim"` (**default for `run_scenario`**): `lightsim2grid.pandapower_compat.dcpf`
    is the verified drop-in for the DC solve (lightsim2grid README documents it; the package is
    installed). Expected ≥ 20× faster **[UNVERIFIED speedup — acceptance 7 measures it]**; Uri
    full replay budget **120 s**. Must match pandapower within 1e-3 pu (acceptance 8).
  - `solver="pandapower"` (reference / fallback): `run_scenario` uses `hour_stride=6` (28 hours
    of Uri, failures carried forward across the stride) → 28 × ~4 × 0.84 ≈ **95 s**, inside the
    same 120 s budget; the stride is written into `run_id` (`…-h6`) so a strided run can never be
    mistaken for an hourly one.
  - Also enable `pp.rundcpp(..., recycle=...)`/`pp.runpp` recycle where pandapower supports it
    for repeated topology-only changes **[UNVERIFIED gain on 3.5.3]**.
- Single-hour `run_cascade` (copilot path): budget **10 s** = up to ~10 pandapower solves, or
  effectively unbounded stages under lightsim; MAX_STAGES stays 25.
- Exceeding a budget raises `CascadeBudgetExceeded` with the partial result attached — never a
  silent truncation; `solve_ms` and `n_solves` are recorded on every result.

### Determinism

Every stochastic choice goes through one `numpy.random.Generator` seeded by
`(seed, scenario_id, hour)`. Same inputs + same seed → byte-identical `cascade_runs` rows.
`seed` is stored in `cascade_runs.run_id` (`f"{scenario_id}-s{seed}-{sha8(forced_out)}"`).

### Islanding

pandapower's `check_connectivity=True` deactivates buses without a slack path; that is NOT
enough for us because it silently zeroes islands that have generation. So islanding is handled
explicitly in step 4a–b with networkx (`nx.connected_components` on a graph of in-service
buses/lines/trafos), one `ext_grid` is created per surviving island at its largest generator bus,
and only then is `rundcpp` called.

## Interfaces

```python
# twin/build.py
def build_base_net(mpc_path: Path = Path("data/raw/activsg2000/ACTIVSg2000.m"),
                   duck_path: Path = Path("data/duck/grid.duckdb"),
                   cache_dir: Path = Path("twin/net_cache")) -> pandapower.auxiliary.pandapowerNet
def load_base_net(cache_dir: Path = Path("twin/net_cache")) -> pandapowerNet   # raises if cache stale
def scale_loads(net: pandapowerNet, scenario_id: str, hour: int, duck_path: Path = ...) -> float  # returns k
def line_failure_probs(net: pandapowerNet, scenario_id: str, hour: int,
                       params: FragilityParams) -> pandas.Series   # index = element_id, values in [0,1]
def gen_unavailability(net: pandapowerNet, scenario_id: str, hour: int,
                       params: FragilityParams) -> pandas.Series
def weather_sample(net: pandapowerNet, scenario_id: str, hour: int,
                   seed: int, params: FragilityParams) -> set[str]       # element_ids failing this hour

# twin/cascade.py
@dataclass(frozen=True)
class TrippedElement: element_id: str; kind: Literal["line","trafo","gen","bus"]; stage: int; cause: Literal["weather","overload","island","forced"]
@dataclass(frozen=True)
class CountyDark: county_fips: str; lost_mw: float; customers_out: int; fraction_dark: float
@dataclass(frozen=True)
class CriticalLoadLost: cl_id: str; kind: str; name: str; hour_lost: int
@dataclass(frozen=True)
class CascadeResult:
    run_id: str; scenario_id: str; hour: int; stages: int; converged: bool
    tripped: list[TrippedElement]; lost_load_mw: float
    counties_dark: list[CountyDark]; critical_loads_lost: list[CriticalLoadLost]
    served_fraction_by_bus: dict[str, float]; solve_ms: float

def run_cascade(net: pandapowerNet, forced_out: set[str], scenario_id: str, hour: int,
                seed: int = 0, carried_out: set[str] | None = None,
                trip_pct: float = 100.0, max_stages: int = 25, budget_s: float = 10.0,
                solver: Literal["pandapower","lightsim"] = "lightsim") -> CascadeResult
def run_scenario(scenario_id: str, seed: int = 0, forced_out: set[str] | None = None,
                 net: pandapowerNet | None = None, budget_s: float = 120.0,
                 solver: Literal["pandapower","lightsim"] = "lightsim",
                 hour_stride: int = 1,            # forced to 6 when solver="pandapower" unless budget_s is raised
                 hours: list[int] | None = None,  # explicit subset (siting engine's stress hours)
                 write: bool = True) -> list[CascadeResult]
def write_cascade_runs(results: list[CascadeResult], duck_path: Path = ...) -> int   # rows written

# twin/tools.py — the copilot-facing wrapper (exact contract signature)
def run_cascade(element_ids: list[str], scenario_id: str, hour: int) -> dict
    # loads cached net, seed=0, calls cascade.run_cascade(forced_out=set(element_ids)),
    # writes the row, returns CascadeResult as a JSON-able dict (dataclasses.asdict)
```

CLI: `uv run python -m twin.build` (build + cache), `uv run python -m twin.cascade --scenario uri_2021 --seed 0`.

## Acceptance criteria

1. `build_base_net()` returns a net with exactly 2000 buses, 2359 lines, 0 trafos, 544 gens,
   1125 loads and 67 109 MW total base load (verified counts); every `net.line`, `net.gen`,
   `net.bus` row has a non-null `element_id` that exists in the matching DuckDB table.
2. Base case (no outages, base load) `rundcpp` converges with max line loading ≈ 79.9 % (verified)
   and zero elements above 100 %; the test asserts `max(loading_percent) < 100` and prints the
   top-5 loaded lines (they are the natural "critical elements" for the demo).
3. Rating check: for 20 random rated lines, `net.line.max_i_ka * sqrt(3) * vn_kv` equals
   `lines.rate_a_mw` within 0.5 %; the count of `unrated` lines is printed and is < 5 % of lines.
4. `scale_loads("uri_2021", 0)` returns `k` such that `sum(net.load.p_mw)` equals
   `ba_load_hourly` for ERCO at 2021-02-13 00:00 within 0.1 %; a missing hour raises
   `MissingLoadHourError`.
5. Determinism: `run_scenario("uri_2021", seed=7)` run twice yields identical
   `tripped_element_ids_json`, `lost_load_mw`, `counties_dark_json` for all 168 hours.
6. Islanding: forcing out every line touching a chosen 345 kV bus produces an island; the run
   reports that island's buses as dark with `cause="island"` and does not raise from pandapower.
7. Budget: `run_scenario("uri_2021", solver="lightsim")` (hourly, 168 h) completes in < 120 s
   on a laptop; `run_scenario("uri_2021", solver="pandapower")` (stride 6) also < 120 s; a
   single `run_cascade` call (copilot) < 10 s; `solve_ms`, `n_solves` and the measured per-solve
   time for each solver are printed (the pandapower figure must be ≈ 0.84 s; a lightsim figure
   slower than 0.2 s/solve fails this criterion and the default flips to pandapower+stride).
8. `solver="lightsim"` vs `solver="pandapower"`: `res_line.p_from_mw` agree within 1e-3 pu on the
   base case and after forcing out the 3 most-loaded lines.
9. Critical-load tagging: for `uri_2021` at least one `critical_loads` row with `kind="dod"`
   appears in `critical_loads_lost_json` by hour 72, and the front end can name it (the "Fort
   Hood at hour 3" beat in the demo — if none is lost with default params, the demo uses a forced
   outage and says so).
10. Plausibility vs. history (soft gate, reported not asserted): peak `lost_load_mw` for
    `uri_2021` lands in 10–30 GW (ERCOT shed ~20 GW at Uri's peak **[UNVERIFIED exact figure]**);
    the number and the ratio are printed in the run summary.
11. **Break-it probe (must turn red):** set `trip_pct = 1e9` (nothing can overload). Test asserts
    that for a forced outage of the 3 highest-loaded 345 kV lines at Uri hour 60, the number of
    `cause="overload"` trips is > 0 with default `trip_pct`, and the test FAILS under the mutated
    value. A second probe mutates `line_failure_probs` to return all zeros and asserts the
    `cause="weather"` count drops to zero (proves the weather wire is live, not decorative).

## Demo hook

Hero beat 2–3 of the demo script: load Uri, press play; the map animates `tripped` by stage and
hour from `cascade_runs`; the county choropleth fills from `counties_dark_json`; the critical-load
panel turns a DoD installation red at the hour in `critical_loads_lost_json`. The copilot's
`run_cascade(["line_1234"], "uri_2021", 60)` answers "what if this line goes at hour 60" live in
< 5 s. The siting counterfactual (spec 04) is the same function with a generator added.

## Risks / unknowns

- Bus coordinates live in the PowerWorld `.AUX`, ingested by spec 01 — this spec is blocked on
  `buses.lon/lat` being populated; until then attribution works (it is by `county_fips`) but the
  map does not.
- from_mpc rating conversion behaviour with `rateA == 0` — pinned by acceptance 3.
- 0.84 s/solve means the hourly Uri replay is only stage-ready under lightsim2grid; if its
  `dcpf` compat path misbehaves on 3.5.3, the shipped fallback is pandapower with a 6-hour stride
  (documented in `run_id`), not a silent truncation.
- DC PF ignores voltage collapse and reactive limits; Uri's real mechanism was generation loss
  plus frequency — we model gen derates as sampled unavailability, which is honest but coarse.
- Simultaneous-trip policy can over-cascade; `trip_policy="worst"` is the fallback if runs look
  absurd (everything dark by stage 3).
- Fragility parameters are priors; the outage model (spec 02) is the calibrated layer, this one is
  the physics layer — the demo must say which is which.
- `check_connectivity=True` behaviour on multi-island nets must be verified with the explicit
  per-island `ext_grid` approach; if pandapower still complains, fall back to running each island
  as a separate sub-net (`pp.select_subnet`).

## Weekend time-box

| Task | Hours |
|---|---|
| Download case, `from_mpc`, element_id stamping, ratings, cache | 2.0 |
| Hourly load scaling + gen scaling | 1.0 |
| Fragility params + weather sampling + gen derates | 1.5 |
| Cascade loop, islanding, attribution, writer | 3.5 |
| Acceptance tests incl. break-it probes | 1.5 |
| Tuning against Uri plausibility + parquet export for the map | 1.5 |
| **Total** | **12.5 h** (Day 1 evening + Day 2 morning overlap) |
| lightsim2grid `dcpf` solver path + parity test (now on the critical path, not stretch) | 1.5 h |
| Stretch: Grid2Op operator agent (redispatch/topology remediation via `LightSimBackend`) | +4 h, only if everything above is green by Day 2 noon |
