# 03 — Cascade Simulation (`twin/`)

> **Scope order:** Minnesota is the current case ([`10-minnesota-demo.md`](10-minnesota-demo.md)); Texas is second; further states follow. Texas references below describe the second case, not the current one.

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
| ACTIVSg2000 case | `case_ACTIVSg2000.m` bundled in the pip package `matpower` under `matpower/data/` (verified by the coordinator; copy to `data/raw/activsg2000/case_ACTIVSg2000.m` so the raw dir is the source of record). Verified import (re-run 2026-09-05, pandapower 3.5.3): `from_mpc(path, f_hz=60)` → **2000 buses / 2359 `line` rows / 0 `trafo` rows / 847 `impedance` rows / 484 `gen` + 59 `sgen` + 1 `ext_grid` (= the 544 MATPOWER generator rows) / 1125 loads / 67 109 MW load**. The `.m` has **3206 branch rows**: the 847 with a tap ratio AND unequal end-voltages import as `net.impedance` (NOT `net.line`, NOT `net.trafo`), the remaining 2359 (2345 with ratio 0 + 14 with ratio 1 between equal-kV buses) import as `net.line`. Base-case `pp.rundcpp`: **first call 0.49 s (one-time import/JIT cost), every later call 9–14 ms** (100 topology-changed solves = 1.23 s); **max line loading 79.87 %**. | Bus lat/lon are NOT in the `.m`; they come from the TAMU PowerWorld `.AUX` (`data/raw/activsg2000/…/Texas2000_June2016.AUX`) — verified: the coordinates live in the **`DATA (Substation, [SubNum,SubName,SubID,Latitude,Longitude,…])` block**, not the Bus block; the Bus block carries `SubNum`, so bus→substation→lat/lon is a two-step join (the companion `Texas2000_June2016.xlsx` `Substations` sheet has the same `Latitude`/`Longitude` columns and is easier to read). Spec 01 ingests this into `buses.lon/lat`. This spec reads geography ONLY from `buses`. Also verified: `from_mpc` **renumbers buses** — pandapower bus index = MATPOWER row position (bus 1001 → index 1000), so every join to the `.m`/`.AUX` must go through row order or `net.bus.name`, never through the pandapower index as a bus number. |
| `buses`, `lines`, `gens`, `loads` | `data/duck/grid.duckdb` | Produced by spec 01 (ingest). `lines.rate_a_mw` is the MATPOWER `rateA`; `buses.county_fips` is the bus↔county join. |
| `ba_load_hourly(ba_code, ts, demand_mw)` | DuckDB | EIA-930 hourly demand; Texas rows have `ba_code = 'ERCO'`. |
| `weather_hourly(county_fips, ts, wind_ms, gust_ms, temp_c, ice_mm, precip_mm)` | DuckDB | HRRR-derived county-hour weather for each scenario window. |
| `counties(county_fips, name, state, pop, geom_wkb)` | DuckDB | `pop` → customers via a fixed 2.5 persons/customer ratio (documented constant, overridable; **[UNVERIFIED]** — Census QuickFacts gives Texas persons per *household* 2019–2023 = 2.70, but "customer" = meter incl. non-residential, for which no primary figure was found; what would verify it is EIA-861 Texas customer counts ÷ Census population). |
| `critical_loads(cl_id, kind, name, lon, lat, bus_id, county_fips)` | DuckDB | `bus_id` = nearest bus of ≥ 115 kV within the same county, assigned by spec 01. |
| `scenarios(scenario_id, name, kind, ts_start, ts_end)` | DuckDB | `uri_2021` (2021-02-13..2021-02-20 — a product choice: the FERC/NERC final report's event window is Feb 8–20, 2021 and ERCOT's firm load shed ran Feb 15–18, so this 168 h window contains the whole Texas outage), `beryl_2024` (landfall near Matagorda, TX 04:50 EDT July 8, 2024 — DOE SitRep #4), `helene_2024` (landfall Florida Big Bend Sept 26, 2024; no Texas impact — NHC TCR AL092024), `forecast_72h`. |

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
   Matching is by MATPOWER row order (`from_mpc` preserves branch order within each target
   table — verified: the 2359 `net.line` rows are exactly the `.m` branch rows without a
   voltage-changing tap, in order, and `from_bus/to_bus` match row-for-row). **CORRECTED:** the
   847 transformer branches do NOT become lines or `net.trafo`; they become **`net.impedance`**
   rows (`rft_pu/xft_pu`, `sn_mva` = MATPOWER `rateA`). `pp.rundcpp` fills `res_impedance` with
   `p_from_mw/p_to_mw/i_from_ka/i_to_ka` but **no `loading_percent`**, so transformer overload
   must be computed by the loop as `max(|p_from_mw|,|p_to_mw|) / sn_mva · 100` (DC, no losses) —
   otherwise transformers can never trip and the cascade is lines-only. `kind="trafo"` in
   `TrippedElement` refers to these impedance rows. The loop still handles `net.trafo`
   generically for other cases. Cache metadata stores the counts (2000/2359/847/484+59+1/1125)
   and the build fails loudly if they differ.
   Verified: `from_mpc` sets `max_i_ka = rateA / (√3 · vn_kv)` exactly (max relative error
   2e-16 over all 2359 lines) and a branch with `rateA == 0` gets the sentinel
   `max_i_ka = 99999` (checked on a modified copy of the case; the shipped case has **zero**
   `rateA == 0` rows). Step 3 overwrites the value anyway.
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
       priors, **[UNVERIFIED]** against utility fragility curves — no primary source was found
       that gives per-kV-class wind/ice hazard rates in this functional form; what would verify
       them is a published fragility curve, e.g. the ice/wind curves in the EPRI/NERC winter
       storm reports or a utility outage-vs-gust regression). **CORRECTED kV classes:** the
       ACTIVSg2000 transmission voltages are exactly **115 / 161 / 230 / 500 kV** (826 / 453 /
       152 / 120 buses; generator buses are 13.2–24 kV) — there is **no 345 kV** and nothing
       below 115 kV in this case, so the classes are keyed to what exists:

       | kV class | g0 (m/s gust) | a (per km per (m/s)²) | i0 (mm ice) | b (per km per mm) |
       |---|---|---|---|---|
       | 115 | 25 | 2.0e-5 | 6 | 4.0e-4 |
       | 161–230 | 30 | 1.0e-5 | 10 | 2.5e-4 |
       | 500 | 35 | 5.0e-6 | 12 | 1.5e-4 |
   - Generators: cold-weather derate for `uri_2021` only — gas/coal units in counties with
     `temp_c < -8` get `p_unavail = 0.35`, wind units `0.5`, nuclear `0.05` (STP Unit 1 did trip
     in Uri, so nuclear is not zero; the 0.35/0.5/0.05 values are priors, **[UNVERIFIED]**).
     **Fuel source (verified):** the fuel is NOT in the pandapower net (`net.gen.type` is empty
     after `from_mpc`), NOT exposed by `matpowercaseframes.CaseFrames`, and NOT in the
     `Texas2000_June2016.xlsx` `Generators` sheet (columns: Bus Number, Min/Max MW, Min/Max Mvar,
     MW dispatch, Voltage Set Point — no fuel). It IS in the `.m` as `mpc.genfuel` / `mpc.gentype`
     (544 rows: ng 367, wind 87, coal 39, hydro 25, solar 22, nuclear 4) — parse those two cell
     arrays from the `.m` by regex in row order and stamp `fuel` onto `gen`/`sgen` rows (the
     converter splits the 544 rows into 484 `gen` + 59 `sgen` + 1 `ext_grid`; the stamping must
     follow the converter's split, and the build asserts every row got a fuel). Marks the twin as honest about Uri's real driver
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
       c. pp.rundcpp(net, check_connectivity=True)   # verified signature (check_connectivity defaults True); buses with no path to a slack get NaN results and zero served load
       d. overloaded = lines with res_line.loading_percent > TRIP_PCT (default 100; parameter)
          ∪ impedances (transformers) with max(|p_from_mw|,|p_to_mw|) / sn_mva · 100 > TRIP_PCT
          - loading_percent = i_ka / (max_i_ka · df · parallel) · 100 (pandapower's formula, verified in
            pandapower/results_branch.py: `i_max = max_i_ka * df * parallel`; `inf` where i_max == 0)
          - res_impedance has NO loading_percent (verified) — the loop computes it
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

### Speed (CORRECTED — designed around the re-measured 9–14 ms/solve)

- **The earlier "0.84 s/solve" was the one-time first-call cost** (import + JIT), not the
  steady-state solve time. Re-measured 2026-09-05 on this net: first `pp.rundcpp` 0.49 s, every
  subsequent solve **9–14 ms** including a topology change (100 solves with a different line
  dropped each time = 1.23 s; `copy.deepcopy(net)` = 5 ms). A full Uri replay of 168 hours ×
  ~3–5 stages ≈ 500–850 solves is therefore ≈ **6–12 s with plain pandapower** — stage-ready
  with no second solver. Consequences:
  - `solver="pandapower"` is the **default and the only shipped solver**; `hour_stride` defaults
    to 1 (hourly). The stride option survives as a knob and is still written into `run_id`
    (`…-h6`) when used, so a strided run can never be mistaken for an hourly one.
  - `solver="lightsim"` is **stretch, not on the weekend path**, because it is NOT a drop-in on
    this case (verified against lightsim2grid 1.0.0): `lightsim2grid.pandapower_compat.dcpf(B,
    Pbus, Va0, ref, pv, pq)` is a matrix-level replacement of pandapower's internal `dcpf`
    ("meant to be used from inside pandapower and not directly" — its own docstring), pandapower
    3.5.3 wires `lightsim2grid` ONLY into the AC Newton-Raphson path (`run_newton_raphson_pf`;
    `rundcpp`/`run_dc_pf` have no lightsim hook), and `lightsim2grid.gridmodel.init_from_pandapower(net)`
    raises `RuntimeError: Unsupported element found (Impedance - "pp_net.impedance")` on this net
    because of the 847 transformer-impedances. Using it would require converting impedances to
    `trafo` rows first; the measured pandapower speed makes that unnecessary.
  - `pp.rundcpp(net, recycle=...)` exists in the 3.5.3 signature; its gain on repeated
    topology-only changes is **[UNVERIFIED — measure before relying on it; not needed for budget]**.
- Budgets: `run_scenario` hourly Uri **120 s** (10× headroom over the measured estimate);
  single-hour `run_cascade` (copilot path) **10 s** ≈ up to ~500 solves, so MAX_STAGES (25) is
  the binding limit, not time.
- Exceeding a budget raises `CascadeBudgetExceeded` with the partial result attached — never a
  silent truncation; `solve_ms` and `n_solves` are recorded on every result.

### Determinism

Every stochastic choice goes through one `numpy.random.Generator` seeded by
`(seed, scenario_id, hour)`. Same inputs + same seed → byte-identical `cascade_runs` rows.
`seed` is stored in `cascade_runs.run_id` (`f"{scenario_id}-s{seed}-{sha8(forced_out)}"`).

### Islanding (behaviour verified on this net, 2026-09-05)

pandapower's `check_connectivity=True` (the default) deactivates buses without a slack path; that
is NOT enough for us because it **silently zeroes islands that have generation** — verified:
cutting the 4 lines at a 115 kV bus produced a 3-bus island with 7.6 MW of gen and 13.5 MW of
load; `rundcpp` returned `converged=True`, `res_bus.vm_pu = NaN`, `res_gen.p_mw = 0`,
`res_load.p_mw = 0` for the island, and `net.bus.in_service` was left `True` (the deactivation is
internal, results are just NaN/0). With `check_connectivity=False` pandapower does NOT raise
either: it returns `converged=True` with garbage angles (−1.7e16 degrees) and "serves" the island
load. So the loop must never call `rundcpp` without its own island handling. Islanding is handled
explicitly in step 4a–b with `pandapower.topology.create_nxgraph(net)` — verified to include
`impedance` edges by default (`include_impedances=True`; 3206 edges, 1 component; with
`include_impedances=False` the graph falls apart into 453 components, so the impedance edges are
mandatory) — plus `networkx.connected_components`. One `ext_grid` is created per surviving island
at its largest generator bus (verified: `pp.create_ext_grid(net, bus)` on the island bus makes
`rundcpp` serve the island and `res_ext_grid` reports one row per slack), and only then is
`rundcpp` called.

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
                solver: Literal["pandapower","lightsim"] = "pandapower") -> CascadeResult   # "lightsim" raises NotImplementedError until the stretch lands
