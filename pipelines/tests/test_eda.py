from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import duckdb
import pytest

from pipelines.db import ensure_schema
from pipelines.eda import EDA_VERSION, render_summary, run_eda
from pipelines.metrics import METRIC_LAYER_VERSION


FIXED_NOW = datetime(2026, 9, 5, 12, 0, 0)
COUNTIES = (("48453", "Travis", "TX"), ("27053", "Hennepin", "MN"))


def _provenance() -> tuple[object, ...]:
    return ("fixture", "test://fixture", "v1", datetime(2026, 9, 5), "batch-1")


def _seed(path: Path, *, windows: int = 12, spike: bool = True) -> None:
    con = duckdb.connect(str(path))
    try:
        ensure_schema(con)
        provenance = _provenance()
        for fips, name, state in COUNTIES:
            con.execute("INSERT INTO counties VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (fips, name, state, 1000000, b"county", *provenance))
        con.execute(
            "INSERT INTO scenarios VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("uri_2021", "Uri", "historical", datetime(2021, 2, 13), datetime(2021, 2, 20), *provenance),
        )
        con.execute(
            "INSERT INTO site_candidates VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (1, "Example Site", "coal_retired", -97.7, 30.3, "48453", None, 1000.0, "source-site-1", *provenance),
        )
        con.execute(
            "INSERT INTO site_scores VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (1, "all", 1000.0, 90.0, "[]", 80.0, 15.0, 20.0, 30.0, *provenance),
        )
        _seed_predictions(con, windows=windows, spike=spike)
    finally:
        con.close()


def _seed_predictions(con: duckdb.DuckDBPyConnection, *, windows: int, spike: bool, start: int = 0) -> None:
    """Insert six-hour prediction windows with an optional planted spike."""
    provenance = _provenance()
    for index in range(start, start + windows):
        timestamp = datetime(2021, 2, 13) + timedelta(hours=6 * index)
        for offset, (fips, _, _) in enumerate(COUNTIES):
            customers = 100 + offset * 10 + index
            probability = 0.30 + 0.01 * index + 0.02 * offset
            if spike and index == 5 and fips == "48453":
                customers = 100000
                probability = 0.99
            con.execute(
                "INSERT INTO outage_predictions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("uri_2021", fips, timestamp, probability, customers, "ice", *provenance),
            )


def _findings(report: dict, code: str) -> list[dict]:
    return [finding for finding in report["findings"] if finding["code"] == code]


def test_eda_profiles_canonical_kpis_and_ranks_a_planted_anomaly(tmp_path: Path) -> None:
    database = tmp_path / "grid.duckdb"
    _seed(database)

    report = run_eda(database, now=FIXED_NOW, min_correlation_rows=10)

    assert report["eda_version"] == EDA_VERSION
    assert report["metric_layer_version"] == METRIC_LAYER_VERSION
    outage = report["views"]["outage_county_prediction_windows"]
    assert outage["status"] == "ok"
    assert outage["rows"] == 24
    assert outage["measures"] == ["outage_customers_at_risk", "outage_probability"]

    stats = outage["profiles"]["outage_customers_at_risk"]["stats"]
    assert stats["rows"] == 24 and stats["non_null"] == 24
    assert stats["max"] == 100000 and stats["null_fraction"] == 0.0
    assert stats["mad"] is not None

    # Segmentation stays inside the released aggregation rules: counts and
    # order statistics per contract dimension, never a cross-window sum.
    states = outage["profiles"]["outage_customers_at_risk"]["segments"]["state"]["segments"]
    assert [segment["segment"] for segment in states] == ["MN", "TX"]
    assert all(segment["rows"] == 12 for segment in states)

    correlation = next(entry for entry in outage["correlations"] if entry["x"] == "outage_customers_at_risk")
    assert correlation["status"] == "ok" and correlation["pairwise_rows"] == 24
    assert correlation["pearson_r"] is not None

    anomalies = _findings(report, "anomaly_candidate")
    spike = next(finding for finding in anomalies if finding["metric"] == "outage_customers_at_risk")
    assert spike["severity"] == "high"
    assert spike["evidence"]["keys"]["county_fips"] == "48453"
    assert spike["evidence"]["value"] == 100000
    # Findings stay traceable to the canonical metric definition.
    assert spike["metric_version"] == METRIC_LAYER_VERSION
    assert spike["lineage"] == "outage_predictions → metric_outage_county_prediction_windows"
    assert spike["unit"] == "customer accounts"
    assert spike["follow_up_question"] and spike["recommended_action"]

    assert outage["profiles"]["outage_customers_at_risk"]["outliers"]["scale"] == "mad"

    # The same spike also moves the county series between adjacent windows.  The
    # first differences are near-constant, so the mean-absolute-deviation
    # fallback carries the scale instead of a collapsed MAD.
    shifts = _findings(report, "level_shift")
    assert any(finding["evidence"]["keys"]["county_fips"] == "48453" for finding in shifts)
    change = outage["profiles"]["outage_customers_at_risk"]["change"]
    assert change["status"] == "ok" and change["series_analysed"] == 2
    assert change["stats"]["mad"] == 0 and change["scale"] == "mean_abs_deviation"

    severity_rank = {"high": 0, "medium": 1, "low": 2}
    ranks = [(severity_rank[finding["severity"]], -finding["impact"]) for finding in report["findings"]]
    assert ranks == sorted(ranks)


def test_eda_rerun_after_a_refresh_is_deterministic_and_updates_findings(tmp_path: Path) -> None:
    database = tmp_path / "grid.duckdb"
    _seed(database)

    first = run_eda(database, now=FIXED_NOW)
    repeat = run_eda(database, now=FIXED_NOW)
    assert repeat == first

    con = duckdb.connect(str(database))
    try:
        _seed_predictions(con, windows=6, spike=False, start=12)
    finally:
        con.close()

    refreshed = run_eda(database, now=FIXED_NOW)
    assert refreshed["views"]["outage_county_prediction_windows"]["rows"] == 36
    assert refreshed != first
    assert all(finding["metric_version"] == METRIC_LAYER_VERSION for finding in refreshed["findings"])
    assert _findings(refreshed, "anomaly_candidate")

    summary = render_summary(refreshed)
    assert "## Prioritized findings" in summary
    assert "## Follow-up questions" in summary
    assert "outage_customers_at_risk" in summary


def test_eda_reports_unavailable_rather_than_zero_on_an_empty_artifact(tmp_path: Path) -> None:
    database = tmp_path / "empty.duckdb"
    con = duckdb.connect(str(database))
    try:
        ensure_schema(con)
    finally:
        con.close()

    report = run_eda(database, now=FIXED_NOW)

    assert {view["status"] for view in report["views"].values()} == {"no_rows"}
    assert all(view["profiles"] == {} for view in report["views"].values())
    empty = _findings(report, "no_rows")
    assert len(empty) == 3
    assert all(finding["severity"] == "high" for finding in empty)
    assert all("unavailable, not zero" in finding["description"] for finding in empty)
    assert {check["check"] for check in report["unavailable_checks"]} == {"view_scope"}
    assert "None; every requested statistic was computable." not in render_summary(report)


def test_eda_reports_a_scoped_view_with_too_little_data_as_insufficient(tmp_path: Path) -> None:
    database = tmp_path / "sparse.duckdb"
    _seed(database, windows=2, spike=False)

    report = run_eda(database, now=FIXED_NOW)

    cascade = report["views"]["cascade_run_hours"]
    assert cascade["status"] == "no_rows"
    outage = report["views"]["outage_county_prediction_windows"]
    outliers = outage["profiles"]["outage_probability"]["outliers"]
    assert outliers["status"] == "insufficient_rows" and outliers["candidates"] == []
    assert "required" in outliers["reason"]
    change = outage["profiles"]["outage_probability"]["change"]
    assert change["status"] == "insufficient_rows" and change["series_analysed"] == 0
    site_change = report["views"]["site_scorecards"]["profiles"]["site_grid_value_score"]["change"]
    assert site_change["status"] == "not_applicable"
    reasons = {check["reason"] for check in report["unavailable_checks"]}
    assert any("required" in reason for reason in reasons)


def test_eda_rejects_an_unknown_view_and_a_missing_metric_layer(tmp_path: Path) -> None:
    database = tmp_path / "grid.duckdb"
    _seed(database, windows=3, spike=False)

    with pytest.raises(ValueError, match="Unknown metric view"):
        run_eda(database, views=["outage_predictions; DROP TABLE counties"], now=FIXED_NOW)

    with pytest.raises(RuntimeError, match="Canonical metric views are missing"):
        run_eda(database, install_views=False, now=FIXED_NOW)


def test_eda_scenario_filter_selects_one_scenario(tmp_path: Path) -> None:
    database = tmp_path / "grid.duckdb"
    _seed(database, windows=3, spike=False)

    scoped = run_eda(database, views=["outage_county_prediction_windows"], scenario_id="no_such_scenario", now=FIXED_NOW)
    assert scoped["views"]["outage_county_prediction_windows"]["status"] == "no_rows"
    assert scoped["parameters"]["scenario_id"] == "no_such_scenario"

    matched = run_eda(database, views=["outage_county_prediction_windows"], scenario_id="uri_2021", now=FIXED_NOW)
    assert matched["views"]["outage_county_prediction_windows"]["rows"] == 6
