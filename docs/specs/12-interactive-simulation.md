# 12 — Interactive Grid Simulation (`twin/`, `siting/`, `copilot/`, `web/`)

> **State scope:** Texas / ACTIVSg2000 only. This spec is the interactive-physics lane and
> supersedes [`10-minnesota-demo.md`](10-minnesota-demo.md) **for that lane only**. Minnesota
> remains aggregate-mode per [`docs/research/minnesota/solver-network-feasibility.md`](../research/minnesota/solver-network-feasibility.md)
> and must never render lines, flows, loading, trips, or cascades.

Status: draft · Owner: platform + web lanes · Supersedes nothing in specs 01–09; it makes
03 (cascade), 04 (siting), 05 (copilot tools), and 06 (frontend) *interactive* rather than
precomputed.

## Purpose

Make the Texas grid an object the user can **edit and break**, and have the answer come back
from a solver rather than a lookup table. Six capabilities:

1. Real Texas nodes on the map — actual coordinates, power draw, annotation.
2. Add and remove producers, consumers, and transmission, under physics-informed limits.
3. Crisis mode — take providers, consumers, or transmitters offline and see the consequence.
4. Load/supply accounting — consumer draw versus producer capability, with headroom.
5. A redundancy score for consumer locations.
6. Ideal-location search for new producers and consumers.

**Fidelity bar: good enough, honestly labeled.** DC power flow, no reactive power, no
dynamics, no protection modeling, no unit commitment. Every result carries `model_fidelity:
"dc_screening"` and the caveat that it is a screening model on a *synthetic* network. See
§Truth labels.

## Inputs

All from the existing DuckDB contract (`00-overview.md` §2.2) — no new ingest is required.

| Input | Table | Already populated by |
| --- | --- | --- |
| Bus identity, coordinates, voltage | `buses(bus_id, name, base_kv, lon, lat, county_fips, ba_code)` | [pipelines/activsg.py](../../pipelines/activsg.py) from AUX |
| Branch impedance, rating, geometry | `lines(line_id, from_bus, to_bus, base_kv, r_pu, x_pu, rate_a_mw, length_km, geom_wkb)` | same |
| Generation | `gens(gen_id, bus_id, fuel, pmax_mw)` + `synthetic_generator_electrical` | same |
| Consumer draw | `loads(load_id, bus_id, p_mw_nominal)` | same |
| Hourly demand shape | `ba_load_hourly(ba_code, ts, demand_mw)` | `pipelines/eia930.py` |
| Critical facilities | `critical_loads(cl_id, kind, name, lon, lat, bus_id, county_fips)` | `pipelines/critical_loads.py` |
| Counties, hazard | `counties`, `hazard_static` | `pipelines/counties.py`, `nri.py` |

The 847 branches that import as `net.impedance` are in scope and must be included in the
transformer-overload path (product invariant). lightsim2grid stays out — it raises
`Unsupported element (Impedance)` on this case.

## Outputs

- `twin/net.py` — cached `pandapowerNet` built from the tables above.
- `twin/cascade.py` — `CascadeResult` (per `03-cascade-sim.md`), now callable on an edited net.
- `scenario_edits` — new table: `(edit_id, session_id, base_scenario_id, ops_json, created_at, edit_hash)`.
- `redundancy_scores` — new table: `(bus_id, scenario_id, hour, n1_survival_pct, independent_paths, nearest_alt_source_km, headroom_mw, score, components_json)`.
- `siting_search_runs` — new table: `(run_id, objective, kind[producer|consumer], unit_mw, scenario_id, ranked_json, computed_at)`.
- In-memory `GridBalance` — draw, capability, headroom, reserve margin, per region and per island.

## Algorithm or Design

### 12.1 Net construction (`twin/net.py`)