def run_scenario(scenario_id: str, seed: int = 0, forced_out: set[str] | None = None,
                 net: pandapowerNet | None = None, budget_s: float = 120.0,
                 solver: Literal["pandapower","lightsim"] = "pandapower",
                 hour_stride: int = 1,            # hourly by default; any stride > 1 is stamped into run_id
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

1. `build_base_net()` returns a net with exactly 2000 buses, 2359 lines, 0 trafos, 847
   impedances, 484 gens + 59 sgens + 1 ext_grid, 1125 loads and 67 109 MW total base load
   (verified counts); every `net.line`, `net.impedance`, `net.gen`, `net.sgen`, `net.bus` row has
   a non-null `element_id` that exists in the matching DuckDB table, and every `gen`/`sgen` row
   has a `fuel` in {ng, wind, coal, hydro, solar, nuclear} with the totals 367/87/39/25/22/4
   across gen+sgen+ext_grid (from `mpc.genfuel`).
2. Base case (no outages, base load) `rundcpp` converges with max line loading ≈ 79.9 % (verified
   79.87 %) and zero elements above 100 %; the test asserts `78 < max(loading_percent) < 82` (a
   band, so a wrong rating overwrite or a wrong `f_hz` shows up as a red) and prints the top-5
   loaded lines (they are the natural "critical elements" for the demo).
   2b. The loop's impedance loading (`max(|p_from|,|p_to|)/sn_mva`) is computed for all 847
   impedances on the base case and its max is printed; the test asserts it is finite and > 0.
3. Rating check: for 20 random rated lines, `net.line.max_i_ka * sqrt(3) * vn_kv` equals
   `lines.rate_a_mw` within 0.5 %; the count of `unrated` lines is printed and equals 0 on this
   case (verified: no `rateA == 0` rows), and a unit test on a modified `.m` with one `rateA = 0`
   branch asserts that branch is tagged `unrated=True` with `max_i_ka == 9999` after step 3.
4. `scale_loads("uri_2021", 0)` returns `k` such that `sum(net.load.p_mw)` equals
   `ba_load_hourly` for ERCO at 2021-02-13 00:00 within 0.1 %; a missing hour raises
   `MissingLoadHourError`.
5. Determinism: `run_scenario("uri_2021", seed=7)` run twice yields identical
   `tripped_element_ids_json`, `lost_load_mw`, `counties_dark_json` for all 168 hours, AND the
   run is non-trivial: total `cause="weather"` trips > 0 and `seed=8` differs from `seed=7` in at
   least one hour's `tripped_element_ids_json` (two empty runs are trivially identical — this
   clause makes the test fail if sampling is dead).
