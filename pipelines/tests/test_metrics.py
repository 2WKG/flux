from __future__ import annotations

from datetime import datetime

import duckdb
import pytest

from pipelines import metrics
from pipelines.db import ensure_schema
from pipelines.metrics import (
    METRIC_DEFINITIONS,
    METRIC_LAYER_VERSION,
    install_metric_layer,
    metric_query,
    metric_view,
)


def _provenance() -> tuple[object, ...]:
    return ("fixture", "test://fixture", "v1", datetime(2026, 9, 5), "batch-1")  # noqa: DTZ001 -- DuckDB TIMESTAMP fixture


def _seed(con: duckdb.DuckDBPyConnection) -> None:
    ensure_schema(con)
    provenance = _provenance()
    con.execute(
        """INSERT INTO counties VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("48453", "Travis", "TX", 1000000, b"county", *provenance),
    )
    con.execute(
        """INSERT INTO scenarios VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "uri_2021",
            "Uri",
            "historical",
            datetime(2021, 2, 13),  # noqa: DTZ001 -- DuckDB TIMESTAMP fixture
            datetime(2021, 2, 20),  # noqa: DTZ001 -- DuckDB TIMESTAMP fixture
            *provenance,
        ),
    )
    con.execute(
        """INSERT INTO site_candidates VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
        """INSERT INTO outage_predictions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        ("uri_2021", "48453", datetime(2021, 2, 13), 0.4, 120, "ice", *provenance),  # noqa: DTZ001 -- DuckDB TIMESTAMP fixture
    )
    con.execute(
        """INSERT INTO cascade_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "uri_2021-s0-empty",
            "uri_2021",
            2,
            "[]",
            42.0,
            "[]",
            "[]",
            1,
            *provenance,
        ),
    )
    con.execute(
        """INSERT INTO site_scores VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (1, "all", 1000.0, 90.0, "[]", 80.0, 15.0, 20.0, 30.0, *provenance),
    )


def test_metric_layer_uses_contract_views_and_preserves_grain() -> None:
    con = duckdb.connect(":memory:")
    _seed(con)

    install_metric_layer(con)
    install_metric_layer(con)

    outage = con.execute(metric_query("outage_county_prediction_windows")).fetchone()
    assert outage[:8] == (
        "uri_2021",
        "Uri",
        "historical",
        "48453",
        "Travis",
        "TX",
        datetime(2021, 2, 13),  # noqa: DTZ001 -- DuckDB TIMESTAMP fixture
        0.4,
    )
    assert outage[8] == 120
    assert outage[10:15] == _provenance()

    cascade = con.execute(metric_query("cascade_run_hours")).fetchone()
    assert cascade[0:7] == (
        "uri_2021-s0-empty",
        "uri_2021",
        "Uri",
        "historical",
        2,
        datetime(2021, 2, 13, 2),  # noqa: DTZ001 -- DuckDB TIMESTAMP fixture
        42.0,
    )
    assert cascade[10:12] == (1, "Example Site")

    score = con.execute(metric_query("site_scorecards")).fetchone()
    assert score[0:10] == (
        1,
        "Example Site",
        "coal_retired",
        "48453",
        "Travis",
        "TX",
        "all",
        "all_scenarios",
        None,
        None,
    )
    assert score[10:15] == (1000.0, 90.0, "[]", 80.0, 15.0)

    assert metric_view("site_scorecards") == "metric_site_scorecards"
    assert metric_query("site_scorecards") == "SELECT * FROM metric_site_scorecards"
    assert METRIC_LAYER_VERSION == "1.0.0"
    assert {definition.name for definition in METRIC_DEFINITIONS} == {
        "outage_customers_at_risk",
        "outage_probability",
        "cascade_lost_load_mw",
        "site_lol_reduction_mwh",
        "site_grid_value_score",
    }
    assert all(
        definition.version == METRIC_LAYER_VERSION for definition in METRIC_DEFINITIONS
    )
    assert all(
        definition.unit and definition.lineage for definition in METRIC_DEFINITIONS
    )


def test_metric_view_install_rolls_back_on_a_bad_view(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    con = duckdb.connect(":memory:")
    _seed(con)
    monkeypatch.setattr(
        metrics,
        "VIEW_STATEMENTS",
        (
            metrics.VIEW_STATEMENTS[0],
            "CREATE OR REPLACE VIEW metric_broken AS SELECT FROM",
        ),
    )

    with pytest.raises(duckdb.ParserException):
        install_metric_layer(con)

    assert "metric_outage_county_prediction_windows" not in {
        row[0] for row in con.execute("SHOW TABLES").fetchall()
    }


def test_metric_layer_rejects_unknown_view_and_schema_version_mismatch() -> None:
    con = duckdb.connect(":memory:")
    _seed(con)

    with pytest.raises(ValueError, match="Unknown metric view"):
        metric_query("outage_predictions; DROP TABLE counties")

    con.execute("UPDATE schema_meta SET value = '0.0.0' WHERE key = 'contract_version'")
    with pytest.raises(RuntimeError, match="requires DuckDB contract"):
        install_metric_layer(con)