`buses` → `pp.create_bus` (name, vn_kv). `lines` → `create_line_from_parameters` using
`r_pu`/`x_pu` converted on the case base MVA (100 MVA) and `rate_a_mw` → `max_i_ka`.
Equal-voltage-endpoint records with a tap become transformers; the 847 impedance branches keep
their `net.impedance` representation. `gens` → `create_gen` (`p_mw` from
`synthetic_generator_electrical`, `max_p_mw` = `pmax_mw`); the largest-capacity bus is slack.
`loads` → `create_load(p_mw = p_mw_nominal)`.

Hourly scaling: `p_mw(h) = p_mw_nominal × ba_load_hourly[ba_code, h] / ba_load_hourly[ba_code, ts_start]`.
A bus whose `ba_code` has no row that hour is **unavailable**, not defaulted.

Build is cached by `sha256(grid tables) + scenario_id`; target < 3 s cold, < 50 ms warm.

### 12.2 Scenario edits (`twin/edits.py`)

An edit is an ordered op list applied to the cached net *in a copy*, never in place:

```python
type Op = (
    {"op": "remove", "kind": "line|gen|bus|load", "id": str}
  | {"op": "add_gen",  "bus_id": int, "p_mw": float, "fuel": str}
  | {"op": "add_load", "bus_id": int, "p_mw": float, "kind": str}
  | {"op": "add_line", "from_bus": int, "to_bus": int, "base_kv": float}
  | {"op": "outage",   "kind": "line|gen|bus|load", "id": str}   # crisis: offline, not deleted
)
```

`edit_hash = sha8(canonical_json(ops))` and every downstream artifact carries it, so a result
is always traceable to the exact edited network. `remove` and `outage` differ only in
reporting: an outage is attributed as a crisis cause, a removal changes the baseline.

### 12.3 Physics-informed placement limits (`twin/feasibility.py`)

A proposed `add_gen` / `add_load` / `add_line` returns `valid | invalid | unknown` with a
reason, before any solve:

| Rule | Threshold | Basis |
| --- | --- | --- |
| P1 Interconnect distance | attach point must be within **40 km** of a bus with `base_kv ≥ 138` | reuses `04-siting-engine.md` §candidates step 4 |
| P2 Voltage class | unit > 300 MW requires `base_kv ≥ 230` | **[UNVERIFIED — our screening choice]** |
| P3 Spur rating | new radial spur limited to the thermal rating of the smallest conductor class for its voltage; longer than 40 km ⇒ `invalid` | **[UNVERIFIED — our screening choice]** |
| P4 Corridor headroom | post-injection loading of the connecting corridor ≤ 100 % of `rate_a_mw` at the scenario peak hour | DC PF on the edited net |
| P5 Interconnection membership | site must be inside ERCOT; SPP/WECC sites get `bus_id = NULL` and `unknown` | `04-siting-engine.md` (verified via PUC "Utilities Outside ERCOT") |
| P6 Island viability | the edit must not leave the attach point in an island with no generation | connectivity check |

P1 and P3 together are the "limits on transmission distance" requirement. P1–P3 are geometric
and run in < 10 ms; P4 and P6 need one DC solve.

### 12.4 Crisis simulation (`twin/cascade.py`, extending spec 03)

Unchanged loop — drop → `pp.rundcpp` → trip elements over `rate_a_mw` → repeat — with three
additions:

- **Element kinds.** `forced_out` accepts `gen` and `load` ids, not only lines/trafos. Losing a
  *consumer* is a valid crisis input (load shed, industrial trip) and reduces demand.
- **Island balancing.** After each topology change, per island: if generation capability >
  demand, scale generation down proportionally; if demand > capability, shed load
  proportionally and record `lost_load_mw` per bus. A zero-generation island is fully dark.
- **Attribution.** Lost load maps to `county_fips` via `buses`, to customers via
  `counties.pop` share, and to `critical_loads` via `critical_loads.bus_id`.

Budgets from A7 hold: 120 s per scenario replay, **10 s** per interactive call, `MAX_STAGES = 25`.

### 12.5 Load/supply accounting (`twin/balance.py`)

