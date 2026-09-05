from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb
import pytest

from pipelines.db import ensure_schema
from pipelines.eda import (
    EDA_VERSION,
    MEAN_AD_Z_CONSTANT,
    ROBUST_Z_CONSTANT,
    MissingMetricViewsError,
    render_summary,
    run_eda,
)
from pipelines.metrics import METRIC_LAYER_VERSION, install_metric_layer

FIXED_NOW = datetime(2026, 9, 5, 12, 0, 0, tzinfo=UTC)
COUNTIES = (("48453", "Travis", "TX"), ("27053", "Hennepin", "MN"))
REPO_ROOT = Path(__file__).resolve().parents[2]
RUN_EDA = REPO_ROOT / "scripts" / "run_eda.py"


def _naive(value: datetime) -> datetime:
    """Contract timestamp columns are naive UTC; strip the zone at the insert boundary."""
    return value.astimezone(UTC).replace(tzinfo=None)


def _provenance() -> tuple[object, ...]:
    return (
        "fixture",
        "test://fixture",
        "v1",
        _naive(datetime(2026, 9, 5, tzinfo=UTC)),
        "batch-1",
    )


def _seed(
    path: Path, *, windows: int = 12, spike: bool = True, install: bool = True
) -> None:
    con = duckdb.connect(str(path))
    try:
        ensure_schema(con)
        provenance = _provenance()
        for fips, name, state in COUNTIES:
            con.execute(
                "INSERT INTO counties VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (fips, name, state, 1000000, b"county", *provenance),
            )
        con.execute(
            "INSERT INTO scenarios VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "uri_2021",
                "Uri",
                "historical",
                _naive(datetime(2021, 2, 13, tzinfo=UTC)),
                _naive(datetime(2021, 2, 20, tzinfo=UTC)),
                *provenance,
            ),
        )
        con.execute(
            "INSERT INTO site_candidates VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                1,
                "Example Site",
                "coal_retired",
                -97.7,
                30.3,
                "48453",
                None,
                1000.0,
                "source-site-1",
                *provenance,
            ),
        )
        con.execute(
            "INSERT INTO site_scores VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (1, "all", 1000.0, 90.0, "[]", 80.0, 15.0, 20.0, 30.0, *provenance),
        )
        _seed_predictions(con, windows=windows, spike=spike)
        if install:
            install_metric_layer(con)
    finally:
        con.close()


def _seed_predictions(
    con: duckdb.DuckDBPyConnection,
    *,
    windows: int,
    spike: bool,
    start: int = 0,
    counties: tuple[tuple[str, str, str], ...] = COUNTIES,
) -> None:
    """Insert six-hour prediction windows with an optional planted spike."""
    provenance = _provenance()
    for index in range(start, start + windows):
        timestamp = _naive(
            datetime(2021, 2, 13, tzinfo=UTC) + timedelta(hours=6 * index)
        )
        for offset, (fips, _, _) in enumerate(counties):
            customers = 100 + offset * 10 + index
            probability = 0.30 + 0.01 * index + 0.02 * offset
            if spike and index == 5 and fips == "48453":
                customers = 100000
                probability = 0.99
            con.execute(
                "INSERT INTO outage_predictions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "uri_2021",
                    fips,
                    timestamp,
                    probability,
                    customers,
                    "ice",
                    *provenance,
                ),
            )


