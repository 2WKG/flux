# 07 — Causal layer (Bayesian network, hardening effect estimate, counterfactual replay)

Status: build spec, weekend scope, with an explicit "what is real vs slideware" ledger.
Depends on: `01-data-ingest.md` (tables), `02-outage-model.md` (`outage_predictions`,
`outage_features.parquet`), `03-cascade-sim.md` (`twin/cascade.py::run_scenario(scenario_id, seed, forced_out, net=…)`,
`cascade_runs(run_id, scenario_id, hour, tripped_element_ids_json, lost_load_mw, counties_dark_json, critical_loads_lost_json)`),
`04-siting-engine.md` (`site_candidates` with string `site_id`, `site_scores`), `05-copilot.md`
(`copilot/tools/registry.py`, `[doc p.N]` citation format, number-trace verifier).

## Purpose

Three deliverables, in decreasing order of weekend realism:

1. **C1 — Outage causal graph (pgmpy).** A small discrete Bayesian network
   `weather_severity → exposure → line_failures → substation_loss → customers_out`, with
   `investment` (utility SAIDI trend / hardening) as a confounder on `line_failures` and
   `customers_out`. Answers "how much of this county's outage risk is weather vs.
   under-investment?" by comparing `P(customers_out | do(weather), investment)` across
   investment strata. **Achievable**: fitted from `outage_features` + `utility_reliability`.
2. **C2 — Effect of hardening / firm generation on outage duration (DoWhy / EconML).**
   Difference-in-differences with synthetic-control weights across similar counties in
   EAGLE-I, treated = counties whose utility's SAIDI-excluding-MED trend improved (proxy for
   hardening) or whose county gained ≥ 100 MW firm capacity (EIA-860 `operating_date`).
   **Achievable as an estimate with a wide interval and a stated identification caveat;**
   slideware if EIA-861 (P1) is not loaded.
3. **C3 — Counterfactual replay ("Uri with site X online").** A literal do-operation on the
   twin: re-run the spec-03 cascade for `uri_2021` with a generator added at
   `site_candidates.bus_id`, diff `customers_out` per county and per critical load against the
   factual run. **Achievable and the closing slide** — it is a function call into existing code,
   not new modelling.

The copilot cites all three through one tool, `causal_query`, and each answer carries the
method, the assumptions, and the interval so the LLM cannot round "estimate" up to "fact".

## Inputs

| Table / artifact | Used by | Columns |
|---|---|---|
| `data/parquet/outage_features.parquet` | C1, C2 | `county_fips, window_start, frac_out, y_out, gust_max, ice_sum_48h, temp_min_48h, precip_sum_72h, wildfire_hazard, WFIR_RISKS, nri_score, storm_event_*` |
| `eaglei_outages` + `county_customers` | C2 | restoration duration per event |
| `utility_reliability`, `utility_county` (spec 01 S16, P1) | C1 confounder, C2 treatment | `saidi_wo_med` by utility-year → county-year customer-weighted |
| `eia_plants` (spec 01 S3) | C2 treatment | `county_fips, capacity_mw, primary_fuel, operating_date` (`out_eia__yearly_plants`/generators) |
| `lines`, `buses` | C1 node `line_failures` (twin-derived) | tripped-line counts from `cascade_runs` when available |
| `cascade_runs` (spec 03) | C1 `line_failures`/`substation_loss`, C3 factual baseline | `run_id, scenario_id, hour, tripped_element_ids_json, counties_dark_json, critical_loads_lost_json` |
| `site_candidates`, `site_scores` (spec 04) | C3 | `site_id (str), bus_id, capacity_slot_mw` |
| `twin/cascade.py::run_scenario(scenario_id, seed, forced_out, net=…)` + `twin/net_cache/activsg2000.p` | C3 | spec 03; the `net=` override is the intervention hook |
| Reference PDFs in `copilot/corpus/` | citations | DOE coal-to-nuclear (2022, 2024), 10 CFR 100, EO 14299–14302 |

## Outputs

