"""Reproducible exploratory data analysis over the canonical metric layer.

The workflow is deliberately parameterized and read-mostly: it profiles the
released KPI columns, measures missingness, correlates measures inside one
view, segments them by contract dimensions, looks for period-over-period
change, and ranks anomaly and data-quality candidates by impact.

Every number is traced back to a released KPI in :mod:`pipelines.metrics`; this
module invents no metric, no join, and no aggregation rule.  A statistic that
cannot be computed is reported as an explicit unavailable status with a reason,
never as a zero or a default.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb

from pipelines.db import SCHEMA_VERSION
from pipelines.metrics import (
    METRIC_DEFINITIONS,
    METRIC_LAYER_VERSION,
    install_metric_layer,
    metric_view,
)

EDA_VERSION = "1.0.0"

# Iglewicz-Hoaglin modified z-score constants and threshold.  The mean-absolute
# deviation form is the documented fallback for a discrete measure whose median
# absolute deviation collapses to zero.
ROBUST_Z_CONSTANT = 0.6745
MEAN_AD_Z_CONSTANT = 0.7979
ROBUST_Z_THRESHOLD = 3.5
HIGH_SEVERITY_Z = 5.0

FLOAT_SIGNIFICANT_DIGITS = 12

MIN_CORRELATION_ROWS = 30
MIN_ROBUST_ROWS = 8
MIN_CHANGE_POINTS = 3
MAX_OUTLIERS_PER_MEASURE = 5
MAX_SEGMENTS_PER_DIMENSION = 20

# Released KPI -> column in its metric view.  Analysing only released KPIs is
# what keeps a finding traceable; unreleased view columns are left alone.
MEASURE_COLUMNS = {
    "outage_customers_at_risk": "customers_at_risk",
    "outage_probability": "outage_probability",
    "cascade_lost_load_mw": "lost_load_mw",
    "site_lol_reduction_mwh": "lol_reduction_mwh",
    "site_grid_value_score": "grid_value_score",
}

_DEFINITIONS = {definition.name: definition for definition in METRIC_DEFINITIONS}
if set(MEASURE_COLUMNS) != set(_DEFINITIONS):
    raise RuntimeError(
        "EDA measures drifted from pipelines.metrics.METRIC_DEFINITIONS; "
        "update MEASURE_COLUMNS before running the workflow."
    )


@dataclass(frozen=True)
class ViewProfile:
    """Contract grain and dimensions the EDA is allowed to use for one view."""

    grain: tuple[str, ...]
    dimensions: tuple[str, ...]
    time_column: str | None
    series_key: tuple[str, ...]


EDA_PROFILES = {
    "outage_county_prediction_windows": ViewProfile(
        grain=("scenario_id", "county_fips", "prediction_window_start_utc"),
        dimensions=("state", "driver", "scenario_kind"),
        time_column="prediction_window_start_utc",
        series_key=("scenario_id", "county_fips"),
    ),
    "cascade_run_hours": ViewProfile(
        grain=("run_id", "hour"),
        dimensions=("scenario_kind", "scenario_id"),
        time_column="snapshot_ts_utc",
        series_key=("run_id",),
    ),
    "site_scorecards": ViewProfile(
        grain=("site_id", "scenario_id", "unit_mw"),
        dimensions=("state", "site_kind", "scenario_scope"),
        time_column=None,
        series_key=(),
    ),
}

FOLLOW_UPS = {
    "no_rows": "Which producer still owes rows for {view}, and is the gap a failed run or an unloaded release?",
    "missing_measure": "Why is {metric} missing for part of {view}, and should those rows be withheld from the dashboard?",
    "zero_variance": "Is {metric} genuinely constant in {view}, or is a producer writing a placeholder value?",
    "anomaly_candidate": "Does the extreme {metric} value at {evidence} reflect a real stress case or an input error?",
    "level_shift": "What happened between the {metric} snapshots at {evidence} to move the series that far in one step?",
}

RECOMMENDED_ACTIONS = {
    "no_rows": "Load or rerun the producer for this view before publishing any dashboard panel that reads it.",
    "missing_measure": "Repair the producer or label the affected rows unavailable; do not read a missing measure as zero.",
    "zero_variance": "Confirm the constant with the metric owner before segmenting or ranking on it.",
    "anomaly_candidate": "Review the flagged row against its source record and either confirm the stress case or fix the input.",
    "level_shift": "Review the two adjacent snapshots against the scenario timeline before quoting either value.",
}


class MissingMetricViewsError(RuntimeError):
    """The artifact lacks canonical metric views and the run was not allowed to install them."""

    status = "metric_views_missing"

    def __init__(self, missing: list[str]) -> None:
        self.missing = missing
        super().__init__(
            f"Canonical metric views are missing: {', '.join(missing)}. "
            "Rerun with install_views=True (CLI: --install-views) against a writable artifact, "
            "or run pipelines.metrics.install_metric_layer first."
        )


# Topology label is derived from the artifact's own ingest log, never assumed:
# ``pipelines.activsg.log_artifact`` records the ACTIVSg2000 case under this source.
SYNTHETIC_TOPOLOGY_SOURCES = {"activsg2000": "synthetic ACTIVSg2000"}


def _measures_for(public_view: str) -> tuple[tuple[str, str], ...]:
    """Return the ``(kpi_name, column)`` pairs released for one metric view."""
    physical = metric_view(public_view)
    return tuple(
        (name, MEASURE_COLUMNS[name])
        for name in sorted(MEASURE_COLUMNS)
        if _DEFINITIONS[name].view == physical
    )


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _scope(public_view: str, scenario_id: str | None) -> tuple[str, list[Any]]:
    """Build the read-only scope subquery; names come from the frozen registry."""
    sql = f"SELECT * FROM {metric_view(public_view)}"
    params: list[Any] = []
    if scenario_id is not None:
        sql += " WHERE scenario_id = ?"
        params.append(scenario_id)
    return f"({sql})", params


def _json_safe(value: Any) -> Any:
    """Normalize a DuckDB value for a report that must compare equal across runs.

    Floats are rounded to :data:`FLOAT_SIGNIFICANT_DIGITS`: DuckDB's parallel
    aggregation may reorder a floating-point sum, so an unchanged artifact can
    otherwise produce last-place differences between two runs.
    """
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        value = float(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return float(f"{value:.{FLOAT_SIGNIFICANT_DIGITS}g}")
    if isinstance(value, (bytes, bytearray, memoryview)):
        return f"<{len(bytes(value))} bytes>"
    return value


def _columns(con: duckdb.DuckDBPyConnection, public_view: str) -> list[str]:
    return [
        row[0] for row in con.execute(f"DESCRIBE {metric_view(public_view)}").fetchall()
    ]


def _require_views(con: duckdb.DuckDBPyConnection, public_views: list[str]) -> None:
    present = {
        row[0] for row in con.execute("SELECT view_name FROM duckdb_views()").fetchall()
    }
    missing = sorted(
        metric_view(name) for name in public_views if metric_view(name) not in present
    )
    if missing:
        raise MissingMetricViewsError(missing)


def _topology(con: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    """Report the network topology the artifact was built on, from ``ingest_log``."""
    tables = {
        row[0]
        for row in con.execute("SELECT table_name FROM duckdb_tables()").fetchall()
    }
    if "ingest_log" not in tables:
        return {
            "status": "unavailable",
            "reason": "The artifact has no ingest_log table.",
            "label": None,
        }
    placeholders = ", ".join("?" for _ in SYNTHETIC_TOPOLOGY_SOURCES)
    rows = con.execute(
        f"""SELECT source, source_release, source_file FROM ingest_log
            WHERE source IN ({placeholders}) ORDER BY source, source_release, source_file""",
        list(SYNTHETIC_TOPOLOGY_SOURCES),
    ).fetchall()
    if not rows:
        return {
            "status": "unavailable",
            "reason": "ingest_log records no topology case load; the network source is unknown.",
            "label": None,
        }
    source, release, source_file = rows[0]
    return {
        "status": "ok",
        "label": SYNTHETIC_TOPOLOGY_SOURCES[source],
        "synthetic": True,
        "source": source,
        "source_release": release,
        "source_file": source_file,
    }


def _provenance(
    con: duckdb.DuckDBPyConnection, base: str, params: list[Any], columns: list[str]
) -> dict[str, Any]:
    """Surface the scenario kinds and sources of record behind the rows in scope."""
    source_columns = [column for column in columns if column.endswith("_source_name")]
    provenance: dict[str, Any] = {"scenario_kinds": [], "source_names": []}
    if "scenario_kind" in columns:
        provenance["scenario_kinds"] = [
            row[0]
            for row in con.execute(
                f"SELECT DISTINCT scenario_kind FROM {base} WHERE scenario_kind IS NOT NULL "
                "ORDER BY scenario_kind",
                params,
            ).fetchall()
        ]
    for column in source_columns:
        quoted = _quote(column)
        provenance["source_names"] += [
            row[0]
            for row in con.execute(
                f"SELECT DISTINCT {quoted} FROM {base} WHERE {quoted} IS NOT NULL ORDER BY {quoted}",
                params,
            ).fetchall()
        ]
    provenance["source_names"] = sorted(set(provenance["source_names"]))
    return provenance


def _robust_stats(
    con: duckdb.DuckDBPyConnection, base: str, params: list[Any], expr: str
) -> dict[str, Any]:
    """Profile one numeric expression, including a median-absolute-deviation scale."""
    row = con.execute(
        f"""SELECT count(*), count({expr}), min({expr}), max({expr}), avg({expr}),
                   stddev_samp({expr}), median({expr}),
                   quantile_cont({expr}, 0.1), quantile_cont({expr}, 0.9)
            FROM {base}""",
        params,
    ).fetchone()
    stats = {
        "rows": row[0],
        "non_null": row[1],
        "null_fraction": None if row[0] == 0 else round((row[0] - row[1]) / row[0], 6),
        "min": _json_safe(row[2]),
        "max": _json_safe(row[3]),
        "mean": _json_safe(row[4]),
        "stddev": _json_safe(row[5]),
        "median": _json_safe(row[6]),
        "p10": _json_safe(row[7]),
        "p90": _json_safe(row[8]),
        "mad": None,
        "mean_abs_deviation": None,
    }
    if row[1]:
        deviations = con.execute(
            f"""SELECT median(abs({expr} - ?)), avg(abs({expr} - ?))
                FROM {base} WHERE {expr} IS NOT NULL""",
            [row[6], row[6], *params],
        ).fetchone()
        stats["mad"] = _json_safe(deviations[0])
        stats["mean_abs_deviation"] = _json_safe(deviations[1])
    return stats


def _outliers(
    con: duckdb.DuckDBPyConnection,
    base: str,
    params: list[Any],
    expr: str,
    keys: tuple[str, ...],
    stats: dict[str, Any],
    *,
    threshold: float,
    limit: int,
) -> dict[str, Any]:
    """Flag modified-z outliers, or state why the test could not run."""
    if stats["non_null"] < MIN_ROBUST_ROWS:
        return {
            "status": "insufficient_rows",
            "reason": f"{stats['non_null']} non-null value(s); {MIN_ROBUST_ROWS} required.",
            "scale": None,
            "candidates": [],
        }
    if stats["mad"]:
        scale, constant, spread = "mad", ROBUST_Z_CONSTANT, stats["mad"]
    elif stats["mean_abs_deviation"]:
        scale, constant, spread = (
            "mean_abs_deviation",
            MEAN_AD_Z_CONSTANT,
            stats["mean_abs_deviation"],
        )
    else:
        return {
            "status": "unavailable",
            "reason": "Every value equals the median; a robust scale is undefined.",
            "scale": None,
            "candidates": [],
        }

    median = stats["median"]
    selected = ", ".join(_quote(key) for key in keys)
    rows = con.execute(
        f"""SELECT {selected}, {expr},
                   {constant} * ({expr} - ?) / ? AS robust_z
            FROM {base}
            WHERE {expr} IS NOT NULL
              AND abs({constant} * ({expr} - ?) / ?) >= ?
            ORDER BY abs(robust_z) DESC, {selected}
            LIMIT {limit}""",
        [median, spread, *params, median, spread, threshold],
    ).fetchall()
    candidates = [
        {
            "keys": {key: _json_safe(value) for key, value in zip(keys, row)},
            "value": _json_safe(row[len(keys)]),
            "robust_z": round(row[len(keys) + 1], 4),
        }
        for row in rows
    ]
    return {"status": "ok", "reason": None, "scale": scale, "candidates": candidates}


def _correlations(
    con: duckdb.DuckDBPyConnection,
    base: str,
    params: list[Any],
    measures: tuple[tuple[str, str], ...],
    min_rows: int,
) -> list[dict[str, Any]]:
    """Correlate released KPIs inside one view; never across views or grains."""
    results = []
    for index, (left_name, left_column) in enumerate(measures):
        for right_name, right_column in measures[index + 1 :]:
            left, right = _quote(left_column), _quote(right_column)
            rows, correlation = con.execute(
                f"""SELECT count(*), corr({left}, {right}) FROM {base}
                    WHERE {left} IS NOT NULL AND {right} IS NOT NULL""",
                params,
            ).fetchone()
            entry: dict[str, Any] = {
                "x": left_name,
                "y": right_name,
                "pairwise_rows": rows,
            }
            if rows < min_rows:
                entry |= {
                    "status": "insufficient_rows",
                    "reason": f"{rows} paired row(s); {min_rows} required.",
                    "pearson_r": None,
                }
            elif correlation is None or not math.isfinite(correlation):
                entry |= {
                    "status": "undefined",
                    "reason": "At least one measure has zero variance.",
                    "pearson_r": None,
                }
            else:
                entry |= {
                    "status": "ok",
                    "reason": None,
                    "pearson_r": round(correlation, 4),
                }
            results.append(entry)
    return results


def _segments(
    con: duckdb.DuckDBPyConnection,
    base: str,
    params: list[Any],
    dimension: str,
    column: str,
) -> dict[str, Any]:
    """Describe a measure per contract dimension without breaking aggregation rules."""
    dim, measure = _quote(dimension), _quote(column)
    rows = con.execute(
        f"""SELECT {dim}, count(*), count({measure}), median({measure}), min({measure}), max({measure})
            FROM {base} GROUP BY {dim}
            ORDER BY count(*) DESC, {dim}
            LIMIT {MAX_SEGMENTS_PER_DIMENSION + 1}""",
        params,
    ).fetchall()
    return {
        "truncated": len(rows) > MAX_SEGMENTS_PER_DIMENSION,
        "segments": [
            {
                "segment": _json_safe(row[0]),
                "rows": row[1],
                "non_null": row[2],
                "median": _json_safe(row[3]),
                "min": _json_safe(row[4]),
                "max": _json_safe(row[5]),
            }
            for row in rows[:MAX_SEGMENTS_PER_DIMENSION]
        ],
    }


def _changes(
    con: duckdb.DuckDBPyConnection,
    base: str,
    params: list[Any],
    profile: ViewProfile,
    column: str,
    threshold: float,
) -> dict[str, Any]:
    """Analyse successive change within a series, never across unrelated series."""
    if profile.time_column is None:
        return {
            "status": "not_applicable",
            "reason": "This view has no time grain.",
            "series_analysed": 0,
            "scale": None,
            "stats": None,
            "candidates": [],
        }

    measure, time_column = _quote(column), _quote(profile.time_column)
    partition = ", ".join(_quote(key) for key in profile.series_key)
    keys = (*profile.series_key, profile.time_column)
    eligible = con.execute(
        f"""SELECT count(*) FROM (
                SELECT 1 FROM {base} WHERE {measure} IS NOT NULL
                GROUP BY {partition} HAVING count(*) >= {MIN_CHANGE_POINTS})""",
        params,
    ).fetchone()[0]
    if not eligible:
        return {
            "status": "insufficient_rows",
            "reason": f"No series has the {MIN_CHANGE_POINTS} points required for change analysis.",
            "series_analysed": 0,
            "scale": None,
            "stats": None,
            "candidates": [],
        }

    # Only series that met the eligibility count contribute deltas: a shorter
    # series must neither inflate the pooled scale nor emit a level_shift.
    lagged = f"""(SELECT {", ".join(_quote(key) for key in keys)},
                    {measure} - lag({measure}) OVER (PARTITION BY {partition} ORDER BY {time_column}) AS delta
             FROM {base}
             QUALIFY count({measure}) OVER (PARTITION BY {partition}) >= {MIN_CHANGE_POINTS})"""
    stats = _robust_stats(con, lagged, params, "delta")
    outliers = _outliers(
        con,
        lagged,
        params,
        "delta",
        keys,
        stats,
        threshold=threshold,
        limit=MAX_OUTLIERS_PER_MEASURE,
    )
    return {
        "status": outliers["status"],
        "reason": outliers["reason"],
        "series_analysed": eligible,
        "scale": outliers["scale"],
        "stats": stats,
        "candidates": outliers["candidates"],
    }


def _evidence_label(evidence: dict[str, Any]) -> str:
    keys = evidence.get("keys")
    if not keys:
        return "the flagged rows"
    return ", ".join(f"{key}={value}" for key, value in keys.items())


def _finding(
    code: str,
    view: str,
    metric: str,
    description: str,
    *,
    severity: str,
    impact: float,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    """Attach KPI lineage so every finding is traceable to the metric layer."""
    definition = _DEFINITIONS[metric]
    return {
        "code": code,
        "severity": severity,
        "impact": round(impact, 4),
        "metric_view": view,
        "metric": metric,
        "metric_version": METRIC_LAYER_VERSION,
        "lineage": definition.lineage,
        "unit": definition.unit,
        "description": description,
        "evidence": evidence,
        "recommended_action": RECOMMENDED_ACTIONS[code],
        "follow_up_question": FOLLOW_UPS[code].format(
            view=view, metric=metric, evidence=_evidence_label(evidence)
        ),
    }


def _analyse_view(
    con: duckdb.DuckDBPyConnection,
    public_view: str,
    profile: ViewProfile,
    scenario_id: str | None,
    *,
    threshold: float,
    min_correlation_rows: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    base, params = _scope(public_view, scenario_id)
    measures = _measures_for(public_view)
    row_count = con.execute(f"SELECT count(*) FROM {base}", params).fetchone()[0]
    findings: list[dict[str, Any]] = []

    if row_count == 0:
        findings.append(
            _finding(
                "no_rows",
                public_view,
                measures[0][0],
                f"{public_view} has no rows in scope; every KPI it releases is unavailable, not zero.",
                severity="high",
                impact=1.0,
                evidence={"scenario_id": scenario_id, "rows": 0},
            )
        )
        return (
            {
                "status": "no_rows",
                "rows": 0,
                "scenario_id": scenario_id,
                "measures": [name for name, _ in measures],
                "missingness": {},
                "profiles": {},
                "correlations": [],
                "provenance": {"scenario_kinds": [], "source_names": []},
            },
            findings,
        )

    columns = _columns(con, public_view)
    missing_sql = ", ".join(
        f"sum(CASE WHEN {_quote(column)} IS NULL THEN 1 ELSE 0 END)"
        for column in columns
    )
    missing_row = con.execute(f"SELECT {missing_sql} FROM {base}", params).fetchone()
    missingness = {
        column: round(value / row_count, 6)
        for column, value in zip(columns, missing_row)
    }

    profiles: dict[str, Any] = {}
    for name, column in measures:
        stats = _robust_stats(con, base, params, _quote(column))
        outliers = _outliers(
            con,
            base,
            params,
            _quote(column),
            profile.grain,
            stats,
            threshold=threshold,
            limit=MAX_OUTLIERS_PER_MEASURE,
        )
        changes = _changes(con, base, params, profile, column, threshold)
        segments = {
            dimension: _segments(con, base, params, dimension, column)
            for dimension in profile.dimensions
        }
        profiles[name] = {
            "column": column,
            "stats": stats,
            "outliers": outliers,
            "change": changes,
            "segments": segments,
        }

        if stats["null_fraction"]:
            findings.append(
                _finding(
                    "missing_measure",
                    public_view,
                    name,
                    f"{name} is missing in {stats['null_fraction']:.1%} of {public_view} rows in scope.",
                    severity="high" if stats["null_fraction"] >= 0.05 else "medium",
                    impact=stats["null_fraction"],
                    evidence={
                        "rows": stats["rows"],
                        "non_null": stats["non_null"],
                        "null_fraction": stats["null_fraction"],
                    },
                )
            )
        if stats["non_null"] > 1 and stats["stddev"] == 0:
            findings.append(
                _finding(
                    "zero_variance",
                    public_view,
                    name,
                    f"{name} is constant at {stats['median']} across {stats['non_null']} row(s) in scope.",
                    severity="medium",
                    impact=0.5,
                    evidence={"value": stats["median"], "non_null": stats["non_null"]},
                )
            )
        for candidate in outliers["candidates"]:
            findings.append(
                _finding(
                    "anomaly_candidate",
                    public_view,
                    name,
                    f"{name} = {candidate['value']} is {abs(candidate['robust_z']):.1f} modified z from the median.",
                    severity="high"
                    if abs(candidate["robust_z"]) >= HIGH_SEVERITY_Z
                    else "medium",
                    impact=abs(candidate["robust_z"]),
                    evidence=candidate,
                )
            )
        for candidate in changes["candidates"]:
            findings.append(
                _finding(
                    "level_shift",
                    public_view,
                    name,
                    f"{name} moved {candidate['value']} between adjacent snapshots "
                    f"({abs(candidate['robust_z']):.1f} modified z).",
                    severity="high"
                    if abs(candidate["robust_z"]) >= HIGH_SEVERITY_Z
                    else "medium",
                    impact=abs(candidate["robust_z"]),
                    evidence=candidate,
                )
            )

    summary = {
        "status": "ok",
        "rows": row_count,
        "scenario_id": scenario_id,
        "measures": [name for name, _ in measures],
        "missingness": missingness,
        "profiles": profiles,
        "correlations": _correlations(
            con, base, params, measures, min_correlation_rows
        ),
        "provenance": _provenance(con, base, params, columns),
    }
    return summary, findings


def _unavailable_checks(views: dict[str, Any]) -> list[dict[str, str]]:
    """List every statistic that could not be computed, with its stated reason."""
    checks: list[dict[str, str]] = []
    for view, result in sorted(views.items()):
        if result["status"] != "ok":
            checks.append(
                {
                    "view": view,
                    "check": "view_scope",
                    "reason": f"View status is {result['status']}.",
                }
            )
            continue
        for metric, profile in sorted(result["profiles"].items()):
            for check in ("outliers", "change"):
                block = profile[check]
                if block["status"] != "ok" and block["reason"]:
                    checks.append(
                        {
                            "view": view,
                            "check": f"{metric}.{check}",
                            "reason": block["reason"],
                        }
                    )
        for correlation in result["correlations"]:
            if correlation["status"] != "ok":
                checks.append(
                    {
                        "view": view,
                        "check": f"corr({correlation['x']}, {correlation['y']})",
                        "reason": correlation["reason"],
                    }
                )
    return checks


def run_eda(
    database: str | Path,
    *,
    views: list[str] | None = None,
    scenario_id: str | None = None,
    robust_z_threshold: float = ROBUST_Z_THRESHOLD,
    min_correlation_rows: int = MIN_CORRELATION_ROWS,
    install_views: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Run the parameterized EDA workflow and return a JSON-serializable report.

    The artifact is opened read-only unless ``install_views`` is set; a missing
    metric layer then raises :class:`MissingMetricViewsError` instead of being
    written into the curated file.
    """
    selected = sorted(views or EDA_PROFILES)
    unknown = sorted(set(selected) - set(EDA_PROFILES))
    if unknown:
        raise ValueError(
            f"Unknown metric view(s): {', '.join(unknown)}; "
            f"choose from {', '.join(sorted(EDA_PROFILES))}."
        )

    generated_at = (now or datetime.now(UTC)).astimezone(UTC)
    if not Path(database).is_file():
        raise FileNotFoundError(f"DuckDB artifact not found: {database}")
    con = duckdb.connect(str(database), read_only=not install_views)
    try:
        if install_views:
            install_metric_layer(con)
        else:
            _require_views(con, selected)
        topology = _topology(con)
        results: dict[str, Any] = {}
        findings: list[dict[str, Any]] = []
        for name in selected:
            result, view_findings = _analyse_view(
                con,
                name,
                EDA_PROFILES[name],
                scenario_id,
                threshold=robust_z_threshold,
                min_correlation_rows=min_correlation_rows,
            )
            results[name] = result
            findings.extend(view_findings)
    finally:
        con.close()

    severity_rank = {"high": 0, "medium": 1, "low": 2}
    findings.sort(
        key=lambda finding: (
            severity_rank[finding["severity"]],
            -finding["impact"],
            finding["metric_view"],
            finding["metric"],
            finding["code"],
            _evidence_label(finding["evidence"]),
        )
    )

    return {
        "eda_version": EDA_VERSION,
        "metric_layer_version": METRIC_LAYER_VERSION,
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": generated_at.isoformat(),
        "database": str(database),
        "parameters": {
            "views": selected,
            "scenario_id": scenario_id,
            "robust_z_threshold": robust_z_threshold,
            "min_correlation_rows": min_correlation_rows,
            "install_views": install_views,
        },
        "topology": topology,
        "views": results,
        "findings": findings,
        "unavailable_checks": _unavailable_checks(results),
        "delivery": "This report is the EDA artifact; no dashboard or notification consumes it yet.",
    }