def _findings(report: dict, code: str) -> list[dict]:
    return [finding for finding in report["findings"] if finding["code"] == code]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_eda_profiles_canonical_kpis_and_ranks_a_planted_anomaly(
    tmp_path: Path,
) -> None:
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
    states = outage["profiles"]["outage_customers_at_risk"]["segments"]["state"][
        "segments"
    ]
    assert [segment["segment"] for segment in states] == ["MN", "TX"]
    assert all(segment["rows"] == 12 for segment in states)

    correlation = next(
        entry
        for entry in outage["correlations"]
        if entry["x"] == "outage_customers_at_risk"
    )
    assert correlation["status"] == "ok" and correlation["pairwise_rows"] == 24
    assert correlation["pearson_r"] is not None

    anomalies = _findings(report, "anomaly_candidate")
    spike = next(
        finding
        for finding in anomalies
        if finding["metric"] == "outage_customers_at_risk"
    )
    assert spike["severity"] == "high"
    assert spike["evidence"]["keys"]["county_fips"] == "48453"
    assert spike["evidence"]["value"] == 100000
    # Findings stay traceable to the canonical metric definition.
    assert spike["metric_version"] == METRIC_LAYER_VERSION
    assert (
        spike["lineage"]
        == "outage_predictions → metric_outage_county_prediction_windows"
    )
    assert spike["unit"] == "customer accounts"
    assert spike["follow_up_question"] and spike["recommended_action"]

    assert outage["profiles"]["outage_customers_at_risk"]["outliers"]["scale"] == "mad"
    # Pin the Iglewicz-Hoaglin constant: modified z = 0.6745 * (x - median) / MAD.
    assert ROBUST_Z_CONSTANT == 0.6745
    expected_z = 0.6745 * (100000 - stats["median"]) / stats["mad"]
    assert spike["evidence"]["robust_z"] == pytest.approx(expected_z, abs=1e-3)

    # The same spike also moves the county series between adjacent windows.  The
    # first differences are near-constant, so the mean-absolute-deviation
    # fallback carries the scale instead of a collapsed MAD.
    shifts = _findings(report, "level_shift")
    assert any(
        finding["evidence"]["keys"]["county_fips"] == "48453" for finding in shifts
    )
    change = outage["profiles"]["outage_customers_at_risk"]["change"]
    assert change["status"] == "ok" and change["series_analysed"] == 2
    assert change["stats"]["mad"] == 0 and change["scale"] == "mean_abs_deviation"
    # Pin the fallback constant: z = 0.7979 * (delta - median) / MeanAD.
    assert MEAN_AD_Z_CONSTANT == 0.7979
    shift = max(
        (f for f in shifts if f["metric"] == "outage_customers_at_risk"),
        key=lambda f: abs(f["evidence"]["robust_z"]),
    )
    expected_shift_z = (
        0.7979
        * (shift["evidence"]["value"] - change["stats"]["median"])
        / change["stats"]["mean_abs_deviation"]
    )
    assert shift["evidence"]["robust_z"] == pytest.approx(expected_shift_z, abs=1e-3)

    severity_rank = {"high": 0, "medium": 1, "low": 2}
    ranks = [
        (severity_rank[finding["severity"]], -finding["impact"])
        for finding in report["findings"]
    ]
    assert ranks == sorted(ranks)


def test_eda_rerun_after_a_refresh_is_deterministic_and_updates_findings(
    tmp_path: Path,
) -> None:
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
    assert all(
        finding["metric_version"] == METRIC_LAYER_VERSION
        for finding in refreshed["findings"]
    )
    assert _findings(refreshed, "anomaly_candidate")

    summary = render_summary(refreshed)
    assert "## Prioritized findings" in summary
    assert "## Follow-up questions" in summary
    assert "outage_customers_at_risk" in summary


def test_eda_reports_unavailable_rather_than_zero_on_an_empty_artifact(
    tmp_path: Path,
) -> None:
    database = tmp_path / "empty.duckdb"
    con = duckdb.connect(str(database))
    try:
        ensure_schema(con)
        install_metric_layer(con)
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
    assert "None; every requested statistic was computable." not in render_summary(
        report
    )


def test_eda_reports_a_scoped_view_with_too_little_data_as_insufficient(
    tmp_path: Path,
) -> None:
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
    site_change = report["views"]["site_scorecards"]["profiles"][
        "site_grid_value_score"
    ]["change"]
    assert site_change["status"] == "not_applicable"
    reasons = {check["reason"] for check in report["unavailable_checks"]}
    assert any("required" in reason for reason in reasons)


def test_eda_rejects_an_unknown_view_and_a_missing_metric_layer(tmp_path: Path) -> None:
    database = tmp_path / "grid.duckdb"
    _seed(database, windows=3, spike=False, install=False)

    with pytest.raises(ValueError, match="Unknown metric view"):
        run_eda(
            database, views=["outage_predictions; DROP TABLE counties"], now=FIXED_NOW
        )

    with pytest.raises(
        MissingMetricViewsError, match="Canonical metric views are missing"
    ) as raised:
        run_eda(database, now=FIXED_NOW)
    assert raised.value.status == "metric_views_missing"
    assert raised.value.missing == [
        "metric_cascade_run_hours",
        "metric_outage_county_prediction_windows",
        "metric_site_scorecards",
    ]