1. `causal/artifacts/outage_bn.bif` — the fitted pgmpy network (BIF format) + `outage_bn_cpds.json` (human-readable CPDs) + `bn_manifest.json` (discretisation cut-points, N, fit date).
2. Table `causal_attribution(county_fips, scenario_id, p_out_factual, p_out_weather_only, p_out_invest_only, share_weather, share_investment, method, fitted_at)`.
   Table `counterfactual_runs(cf_id, scenario_id, site_id TEXT, capacity_mw, factual_run_id, cf_run_id, customer_hours_avoided, peak_customers_avoided, critical_loads_kept JSON, created_at)` (item 4 below; DDL owned here).
3. `causal/artifacts/hardening_effect.json` — `{treatment, estimand, estimate, ci_low, ci_high, n_treated, n_control, method, refutations: {placebo_treatment, random_common_cause, subset}, caveats[]}` (one per treatment: `hardening_saidi`, `firm_generation_100mw`).
4. Table `counterfactual_runs(cf_id, scenario_id, site_id, capacity_mw, factual_run_id, cf_run_id, customer_hours_avoided, peak_customers_avoided, critical_loads_kept: JSON, created_at)`.
5. Tool `causal_query` in `copilot/tools/causal_query.py`.

## Algorithm or Design

### C1 — Bayesian network (`causal/bn.py`)

Nodes and discretisation (all categorical, cut-points saved in `bn_manifest.json`):

| Node | Source column(s) | States |
|---|---|---|
| `weather_severity` | max over window of standardised `gust_max`, `ice_sum_48h`, `-temp_min_48h`, `precip_sum_72h` (each mapped to 0–1 by the spec-02 heuristic clips) | `low / moderate / severe / extreme` (quartiles of the max on positive-storm windows) |
| `weather_type` | argmax of the same four | `wind / ice / cold / flood` |
| `exposure` | `WFIR_RISKS` + `wildfire_hazard` + tree-canopy proxy `[UNVERIFIED: no canopy layer in P0 → use NRI `WFIR` only]` | `low / med / high` (terciles) |
| `investment` | county-year `saidi_wo_med` 5-yr slope, customer-weighted (P1). P0 fallback: NRI `RESL_SCORE` community-resilience `[UNVERIFIED column present in NRI table]`, else a constant node marked `unobserved` | `improving / flat / worsening` |
| `line_failures` | from `cascade_runs`: count of tripped lines whose midpoint is in the county at the run's terminal step, per scenario; when no run exists for the window, latent → fitted by EM | `none / few / many` (0, 1–3, ≥4) |
| `substation_loss` | from `cascade_runs`: any de-energised bus in county | `no / yes` |
| `customers_out` | `frac_out` | `<5% / 5–20% / 20–50% / >50%` |

Edges: `weather_severity→line_failures`, `weather_type→line_failures`, `exposure→line_failures`,
`investment→line_failures`, `line_failures→substation_loss`, `substation_loss→customers_out`,
`line_failures→customers_out`, `investment→customers_out`, `weather_severity→customers_out`
(direct edge for generation-shortfall events like Uri, which is not a wires story).

Fitting: `pgmpy.models.DiscreteBayesianNetwork` (installed pgmpy 1.1.2: importing `pgmpy.models.BayesianNetwork` raises `ImportError: BayesianNetwork is deprecated`) + `model.fit(data, estimator=BayesianEstimator, prior_type='BDeu', equivalent_sample_size=10)`
on every `outage_features` row with a non-NULL label (TX 2021 + 2024 ≈ 600k rows; downsample
negatives 10:1 with weights). Latent `line_failures` (windows with no cascade run) uses
`pgmpy.estimators.ExpectationMaximization` `[UNVERIFIED: EM runtime on 60k rows — cap at 20 iterations, else fit only on windows with a cascade run]`.

Attribution query (per county, per scenario peak window), via `VariableElimination`:
- `p_factual = P(customers_out ≥ 5% | weather=w_obs, exposure=e_obs, investment=i_obs)`
- `p_weather_only = P(… | do(weather=w_obs), investment='improving', exposure=e_obs)` — what
  the county would face if it were a well-invested county under the same weather.