For a scope (state, BA, county, or island) at hour `h`:

```
draw_mw        = Σ loads.p_mw(h)                    # consumer power draw
capability_mw  = Σ gens.pmax_mw over in-service gens
dispatch_mw    = Σ gens.p_mw(h)
headroom_mw    = capability_mw − draw_mw
reserve_margin = headroom_mw / draw_mw
```

`capability_mw` is nameplate, **not** availability-derated — the card says so. Wind and solar
are reported separately from firm fuels so the number is not read as firm capacity.

### 12.6 Redundancy score for consumer locations (`siting/redundancy.py`)

For a load bus `b`, scenario, hour — three components, each 0–100, then a weighted score:

1. **N-1 survival** (weight 50). Over the `k = 20` highest-flow branches supplying `b`
   (ranked by DC power transfer distribution factor), run the single-contingency cascade;
   `n1_survival_pct` = share of those contingencies in which `b` keeps its full load.
2. **Independent paths** (weight 30). Edge-disjoint path count from `b` to any generating bus
   (Menger / max-flow on the unweighted graph), capped at 4 and scaled.
3. **Alternative source proximity** (weight 20). Haversine distance to the nearest generating
   bus not already counted in path 1, scaled inversely against a 150 km reference.
   **[UNVERIFIED reference distance — our choice]**

`score = 0.5·n1 + 0.3·paths + 0.2·proximity`, deterministic, seeded, persisted to
`redundancy_scores`. A bus that is radially fed scores near zero on components 1 and 2 by
construction — that is the intended signal.

### 12.7 Ideal-location search (`siting/search.py`)

Candidate set: existing `site_candidates` (producers) plus every load bus and a 25 km hex grid
clipped to Texas (consumers). For each candidate passing §12.3:

- **Producer objective** — `0.5·z(lost_load_reduction_mwh) + 0.3·z(mean_redundancy_uplift) + 0.2·z(congestion_relief_pct)`,
  where each term is a delta between the baseline cascade and the cascade with the unit online.
- **Consumer objective** — `0.6·z(redundancy_score) + 0.4·z(headroom_mw)` at the candidate bus,
  rejecting any candidate whose added draw pushes a corridor past P4.

Ranked list, top `n`, each row carrying its component values, the `edit_hash` of the
counterfactual, and its safety flags from spec 04 where the candidate is a `site_candidates`
row. Cost control: score all candidates on the single scenario **peak hour**, then re-run the
top 5 over the full window.

### 12.8 Truth labels

Every response from this spec carries:

```json
{"model_fidelity": "dc_screening",
 "network_provenance": "synthetic_activsg2000",
 "limitations": ["DC power flow: no reactive power, voltage, or dynamics",
                 "ACTIVSg2000 is a synthetic Texas network, not ERCOT's model",
                 "Nameplate capability, not derated availability"]}
```

The UI renders `synthetic` for anything derived from ACTIVSg2000 topology (product invariant),
`source_backed` only for EIA/EAGLE-I/Census/NRI attributes, and `illustrative` for user edits.

## Interfaces

```python
# twin/
def build_net(scenario_id: str, hour: int) -> pandapowerNet
def apply_edits(net: pandapowerNet, ops: list[Op]) -> tuple[pandapowerNet, str]   # -> edit_hash
def check_feasibility(op: Op, net: pandapowerNet, hour: int) -> FeasibilityResult
def run_cascade(element_ids: list[str], scenario_id: str, hour: int,
                edits: list[Op] | None = None) -> CascadeResult
def grid_balance(scope: str, scenario_id: str, hour: int,
                 edits: list[Op] | None = None) -> GridBalance
# siting/
def redundancy_score(bus_id: int, scenario_id: str, hour: int) -> RedundancyScore
def search_locations(kind: Literal["producer", "consumer"], unit_mw: float,
                     scenario_id: str, n: int = 10) -> list[RankedLocation]
```

