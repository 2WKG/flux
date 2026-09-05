"""Canonical analytical views and versioned dashboard/EDA metric definitions."""

from __future__ import annotations

from dataclasses import dataclass

import duckdb

from pipelines.db import SCHEMA_VERSION, validate_schema


METRIC_LAYER_VERSION = "1.0.0"


@dataclass(frozen=True)
class MetricDefinition:
    """A stable KPI definition shared by dashboard and notebook consumers."""

    name: str
    version: str
    view: str
    grain: str
    numerator: str
    denominator: str
    unit: str
    filters: str
    aggregation: str
    timezone: str
    lineage: str


METRIC_VIEWS = {
    "outage_county_prediction_windows": "metric_outage_county_prediction_windows",
    "cascade_run_hours": "metric_cascade_run_hours",
    "site_scorecards": "metric_site_scorecards",
}


METRIC_DEFINITIONS = (
    MetricDefinition(
        name="outage_customers_at_risk",
        version=METRIC_LAYER_VERSION,
        view=METRIC_VIEWS["outage_county_prediction_windows"],
        grain="one scenario, county, and six-hour prediction-window start",
        numerator="customers_at_risk",
        denominator="not applicable; this is a modeled count of customer accounts",
        unit="customer accounts",
        filters="scenario_id and prediction_window_start_utc are required before aggregation; optional county_fips, state, and driver",
        aggregation="sum only across counties in one selected scenario and prediction window; never sum across windows",
        timezone="UTC",
        lineage="outage_predictions → metric_outage_county_prediction_windows",
    ),
    MetricDefinition(
        name="outage_probability",
        version=METRIC_LAYER_VERSION,
        view=METRIC_VIEWS["outage_county_prediction_windows"],
        grain="one scenario, county, and six-hour prediction-window start",
        numerator="p_out (already a probability)",
        denominator="not applicable",
        unit="probability (0-1)",
        filters="scenario_id, prediction_window_start_utc, county_fips, state, and driver",
        aggregation="row-level only; do not sum or average across counties or prediction windows",
        timezone="UTC",
        lineage="outage_predictions → metric_outage_county_prediction_windows",
    ),
    MetricDefinition(
        name="cascade_lost_load_mw",
        version=METRIC_LAYER_VERSION,
        view=METRIC_VIEWS["cascade_run_hours"],
        grain="one persisted cascade run and hour offset",
        numerator="lost_load_mw",
        denominator="not applicable; this is a simulated power snapshot",
        unit="MW",
        filters="scenario_id, run_id, hour, snapshot_ts_utc, and counterfactual_site_id",
        aggregation="use one (run_id, hour), or choose the latest hour per run; never sum snapshots across hours or runs",
        timezone="UTC",
        lineage="cascade_runs → metric_cascade_run_hours",
    ),
    MetricDefinition(
        name="site_lol_reduction_mwh",
        version=METRIC_LAYER_VERSION,
        view=METRIC_VIEWS["site_scorecards"],
        grain="one candidate site, scenario scope, and unit size",
        numerator="lol_reduction_mwh",
        denominator="not applicable; this is a stored counterfactual delta",
        unit="MWh",
        filters="site_id, scenario_id, unit_mw, site_kind, county_fips, and state",
        aggregation="row-level comparison only; never sum alternative sites, scenarios, or unit sizes",
        timezone="not applicable",
        lineage="site_scores → metric_site_scorecards",
    ),
    MetricDefinition(
        name="site_grid_value_score",
        version=METRIC_LAYER_VERSION,
        view=METRIC_VIEWS["site_scorecards"],
        grain="one candidate site, scenario scope, and unit size",
        numerator="grid_value_score",
        denominator="not applicable; the source model stores a 0-100 score",
        unit="score (0-100)",
        filters="site_id, scenario_id, unit_mw, site_kind, county_fips, and state",
        aggregation="row-level ranking only; never average or sum alternative sites, scenarios, or unit sizes",
        timezone="not applicable",
        lineage="site_scores → metric_site_scorecards",
    ),
)