6. Islanding: forcing out every line (and impedance) touching a chosen 500 kV bus — there is no
   345 kV in this case — produces an island; the run reports that island's buses as dark with
   `cause="island"` and does not raise from pandapower. **Falsifiable part:** the test picks the
   island by networkx BEFORE the run, sums its base-scaled load `L_island`, and asserts
   `lost_load_mw ≥ 0.99 · L_island` AND that every island bus has `served_fraction_by_bus == 0`
   — a loop that forgets the island would report `lost_load_mw ≈ 0` (pandapower silently zeroes
   the island, verified) and this assertion turns red.
7. Budget: `run_scenario("uri_2021")` (pandapower, hourly, 168 h) completes in < 120 s on a
   laptop; a single `run_cascade` call (copilot) < 10 s; `solve_ms`, `n_solves` and the measured
   per-solve time are printed and the warm per-solve time must be < 50 ms (measured 9–14 ms on
   2026-09-05; the first solve is excluded from the average because it carries the ~0.5 s
   one-time cost). If `solver="lightsim"` is ever implemented, it must additionally pass 8.
8. (Stretch, only if `solver="lightsim"` is implemented) `solver="lightsim"` vs
   `solver="pandapower"`: `res_line.p_from_mw` agree within 1e-3 pu on the base case and after
   forcing out the 3 most-loaded lines. Until then the test is skipped with an explicit
   `NotImplementedError` reason, not silently green.