- `p_invest_only = P(… | do(weather='low'), investment=i_obs, exposure=e_obs)` — what its
  under-investment costs on an ordinary day.
- `share_investment = (p_factual − p_weather_only) / p_factual`, clipped [0,1];
  `share_weather = 1 − share_investment`. Written to `causal_attribution`.
- `do()` here is implemented as evidence on a graph with the incoming edges to the intervened
  node removed (`DiscreteBayesianNetwork.do(node)`; `pgmpy.inference.CausalInference` is the alternative), which is exact for this DAG.

Honesty ledger for C1: the graph is **hand-specified, not discovered**; `investment` is a proxy
(SAIDI trend, which is partly an *outcome* of weather — the confounder is imperfect and the
copilot must say "proxy for hardening"); `line_failures`/`substation_loss` come from the
synthetic twin, so the middle of the chain is model-derived, not observed.

### C2 — Effect estimate (`causal/effect.py`)

Unit: county × storm event. Outcome `duration_h` = hours from first window with `frac_out ≥ 5%`
to first subsequent window with `frac_out < 2%` (cap 240 h), and `peak_frac`. Built by
`causal/panel.py::build_event_panel` from `eaglei_outages` for every `storm_events` cluster
(county-days with a storm row, merged when < 24 h apart) 2018–2025 (P1) or 2021 + 2024 (P0,
too few events for a serious estimate — see ledger).

Treatments:
- `hardening_saidi`: county's customer-weighted `saidi_wo_med` fell ≥ 20% between 2018–2019 mean and 2022–2023 mean. Treatment year = 2021.
- `firm_generation_100mw`: county (or an adjacent county sharing a ≥ 230 kV bus in the twin) gained ≥ 100 MW of gas/nuclear/coal capacity with `operating_date` in 2019–2022 (EIA-860). Treatment year = the operating year.

Design: two-way fixed effects DiD on `log(1 + duration_h)` with county and event-severity-bin
fixed effects, weather controls (`gust_max, ice_sum_48h, temp_min_48h, precip_sum_72h`),
and **synthetic-control-style weights** for controls: for each treated county pick the 10 nearest
untreated counties in (pre-period mean duration, customers, `nri_score`, coastal, lat/lon) and
weight by inverse distance. Implemented with `dowhy.CausalModel(graph=…)` → `identify_effect()`
(backdoor) → `estimate_effect(method_name="backdoor.econml.dml.LinearDML", …)` with
`LightGBMRegressor` nuisance models, plus a plain `statsmodels` TWFE as the transparent check.
Refuters run and are stored: `placebo_treatment_refuter`, `random_common_cause`,
`data_subset_refuter`. Bootstrap CI (200 reps, county-clustered).

Reported claim format (the only form the copilot may use):
"Across N_t treated and N_c matched Texas counties 2018–2025, counties that [treatment] saw
storm restoration times [X%] shorter (95% CI [lo, hi]); placebo test p=[p]. This is an
observational estimate; treatment is a proxy for hardening."

### C3 — Counterfactual replay (`causal/counterfactual.py`)

