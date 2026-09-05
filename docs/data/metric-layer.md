# Canonical analytical model and metric layer

**Metric-layer version:** `1.0.0`
**Fixture-contract dependency:** `pipelines.db.SCHEMA_VERSION == 1.0.0`

This layer gives the dashboard and notebooks the same three read-only DuckDB
views. It reconciles the executable fixture contract from
[`docs/specs/10-duckdb-contract.md`](../specs/10-duckdb-contract.md); it does
not add tables or replace the ingest, model, cascade, or siting owners.

## Canonical entities, facts, and grain

| Role | Canonical table | Identity / grain | Used by metric view |
| --- | --- | --- | --- |
| Dimension | `counties` | `county_fips` | outage and site scorecards |
| Dimension | `scenarios` | `scenario_id` | outage, cascade, and site scorecards; `site_scores.scenario_id='all'` deliberately has no scenario dimension row |
| Dimension | `site_candidates` | `site_id` | site scorecards and cascade counterfactual label |
| Fact | `outage_predictions` | `scenario_id`, `county_fips`, six-hour-window `ts` | `metric_outage_county_prediction_windows` |
| Fact | `cascade_runs` | `run_id`, hour offset | `metric_cascade_run_hours` |
| Fact | `site_scores` | `site_id`, `scenario_id`, `unit_mw` | `metric_site_scorecards` |

The views join only on the contract keys: prediction → scenario and county;
cascade → scenario and optional counterfactual site; score → site → county and
optional scenario. `scenario_id='all'` remains an explicit aggregate scope in
`metric_site_scorecards`: `scenario_scope='all_scenarios'`, and the scenario
name and kind are `NULL`. It is never an unknown scenario.

## Curated views

| Public name | DuckDB view | Grain | Core question |
| --- | --- | --- | --- |
| `outage_county_prediction_windows` | `metric_outage_county_prediction_windows` | scenario × county × prediction-window start | Where is outage risk? |
| `cascade_run_hours` | `metric_cascade_run_hours` | run × hour offset | What does a selected cascade state lose? |
| `site_scorecards` | `metric_site_scorecards` | site × scenario scope × unit MW | Where does a selected firm unit provide value? |

Views retain fact provenance (`source_name`, `source_ref`, `source_version`,
`source_retrieved_at`, and `fixture_batch_id`) under a fact-specific prefix.
That is the runtime lineage from a source record or derived producer through a
curated fact into the view. The source registry and raw artifact remain the
authoritative upstream evidence, as described in
[`data/sources/ingest/README.md`](../../data/sources/ingest/README.md).

## Versioned KPI definitions

The machine-readable registry is `pipelines.metrics.METRIC_DEFINITIONS`. These
are all KPIs released by metric layer 1.0.0; no consumer should invent a join
or change the aggregation rule.

| KPI | Unit | Numerator / denominator | Filters | Aggregation | Time zone | Lineage |
| --- | --- | --- | --- | --- | --- | --- |
| `outage_customers_at_risk` | Customer accounts | `customers_at_risk` / not applicable | Require `scenario_id` and `prediction_window_start_utc`; optional county, state, driver | Sum across counties only within one selected scenario/window; never across windows | UTC | `outage_predictions` → outage view |
| `outage_probability` | Probability (0–1) | `p_out` / not applicable | Scenario, prediction-window start, county, state, driver | Row-level only; never sum or average | UTC | `outage_predictions` → outage view |
| `cascade_lost_load_mw` | MW | `lost_load_mw` / not applicable | Scenario, run, hour, snapshot timestamp, counterfactual site | One run/hour, or latest hour per run; never sum snapshots | UTC | `cascade_runs` → cascade view |
| `site_lol_reduction_mwh` | MWh | `lol_reduction_mwh` / not applicable | Site, scenario scope, unit MW, kind, county, state | Row-level comparison only; never sum alternatives | Not applicable | `site_scores` → scorecard view |
| `site_grid_value_score` | Score (0–100) | `grid_value_score` / not applicable | Site, scenario scope, unit MW, kind, county, state | Row-level ranking only; never average or sum alternatives | Not applicable | `site_scores` → scorecard view |

`outage_predictions.ts` starts a six-hour prediction window. It is therefore
called `prediction_window_start_utc`, not an hourly timestamp. The metric layer
does not turn a risk prediction into observed customers out. `cascade_runs.hour`
is an offset from the scenario start, and the view exposes its UTC timestamp
only for display and filtering.

## Consumer contract

Initialize the fixture schema, install views, then ask the public helper for a
view query. The helper accepts only registered names and returns a fixed
`SELECT *` query, so dashboard and notebook callers have no join text to copy.

```python
from pipelines.db import connect, ensure_schema
from pipelines.metrics import install_metric_layer, metric_query

con = connect("data/duck/grid.duckdb")
ensure_schema(con)
install_metric_layer(con)
rows = con.execute(metric_query("outage_county_prediction_windows")).fetchall()
```

`install_metric_layer()` checks the exact fixture contract version and schema
before issuing only `CREATE OR REPLACE VIEW` statements. A missing or different
contract fails explicitly; migration remains the contract owner’s responsibility.