def render_summary(report: dict[str, Any]) -> str:
    """Render the written insight summary that accompanies the JSON report."""
    parameters = report["parameters"]
    scope = parameters["scenario_id"] or "all scenarios in the artifact"
    lines = [
        "# Flux EDA insight summary",
        "",
        f"**Generated (UTC):** {report['generated_at_utc']}  ",
        f"**Artifact:** `{report['database']}`  ",
        f"**Scope:** {scope}  ",
        (
            f"**Versions:** EDA {report['eda_version']}, metric layer "
            f"{report['metric_layer_version']}, fixture contract {report['schema_version']}"
        ),
        "",
        "Methodology and assumptions: [`docs/data/eda-methodology.md`](eda-methodology.md).",
        "",
        "## Coverage",
        "",
        "| Metric view | Status | Rows in scope | KPIs profiled |",
        "| --- | --- | --- | --- |",
    ]
    for view, result in sorted(report["views"].items()):
        lines.append(
            f"| `{view}` | {result['status']} | {result['rows']} | {', '.join(result['measures'])} |"
        )

    lines += ["", "## Topology and provenance", ""]
    topology = report["topology"]
    if topology["status"] == "ok":
        lines.append(
            f"- Network topology: **{topology['label']}** (ingest_log source `{topology['source']}`, "
            f"release `{topology['source_release']}`). Cascade and site results describe this "
            "synthetic network, not the physical grid."
        )
    else:
        lines.append(f"- Network topology: unavailable; {topology['reason']}")
    for view, result in sorted(report["views"].items()):
        provenance = result["provenance"]
        kinds = (
            ", ".join(f"`{kind}`" for kind in provenance["scenario_kinds"])
            or "none in scope"
        )
        sources = (
            ", ".join(f"`{name}`" for name in provenance["source_names"])
            or "none in scope"
        )
        lines.append(f"- `{view}`: scenario kinds {kinds}; sources of record {sources}")

    lines += ["", "## Prioritized findings", ""]
    if not report["findings"]:
        lines.append(
            "No anomaly or data-quality candidate crossed its threshold in this scope."
        )
    else:
        lines += [
            "| # | Severity | Code | KPI | Evidence | Recommended action |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for rank, finding in enumerate(report["findings"], start=1):
            lines.append(
                f"| {rank} | {finding['severity']} | `{finding['code']}` | `{finding['metric']}` "
                f"({finding['metric_view']}) | {_evidence_label(finding['evidence'])} "
                f"| {finding['recommended_action']} |"
            )

    lines += ["", "## Follow-up questions", ""]
    questions = sorted(
        {finding["follow_up_question"] for finding in report["findings"]}
    )
    lines += [f"- {question}" for question in questions] or [
        "- None raised by this run."
    ]

    lines += ["", "## Checks reported unavailable", ""]
    checks = report["unavailable_checks"]
    lines += [
        f"- `{check['view']}` / `{check['check']}`: {check['reason']}"
        for check in checks
    ] or ["- None; every requested statistic was computable."]
    lines.append("")
    return "\n".join(lines)