def test_eda_default_run_is_read_only_and_never_creates_an_artifact(
    tmp_path: Path,
) -> None:
    database = tmp_path / "grid.duckdb"
    _seed(database, windows=3, spike=False, install=False)
    before = _sha256(database)

    # Without the metric layer a default (read-only) run names the gap and leaves the file alone.
    with pytest.raises(MissingMetricViewsError):
        run_eda(database, now=FIXED_NOW)
    assert _sha256(database) == before

    # Opting in installs the views (a write); a following default run is then read-only.
    installed = run_eda(database, install_views=True, now=FIXED_NOW)
    assert installed["parameters"]["install_views"] is True
    after_install = _sha256(database)
    assert after_install != before
    report = run_eda(database, now=FIXED_NOW)
    assert report["parameters"]["install_views"] is False
    assert report["views"]["outage_county_prediction_windows"]["rows"] == 6
    assert _sha256(database) == after_install

    # A mistyped path must not materialise an empty .duckdb, in either mode.
    missing = tmp_path / "typo.duckdb"
    with pytest.raises(FileNotFoundError):
        run_eda(missing, now=FIXED_NOW)
    with pytest.raises(FileNotFoundError):
        run_eda(missing, install_views=True, now=FIXED_NOW)
    assert not missing.exists()


def test_eda_change_analysis_ignores_series_below_the_point_minimum(
    tmp_path: Path,
) -> None:
    database = tmp_path / "grid.duckdb"
    _seed(database, windows=0, spike=False, install=False)
    con = duckdb.connect(str(database))
    try:
        # Twelve smooth points for Travis; two points with a 49 900 jump for Hennepin.
        _seed_predictions(con, windows=12, spike=False, counties=(COUNTIES[0],))
        provenance = _provenance()
        for index, customers in ((0, 100), (1, 50000)):
            con.execute(
                "INSERT INTO outage_predictions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "uri_2021",
                    "27053",
                    _naive(
                        datetime(2021, 2, 13, tzinfo=UTC) + timedelta(hours=6 * index)
                    ),
                    0.5,
                    customers,
                    "ice",
                    *provenance,
                ),
            )
        install_metric_layer(con)
    finally:
        con.close()

    report = run_eda(
        database, views=["outage_county_prediction_windows"], now=FIXED_NOW
    )
    change = report["views"]["outage_county_prediction_windows"]["profiles"][
        "outage_customers_at_risk"
    ]["change"]

    assert change["series_analysed"] == 1
    # Only the eligible series feeds the pooled scale: 12 rows, 11 non-null first differences.
    assert change["stats"]["rows"] == 12 and change["stats"]["non_null"] == 11
    assert change["stats"]["max"] == 1 and change["stats"]["mean_abs_deviation"] == 0
    shifts = _findings(report, "level_shift")
    assert not any(
        finding["evidence"]["keys"]["county_fips"] == "27053" for finding in shifts
    )
    assert all(
        candidate["keys"]["county_fips"] != "27053"
        for candidate in change["candidates"]
    )


def test_eda_names_missing_and_constant_measures_as_findings(tmp_path: Path) -> None:
    database = tmp_path / "grid.duckdb"
    _seed(database, windows=3, spike=False, install=False)
    con = duckdb.connect(str(database))
    try:
        provenance = _provenance()
        for site_id in range(2, 6):
            con.execute(
                "INSERT INTO site_candidates VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    site_id,
                    f"Site {site_id}",
                    "coal_retired",
                    -97.7,
                    30.3,
                    "48453",
                    None,
                    1000.0,
                    f"s-{site_id}",
                    *provenance,
                ),
            )
            # grid_value_score is nullable per the contract; lol_reduction_mwh is held constant.
            con.execute(
                "INSERT INTO site_scores VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    site_id,
                    "all",
                    1000.0,
                    90.0,
                    "[]",
                    None,
                    15.0,
                    20.0,
                    30.0,
                    *provenance,
                ),
            )
        install_metric_layer(con)
    finally:
        con.close()

    report = run_eda(database, views=["site_scorecards"], now=FIXED_NOW)

    missing = _findings(report, "missing_measure")
    assert [finding["metric"] for finding in missing] == ["site_grid_value_score"]
    assert (
        missing[0]["severity"] == "high"
    )  # 4 of 5 rows missing is well above the 5% cut
    assert missing[0]["impact"] == pytest.approx(0.8)
    assert missing[0]["evidence"] == {"rows": 5, "non_null": 1, "null_fraction": 0.8}

    constant = _findings(report, "zero_variance")
    assert [finding["metric"] for finding in constant] == ["site_lol_reduction_mwh"]
    assert constant[0]["severity"] == "medium" and constant[0]["impact"] == 0.5
    assert constant[0]["evidence"] == {"value": 15.0, "non_null": 5}

    summary = render_summary(report)
    assert "`missing_measure`" in summary and "`zero_variance`" in summary