```
factual  = cascade_runs rows for run_id = f"uri_2021-s{seed}-{sha8(∅)}"        (spec 03 output, cached)
net_cf   = pp.from_pickle("twin/net_cache/activsg2000.p"); pp.create_gen(net_cf, bus=<pp index of site.bus_id>,
              p_mw=capacity_mw, max_p_mw=capacity_mw, min_p_mw=capacity_mw*0.9, name=f"cf:{site_id}", type="nuclear")
cf       = twin.cascade.run_scenario("uri_2021", seed=<same seed>, forced_out=None, net=net_cf, write=False)
diff     = per county per hour: customers_out_factual − customers_out_cf (from counties_dark_json), integrated over hours
```
- Same `seed` → spec 03 draws weather failures from `default_rng(seed ^ hash(scenario_id, hour))`,
  so the element-failure draws are identical and the only difference is the added generator (a
  proper counterfactual under the twin's structural model: abduction = reuse the draws,
  action = `create_gen`, prediction = re-run). The cf rows are written to `cascade_runs` with
  `run_id = f"uri_2021-s{seed}-cf-{site_id}-{int(capacity_mw)}"` and `counterfactual_site_id = site_id`
  (00-overview amendment A1 convention `<scenario_id>-s<seed>-cf-<site_id>-<unit_mw>`; spec 04 writes the #1
  site's 1000 MW row under the same convention, so `precompute` must reuse rather than duplicate it) so the
  front end's playback layer can show both.
- `critical_loads_kept` = entries of the factual `critical_loads_lost_json` absent from the cf run, with `hour_lost`.
- Runs for the top-5 `site_scores` sites (`scenario_id='all'` ranking) at 300 MW and 1,000 MW;
  results cached in `counterfactual_runs` so the demo never waits on pandapower.
- `replay_with_hardening(line_ids, failure_multiplier)` builds `net_cf` by scaling those lines'
  fragility (spec 03 `FragilityParams` per-element override `[UNVERIFIED: a grep of spec 03 on 2026-09-05
  shows `FragilityParams` with no per-element multiplier field, so plan on the emulation path — raise
  `rate_a_mw` ×1.5 and remove the lines from the weather-failure candidate set — unless spec 03 adds one]`) — this is what makes Idea 3's screen (spec 08) causal rather than a ranking.

### Copilot citation contract (`copilot/tools/causal_query.py`)

`causal_query` is registered as a **seventh** tool in `copilot/tools/registry.py` (alongside the six
contract tools `predict_outage, run_cascade, score_site, top_lines, sql, cite` from 00-overview §2.4;
00-overview amendment A5 fixes those six signatures but does not list an additive seventh tool — the
overview owner must ratify this addition) with a 30 s timeout. It returns
`{answer_numbers: dict, method: str, assumptions: list[str], interval: [lo, hi] | None,
evidence_rows: list[dict], citations: list[{"source": str, "locator": str}]}`.
Spec 05's number-trace verifier already checks every numeral in the final text against tool
results, so `answer_numbers` and `evidence_rows` are the only places a causal number may come
from. Added system-prompt rules for this tool: every sentence using one of its numbers ends with
`[causal:<method>]`; `assumptions` are rendered as a "caveats" line; regulatory context still goes
through `cite` and the `[doc p.N]` format — `causal_query` never cites PDFs itself. `citations`
point at `causal_attribution` / `hardening_effect.json` / `counterfactual_runs` rows
(`locator` = primary key). If `interval` is present and crosses zero the LLM must say "not
distinguishable from zero".

## Interfaces (exact function signatures)

```python
# causal/bn.py
NODES: list[str]; EDGES: list[tuple[str, str]]
def discretise(features: pd.DataFrame, cuts: dict | None = None) -> tuple[pd.DataFrame, dict]: ...
def fit_bn(discrete: pd.DataFrame, latent: tuple[str, ...] = ("line_failures",),
           out_dir: str = "causal/artifacts") -> "pgmpy.models.DiscreteBayesianNetwork": ...
def load_bn(path: str = "causal/artifacts/outage_bn.bif") -> "pgmpy.models.DiscreteBayesianNetwork": ...
def attribute(bn, county_fips: str, scenario_id: str, con) -> dict: ...
# → {p_factual, p_out_weather_only, p_out_invest_only, share_weather, share_investment, evidence: dict}
def attribute_scenario(con, bn, scenario_id: str, states: tuple[str, ...] = ("TX",)) -> int: ...  # rows → causal_attribution

# causal/panel.py
def build_event_panel(con, states: tuple[str, ...], years: list[int],
                      onset_frac: float = 0.05, restored_frac: float = 0.02, cap_h: int = 240) -> pd.DataFrame: ...
# → county_fips, event_id, ts_onset, duration_h, peak_frac, gust_max, ice_sum_48h, temp_min_48h, precip_sum_72h, year
def label_treatments(con, panel: pd.DataFrame) -> pd.DataFrame: ...   # adds hardening_saidi, firm_generation_100mw, treat_year_*

# causal/effect.py
@dataclass
class EffectResult:
    treatment: str; estimand: str; estimate: float; ci_low: float; ci_high: float
    n_treated: int; n_control: int; method: str; refutations: dict; caveats: list[str]
def estimate_effect(panel: pd.DataFrame, treatment: Literal["hardening_saidi","firm_generation_100mw"],
                    outcome: Literal["log_duration_h","peak_frac"] = "log_duration_h",
                    k_controls: int = 10, n_boot: int = 200, seed: int = 7) -> EffectResult: ...
def write_effects(results: list[EffectResult], path: str = "causal/artifacts/hardening_effect.json") -> None: ...

# causal/counterfactual.py
def replay_with_site(con, scenario_id: str, site_id: str, capacity_mw: float,
                     seed: int = 0, factual_run_id: str | None = None) -> dict: ...
# → {cf_id, customer_hours_avoided, peak_customers_avoided, critical_loads_kept: list[{cl_id,name,kind,hour_lost_factual}],
#    per_county: list[{county_fips, factual_ch, cf_ch}], factual_run_id, cf_run_id}
def replay_with_hardening(con, scenario_id: str, line_ids: list[int], failure_multiplier: float = 0.2) -> dict: ...
def precompute(con, scenario_id: str = "uri_2021", top_n_sites: int = 5,
               capacities: tuple[float, ...] = (300.0, 1000.0)) -> int: ...      # rows → counterfactual_runs

# copilot/tools/causal_query.py
def causal_query(kind: Literal["attribution","effect","counterfactual"], county_fips: str | None = None,
                 scenario_id: str = "uri_2021", site_id: str | None = None, capacity_mw: float | None = None,
                 treatment: str | None = None) -> dict: ...
```

CLI: `uv run python -m causal.bn --fit --states TX`; `uv run python -m causal.bn --attribute uri_2021`;
`uv run python -m causal.effect --treatment hardening_saidi`; `uv run python -m causal.counterfactual --precompute uri_2021`.

## Acceptance criteria

1. `fit_bn` on TX 2021+2024 completes in < 10 min, writes `outage_bn.bif` that `load_bn` round-trips, and every CPD sums to 1 (pgmpy `check_model()` passes).
2. Sanity: `P(customers_out ≥ 5% | weather_severity='extreme') > 3 × P(… | 'low')` and `P(… | investment='worsening') ≥ P(… | 'improving')` holding weather fixed; both asserted in `causal/tests/test_bn.py`.
3. `causal_attribution` has 254 rows for `uri_2021`; `share_weather ≥ 0.7` for the median county (Uri was weather-dominated — if the model says otherwise it is wrong, not interesting); values in [0,1].
4. Under P0 (no EIA-861), `investment` is fitted as the NRI fallback or marked `unobserved`, and `causal_query("attribution")` returns `assumptions` containing the string "investment proxy: NRI community resilience" or "investment unobserved".
5. `build_event_panel` yields ≥ 300 county-events for TX 2021+2024 and ≥ 2,000 for P1 2018–2025; `duration_h` distribution median between 6 and 72 h.
6. `estimate_effect("hardening_saidi")` returns an `EffectResult` with all three refutations populated; if `n_treated < 15` the result's `caveats` includes "underpowered" and the copilot renders it as slideware ("illustrative estimate").
7. Placebo refuter's estimated effect is within the bootstrap CI of zero for at least one of the two treatments (if both fail, the effect JSON is written with `method="failed_refutation"` and the copilot refuses to quote a number).
8. `replay_with_site("uri_2021", top site, 1000)` runs in < 60 s on cached failure draws, and `customer_hours_avoided ≥ 0` for ≥ 4 of the top-5 sites (a site that makes things worse is reported, not hidden).
9. Determinism: running `replay_with_site` twice with the same `factual_run_id` yields identical `cf_run_id` results (same seed contract with spec 03).
10. `counterfactual_runs` has ≥ 10 rows (5 sites × 2 capacities) for `uri_2021` before the demo; at least one row has a non-empty `critical_loads_kept`.
11. `causal_query` responses validate against `copilot/schemas/causal_query.json`; a unit test asserts every number in `answer_numbers` appears in `evidence_rows` or `hardening_effect.json`.
12. Mutation probe: deleting `causal/artifacts/hardening_effect.json` makes `causal_query("effect")` return `{"answer_numbers": {}, "method": "unavailable"}` — the copilot must not hallucinate an effect (test in `causal/tests/test_tool_fail_closed.py`).

## Demo hook

Closing slide (demo step 4/5): the Uri factual outage map next to `counterfactual_runs` for site #1 at 1 GW — "same storm, this site online: Fort Hood stays green, X M customer-hours avoided" (the installation reverted from Fort Cavazos to Fort Hood on 11 June 2025; 00-overview uses "Fort Hood (Fort Cavazos)") — with the copilot answering "how much of Bell County's risk was weather vs under-investment?" from `causal_attribution` and quoting the hardening DiD only with its interval. The judges' policy question ("is this weather or neglect?") is answered by C1; the investment question ("does firm generation actually help?") by C3 first (twin, exact) and C2 second (history, noisy).

## Risks / unknowns — honest ledger

| Item | Weekend reality |
|---|---|
| C3 counterfactual replay | **Real.** Pure function of spec 03's `run_scenario(net=…)` + seeded `default_rng(seed ^ hash(scenario_id, hour))`; risk is only that the draw depends on the element set (adding a gen must not reorder the weather-failure candidates — spec 03 draws per element_id, so it should not). |
| C1 BN attribution | **Real but proxy-laden.** Graph hand-drawn; `investment` is SAIDI trend (P1) or NRI resilience (P0); middle nodes come from the synthetic twin. Present as "structural model, not discovered causality". |
| C1 EM for latent `line_failures` | `[UNVERIFIED runtime]` — fallback is fitting only on windows with cascade runs (fewer rows, still fine for the demo). |
| C2 DiD / synthetic control | **Estimate with a wide interval at best.** With P0 data (2 years, TX) it is *slideware with a number attached*; needs EIA-861 (P1) and 2018–2025 EAGLE-I to be a defensible claim. Treatment proxies (SAIDI improvement, capacity additions) are confounded by the very storms we study; refuters are reported, not hidden. Do not put a point estimate on a slide without the CI. |
| "Historically, adding firm generation near X reduced restoration time by Y" | Only quotable if AC 6–7 pass; otherwise the sentence is replaced by the C3 twin number, which is what we actually control. |
| Grid2Op operator agent | Out of scope for this spec (stretch in spec 03). |
| pgmpy / dowhy / econml install weight | Already resolved in `uv.lock` (introspected 2026-09-05): `dowhy 0.14`, `econml 0.17.0`, `pgmpy 1.1.2`, `gridstatus 0.36.0`. `CausalModel.estimate_effect(method_name="backdoor.econml.dml.LinearDML")`, `refute_estimate(method_name="placebo_treatment_refuter" / "random_common_cause" / "data_subset_refuter")`, `pgmpy.estimators.{BayesianEstimator, ExpectationMaximization}`, `pgmpy.inference.VariableElimination`, `pgmpy.readwrite.BIFWriter` all exist. If econml fails at runtime, the `statsmodels` TWFE path is the deliverable and `method="twfe_only"`. |

## Weekend time-box (hours)

| Task | Hours |
|---|---|
| C3 `replay_with_site` + `precompute` + `counterfactual_runs` (Day 2 morning, right after spec 03 lands) | 2.0 |
| C1 discretise + fit + attribution table + tests | 2.5 |
| `causal_query` tool + fail-closed tests + schema | 1.0 |
| C2 panel + TWFE (statsmodels) + bootstrap | 2.0 |
| C2 DoWhy/EconML + refuters (only if P1 data present) | 1.5 (stretch) |
| Slide: factual vs counterfactual maps + attribution bar | 1.0 |
| **Total** | **8.5 core + 1.5 stretch** |