9. Critical-load tagging: for `uri_2021` at least one `critical_loads` row with `kind="dod"`
   appears in `critical_loads_lost_json` by hour 72, and the front end can name it (the "Fort
   Hood at hour 3" beat in the demo — the post is Fort Hood again since July 28, 2025 (it was
   Fort Cavazos May 2023–2025, per army.mil); it sits in Oncor/ERCOT territory — if none is lost with default params, the demo uses a forced
   outage and says so).
10. Plausibility vs. history (soft gate, reported not asserted): peak `lost_load_mw` for
    `uri_2021` lands in 10–30 GW (FERC/NERC final report, Nov 2021: ERCOT had "three consecutive
    days of firm load shed — at one point up to 20,000 megawatts", with 61,800 MW of generation
    lost; quote confirmed via a published summary of the report because ferc.gov refused the
    fetch — the number is the report's, not ours);
    the number and the ratio are printed in the run summary.
11. **Break-it probe (must turn red):** set `trip_pct = 1e9` (nothing can overload). Test asserts
    that for a forced outage of the 3 highest-loaded 500 kV lines (no 345 kV exists in this case)
    at Uri hour 60, the number of `cause="overload"` trips is > 0 with default `trip_pct`, and
    the test FAILS under the mutated value. If the base-loaded case never overloads under this
    forced outage, the test must ESCALATE the forced set (top-5, top-10 500 kV lines) until an
    overload occurs, and record which set was needed; it may not pass on "0 == 0". A third probe
    mutates the impedance-loading computation to return zeros and asserts at least one
    `kind="trafo"` overload trip exists across the Uri stress hours with the default code — proving
    transformer overloads are read from `res_impedance`, not ignored. A second probe mutates `line_failure_probs` to return all zeros and asserts the
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
- from_mpc rating conversion with `rateA == 0` yields the `99999` kA sentinel (verified on a
  modified copy); the shipped case has no such rows, so acceptance 3's unrated count is 0.
- Transformer overload is invisible unless the loop reads `res_impedance` — verified there is no
  `loading_percent` for impedances; acceptance 2b and 11 cover it.
- Solve time: the hourly Uri replay is stage-ready with plain pandapower (≈ 12 ms/solve
  warm). lightsim2grid is NOT usable on this net without converting the 847 impedances to
  trafos (see Speed); it is stretch only. If a machine is unexpectedly slow, the fallback is a
  6-hour stride documented in `run_id`, never a silent truncation.
- DC PF ignores voltage collapse and reactive limits; Uri's real mechanism was generation loss
  plus frequency — we model gen derates as sampled unavailability, which is honest but coarse.
- Simultaneous-trip policy can over-cascade; `trip_policy="worst"` is the fallback if runs look
  absurd (everything dark by stage 3).
- Fragility parameters are priors; the outage model (spec 02) is the calibrated layer, this one is
  the physics layer — the demo must say which is which.
- `check_connectivity=True` behaviour on multi-island nets is verified with the explicit
  per-island `ext_grid` approach (see Islanding); pandapower never "complains" — it returns
  NaN/zeros or garbage, so the guard is ours. Fallback if a case ever needs it: run each island
  as a separate sub-net via `pandapower.toolbox.select_subnet` (verified: NOT exported as
  `pp.select_subnet` in 3.5.3; same for `pandapower.toolbox.drop_lines`).

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
| Stretch: lightsim2grid path (needs impedance→trafo conversion first; see Speed) + parity test | +1.5 h, not on the weekend path |
| Stretch: Grid2Op operator agent (redispatch/topology remediation via `LightSimBackend`) | +4 h, only if everything above is green by Day 2 noon |