def test_eda_scenario_filter_selects_one_scenario(tmp_path: Path) -> None:
    database = tmp_path / "grid.duckdb"
    _seed(database, windows=3, spike=False)

    scoped = run_eda(
        database,
        views=["outage_county_prediction_windows"],
        scenario_id="no_such_scenario",
        now=FIXED_NOW,
    )
    assert scoped["views"]["outage_county_prediction_windows"]["status"] == "no_rows"
    assert scoped["parameters"]["scenario_id"] == "no_such_scenario"

    matched = run_eda(
        database,
        views=["outage_county_prediction_windows"],
        scenario_id="uri_2021",
        now=FIXED_NOW,
    )
    assert matched["views"]["outage_county_prediction_windows"]["rows"] == 6


def test_eda_labels_topology_and_provenance_from_the_artifact(tmp_path: Path) -> None:
    database = tmp_path / "grid.duckdb"
    _seed(database, windows=3, spike=False)

    unknown = run_eda(
        database, views=["outage_county_prediction_windows"], now=FIXED_NOW
    )
    assert (
        unknown["topology"]["status"] == "unavailable"
        and unknown["topology"]["label"] is None
    )
    assert "Network topology: unavailable" in render_summary(unknown)
    provenance = unknown["views"]["outage_county_prediction_windows"]["provenance"]
    assert provenance == {"scenario_kinds": ["historical"], "source_names": ["fixture"]}

    con = duckdb.connect(str(database))
    try:
        con.execute(
            "INSERT INTO ingest_log VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "activsg2000",
                "current",
                "ACTIVSg2000.aux",
                "0" * 64,
                1,
                2000,
                "powerworld-aux",
                "p0-v1",
                _naive(FIXED_NOW),
            ),
        )
    finally:
        con.close()

    labelled = run_eda(
        database, views=["outage_county_prediction_windows"], now=FIXED_NOW
    )
    assert labelled["topology"] == {
        "status": "ok",
        "label": "synthetic ACTIVSg2000",
        "synthetic": True,
        "source": "activsg2000",
        "source_release": "current",
        "source_file": "ACTIVSg2000.aux",
    }
    summary = render_summary(labelled)
    assert "**synthetic ACTIVSg2000**" in summary
    assert "scenario kinds `historical`; sources of record `fixture`" in summary


def test_run_eda_cli_runs_as_documented_from_any_cwd(tmp_path: Path) -> None:
    database = tmp_path / "grid.duckdb"
    _seed(database)
    before = _sha256(database)
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    report_path, summary_path = tmp_path / "out" / "r.json", tmp_path / "out" / "s.md"

    completed = subprocess.run(
        [
            sys.executable,
            str(RUN_EDA),
            str(database),
            "--report",
            str(report_path),
            "--summary",
            str(summary_path),
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "# Flux EDA insight summary" in completed.stdout
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["parameters"]["install_views"] is False
    assert report["views"]["outage_county_prediction_windows"]["rows"] == 24
    assert (
        summary_path.read_text(encoding="utf-8") == completed.stdout.rstrip("\n") + "\n"
    )
    # The default run leaves the curated artifact byte-identical.
    assert _sha256(database) == before

    missing = subprocess.run(
        [sys.executable, str(RUN_EDA), str(tmp_path / "typo.duckdb")],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert missing.returncode == 2 and "artifact_missing" in missing.stderr
    assert not (tmp_path / "typo.duckdb").exists()