VIEW_STATEMENTS = (
    """CREATE OR REPLACE VIEW metric_outage_county_prediction_windows AS
        SELECT
            prediction.scenario_id,
            scenario.name AS scenario_name,
            scenario.kind AS scenario_kind,
            prediction.county_fips,
            county.name AS county_name,
            county.state,
            prediction.ts AS prediction_window_start_utc,
            prediction.p_out AS outage_probability,
            prediction.customers_at_risk,
            prediction.driver,
            prediction.source_name AS prediction_source_name,
            prediction.source_ref AS prediction_source_ref,
            prediction.source_version AS prediction_source_version,
            prediction.source_retrieved_at AS prediction_source_retrieved_at,
            prediction.fixture_batch_id AS prediction_fixture_batch_id
        FROM outage_predictions AS prediction
        INNER JOIN scenarios AS scenario USING (scenario_id)
        INNER JOIN counties AS county USING (county_fips)""",
    """CREATE OR REPLACE VIEW metric_cascade_run_hours AS
        SELECT
            cascade.run_id,
            cascade.scenario_id,
            scenario.name AS scenario_name,
            scenario.kind AS scenario_kind,
            cascade.hour,
            scenario.ts_start + cascade.hour * INTERVAL 1 HOUR AS snapshot_ts_utc,
            cascade.lost_load_mw,
            cascade.tripped_element_ids_json,
            cascade.counties_dark_json,
            cascade.critical_loads_lost_json,
            cascade.counterfactual_site_id,
            counterfactual_site.name AS counterfactual_site_name,
            cascade.source_name AS cascade_source_name,
            cascade.source_ref AS cascade_source_ref,
            cascade.source_version AS cascade_source_version,
            cascade.source_retrieved_at AS cascade_source_retrieved_at,
            cascade.fixture_batch_id AS cascade_fixture_batch_id
        FROM cascade_runs AS cascade
        INNER JOIN scenarios AS scenario USING (scenario_id)
        LEFT JOIN site_candidates AS counterfactual_site
            ON cascade.counterfactual_site_id = counterfactual_site.site_id""",
    """CREATE OR REPLACE VIEW metric_site_scorecards AS
        SELECT
            score.site_id,
            site.name AS site_name,
            site.kind AS site_kind,
            site.county_fips,
            county.name AS county_name,
            county.state,
            score.scenario_id,
            CASE WHEN score.scenario_id = 'all' THEN 'all_scenarios' ELSE 'scenario' END
                AS scenario_scope,
            scenario.name AS scenario_name,
            scenario.kind AS scenario_kind,
            score.unit_mw,
            score.safety_score,
            score.safety_flags_json,
            score.grid_value_score,
            score.lol_reduction_mwh,
            score.congestion_relief_pct,
            score.blackstart_reach_mw,
            score.source_name AS score_source_name,
            score.source_ref AS score_source_ref,
            score.source_version AS score_source_version,
            score.source_retrieved_at AS score_source_retrieved_at,
            score.fixture_batch_id AS score_fixture_batch_id
        FROM site_scores AS score
        INNER JOIN site_candidates AS site USING (site_id)
        INNER JOIN counties AS county USING (county_fips)
        LEFT JOIN scenarios AS scenario ON score.scenario_id = scenario.scenario_id""",
)


def _require_contract(con: duckdb.DuckDBPyConnection) -> None:
    """Reject a missing or incompatible fixture schema before creating views."""
    try:
        version = con.execute(
            "SELECT value FROM schema_meta WHERE key = 'contract_version'"
        ).fetchone()
    except duckdb.CatalogException as exc:
        raise RuntimeError(
            "Metric layer requires the versioned Flux fixture schema; run ensure_schema first."
        ) from exc
    if version is None or version[0] != SCHEMA_VERSION:
        actual = None if version is None else version[0]
        raise RuntimeError(
            f"Metric layer requires DuckDB contract {SCHEMA_VERSION!r}, found {actual!r}."
        )
    validate_schema(con)


def install_metric_layer(con: duckdb.DuckDBPyConnection) -> None:
    """Install or refresh the canonical read-only analytical views."""
    _require_contract(con)
    con.execute("BEGIN TRANSACTION")
    try:
        for statement in VIEW_STATEMENTS:
            con.execute(statement)
    except Exception:
        con.execute("ROLLBACK")
        raise
    else:
        con.execute("COMMIT")


def metric_view(name: str) -> str:
    """Resolve a public metric-view name without accepting caller-provided SQL."""
    try:
        return METRIC_VIEWS[name]
    except KeyError as exc:
        available = ", ".join(sorted(METRIC_VIEWS))
        raise ValueError(f"Unknown metric view {name!r}; choose one of {available}.") from exc


def metric_query(name: str) -> str:
    """Return the shared query shape used by dashboard and notebook consumers."""
    return f"SELECT * FROM {metric_view(name)}"