HTTP (spec 05 surface):

```
POST /scenario/edit   {base_scenario_id, ops[]}          -> {edit_hash, feasibility[]}
POST /cascade         {element_ids, scenario_id, hour, edit_hash?}   -> CascadeResult
GET  /balance         ?scope=&scenario_id=&hour=&edit_hash=          -> GridBalance
GET  /redundancy      ?bus_id=&scenario_id=&hour=                    -> RedundancyScore
POST /siting/search   {kind, unit_mw, scenario_id, n}                -> RankedLocation[]
```

Copilot tools (completing the nine-tool contract of `00-overview.md` A8, plus three):
`run_cascade`, `score_site`, `predict_outage` — **register the three that were specified and
never built** — and new `edit_scenario`, `grid_balance`, `redundancy_score`,
`search_locations`. Each returns its evidence block per §12.8; the model may not state a
number these tools did not return.

## Acceptance criteria

1. `uv run python -m twin.net --scenario uri_2021 --hour 0` builds a 2000-bus net including the
   847 impedance branches, and `pp.rundcpp` converges.
2. A `GET /layers/buses` response carries `lon`, `lat`, `base_kv`, node role
   (producer/consumer/transmission), `p_mw` draw, and `pmax_mw` for every bus, with per-field
   provenance.
3. Removing a named transmission corridor and re-running produces a different `lost_load_mw`
   than baseline, and the diff is attributable to named counties and critical loads.
4. Taking a named generator offline reduces island capability and, where demand exceeds it,
   sheds load — reported in MW, not as a status string.
5. A proposed unit 80 km from the nearest 138 kV bus returns `invalid` with reason `P1`; one
   12 km away on a 345 kV bus returns `valid`.
6. Two consumer locations, one radially fed and one meshed, return materially different
   redundancy scores, and the component breakdown explains why.
7. `/balance` for ERCOT at the Uri peak hour returns draw, capability, and headroom whose
   arithmetic a judge can check against the underlying tables.
8. `search_locations(kind="producer")` returns a ranked list whose #1 differs from a
   naive largest-headroom pick, with the objective components shown.
9. Every response above carries `model_fidelity`, `network_provenance`, and `limitations`.
10. An interactive `/cascade` call returns within 10 s.

## Demo hook

"Here is the real Texas network — 2,000 buses, actual coordinates, actual draw. Take out this
corridor." *(cascade replays, counties darken, a hospital drops off.)* "Where should the next
gigawatt go?" *(ranked list.)* "Why there?" *(component breakdown, safety flags.)* "And this
data center — how redundant is that site?" *(score, and the single contingency that kills it.)*

## Risks/unknowns

| Risk | Likelihood | Mitigation |
| --- | --- | --- |
| Interactive cascade exceeds 10 s on a large edit | Medium | Cap `MAX_STAGES`, solve peak hour only for interactive calls, warm net cache |
| Redundancy N-1 over 20 contingencies × many buses too slow | High | Precompute for all load buses overnight; interactive path reads the table and only recomputes for edited buses |
| `rate_a_mw` missing or zero on some branches | Medium | Treat as unavailable, exclude from overload logic, report the count — never assume a rating |
| Judges read the synthetic network as ERCOT's | High | Label on every card; say it aloud in the demo |
| Consumer siting objective has no ground truth | High | Present as a screening comparison, never as a recommendation |

## Weekend time-box

| Block | Work |
| --- | --- |
| 1 | `twin/net.py` + net cache; layer API carries role/draw/annotation |
| 2 | `twin/cascade.py` element kinds + island balancing; `POST /cascade` |
| 3 | `twin/edits.py` + `twin/feasibility.py` P1–P6; `POST /scenario/edit` |
| 4 | `twin/balance.py` + `/balance`; `siting/redundancy.py` + precompute |
| 5 | `siting/search.py` + `/siting/search` |
| 6 | Copilot tool registration for all seven; UI wiring |
