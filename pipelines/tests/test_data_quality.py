from __future__ import annotations

import json
import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer

import duckdb
import pytest

from pipelines.data_quality import run_quality_gate
from pipelines.db import ensure_schema


def _database(tmp_path):
    path = tmp_path / "grid.duckdb"
    con = duckdb.connect(str(path))
    ensure_schema(con)
    provenance = [
        "eia-930",
        "release-1",
        "v1",
        datetime(2026, 9, 5, tzinfo=UTC),
        "batch-1",
    ]
    con.execute(
        "INSERT INTO counties VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ["27001", "Aitkin", "MN", 1, b"geometry", *provenance],
    )
    con.close()
    return path


def _operations(tmp_path, *, sla: int | None = 48):
    path = tmp_path / "operations.json"
    path.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "id": "eia-930",
                        "owner": "data-oncall",
                        "freshness_sla_hours": sla,
                    }
                ]
            }
        )
    )
    return path


def _log(tmp_path, records):
    path = tmp_path / "ingest.jsonl"
    path.write_text("\n".join(json.dumps(record) for record in records) + "\n")
    return path


def test_schema_enforces_null_unique_and_referential_integrity(tmp_path):
    path = _database(tmp_path)
    con = duckdb.connect(str(path))
    with pytest.raises(duckdb.ConstraintException):
        con.execute(
            "INSERT INTO counties VALUES (NULL, 'x', 'MN', 1, ?, 's', 'r', 'v', NULL, 'b')",
            [b"x"],
        )
    with pytest.raises(duckdb.ConstraintException):
        con.execute(
            "INSERT INTO counties VALUES ('27001', 'x', 'MN', 1, ?, 's', 'r', 'v', NULL, 'b')",
            [b"x"],
        )
    with pytest.raises(duckdb.ConstraintException):
        con.execute(
            "INSERT INTO buses VALUES (1, 'x', 1, 0, 0, '99999', NULL, 'fixture', NULL, NULL, 's', 'r', 'v', NULL, 'b')"
        )
    con.close()


def test_gate_checks_contract_values_and_volume_regressions(tmp_path, monkeypatch):
    path = _database(tmp_path)
    operations = _operations(tmp_path)
    # The schema has no enum for state; treating it as an accepted field here
    # exercises the gate's defensive enum check on an imported artifact.
    monkeypatch.setattr(
        "pipelines.data_quality.ACCEPTED_VALUES", {("counties", "state"): {"TX"}}
    )
    previous = tmp_path / "previous.json"
    previous.write_text(json.dumps({"counties": 2}))
    report = run_quality_gate(path, operations, previous_counts_path=previous)
    assert {alert["code"] for alert in report["alerts"]} >= {
        "accepted_values",
        "volume_regression",
    }
    assert not report["dashboard_eligible"]


def test_gate_reports_stale_failed_and_zero_row_source_records(tmp_path):
    path = _database(tmp_path)
    operations = _operations(tmp_path)
    now = datetime(2026, 9, 5, 12, tzinfo=UTC)
    log = _log(
        tmp_path,
        [
            {
                "source_id": "eia-930",
                "status": "ok",
                "row_count": 0,
                "retrieved_at_utc": (now - timedelta(hours=72)).isoformat(),
            },
            {
                "source_id": "eia-930",
                "status": "failed",
                "row_count": 0,
                "retrieved_at_utc": now.isoformat(),
            },
        ],
    )
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"counties": 1}))
    report = run_quality_gate(
        path, operations, ingest_log_path=log, previous_counts_path=baseline, now=now
    )
    codes = {alert["code"] for alert in report["alerts"]}
    assert {"failed_ingest", "zero_row_success", "stale_source"} <= codes
    assert all({"owner", "next_step"} <= set(alert) for alert in report["alerts"])


def test_gate_reconciles_curated_provenance_with_ingest_log(tmp_path):
    path = _database(tmp_path)
    operations = _operations(tmp_path)
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"counties": 1}))
    report = run_quality_gate(
        path,
        operations,
        ingest_log_path=_log(tmp_path, []),
        previous_counts_path=baseline,
    )
    assert any(alert["code"] == "source_curated_mismatch" for alert in report["alerts"])


def test_gate_compares_logged_curated_count_to_the_artifact(tmp_path):
    path = _database(tmp_path)
    operations = _operations(tmp_path)
    log = _log(
        tmp_path,
        [
            {
                "source_id": "eia-930",
                "status": "ok",
                "row_count": 100,
                "curated_row_count": 99,
                "retrieved_at_utc": datetime.now(UTC).isoformat(),
            }
        ],
    )
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"counties": 1}))
    report = run_quality_gate(
        path, operations, ingest_log_path=log, previous_counts_path=baseline
    )
    assert any(alert["code"] == "source_curated_mismatch" for alert in report["alerts"])


def test_api_is_explicitly_unavailable_without_a_url(tmp_path):
    report = run_quality_gate(_database(tmp_path), _operations(tmp_path))
    assert report["api_health"]["status"] == "unavailable"
    assert not report["dashboard_eligible"]


def test_gate_can_probe_a_real_local_health_endpoint(tmp_path):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()

        def log_message(self, *_args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        report = run_quality_gate(
            _database(tmp_path),
            _operations(tmp_path),
            api_health_url=f"http://127.0.0.1:{server.server_port}/health",
        )
    finally:
        server.shutdown()
        thread.join()
    assert report["api_health"]["status"] == "healthy"


def test_latest_partial_ingest_blocks_promotion(tmp_path):
    path = _database(tmp_path)
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"counties": 1}))
    log = _log(
        tmp_path,
        [
            {
                "source_id": "eia-930",
                "status": "partial",
                "row_count": 1,
                "retrieved_at_utc": datetime.now(UTC).isoformat(),
            }
        ],
    )
    report = run_quality_gate(
        path, _operations(tmp_path), ingest_log_path=log, previous_counts_path=baseline
    )
    assert any(alert["code"] == "partial_ingest" for alert in report["alerts"])
    assert not report["dashboard_eligible"]


def test_gate_reports_malformed_log_instead_of_crashing(tmp_path):
    path = _database(tmp_path)
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"counties": 1}))
    log = tmp_path / "ingest.jsonl"
    log.write_text("not json\n")
    report = run_quality_gate(
        path, _operations(tmp_path), ingest_log_path=log, previous_counts_path=baseline
    )
    assert any(alert["code"] == "malformed_ingest_log" for alert in report["alerts"])
    assert not report["dashboard_eligible"]


def test_gate_reports_unhealthy_local_health_endpoint(tmp_path):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(503)
            self.end_headers()

        def log_message(self, *_args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        report = run_quality_gate(
            _database(tmp_path),
            _operations(tmp_path),
            api_health_url=f"http://127.0.0.1:{server.server_port}/health",
        )
    finally:
        server.shutdown()
        thread.join()
    assert report["api_health"]["status"] == "unhealthy"
    assert any(alert["code"] == "api_health" for alert in report["alerts"])


def test_unknown_curated_source_and_future_log_are_blocking(tmp_path):
    path = _database(tmp_path)
    con = duckdb.connect(str(path))
    con.execute("UPDATE counties SET source_name = 'unoperated'")
    con.close()
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"counties": 1}))
    log = _log(
        tmp_path,
        [
            {
                "source_id": "eia-930",
                "status": "ok",
                "row_count": 1,
                "retrieved_at_utc": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
            }
        ],
    )
    report = run_quality_gate(
        path, _operations(tmp_path), ingest_log_path=log, previous_counts_path=baseline
    )
    assert {"unoperated_source", "malformed_ingest_log"} <= {
        alert["code"] for alert in report["alerts"]
    }
    assert not report["dashboard_eligible"]


def test_latest_timestamp_beats_log_order_for_partial_status(tmp_path):
    path = _database(tmp_path)
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"counties": 1}))
    now = datetime(2026, 9, 5, 12, tzinfo=UTC)
    log = _log(
        tmp_path,
        [
            {
                "source_id": "eia-930",
                "status": "partial",
                "row_count": 1,
                "retrieved_at_utc": (now - timedelta(hours=1)).isoformat(),
            },
            {
                "source_id": "eia-930",
                "status": "ok",
                "row_count": 1,
                "curated_row_count": 1,
                "retrieved_at_utc": (now - timedelta(hours=2)).isoformat(),
            },
        ],
    )
    report = run_quality_gate(
        path,
        _operations(tmp_path),
        ingest_log_path=log,
        previous_counts_path=baseline,
        now=now,
    )
    assert any(alert["code"] == "partial_ingest" for alert in report["alerts"])


def test_declared_provenance_mapping_allows_a_reconciled_release(tmp_path):
    path = _database(tmp_path)
    con = duckdb.connect(str(path))
    # The production EIA-930 loader persists eia930; the operations/catalogue
    # identity deliberately uses eia-930.
    con.execute(
        "UPDATE counties SET source_name = 'eia930', source_version = '2024_h2'"
    )
    con.close()
    operations = tmp_path / "operations.json"
    operations.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "id": "eia-930",
                        "owner": "data-oncall",
                        "freshness_sla_hours": None,
                    }
                ],
                "curated_source_mappings": [
                    {"source_name": "eia930", "operation_ids": ["eia-930"]}
                ],
            }
        )
    )
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"counties": 1}))
    log = _log(
        tmp_path,
        [
            {
                "source_id": "eia-930",
                "status": "ok",
                "row_count": 1,
                "curated_row_count": 1,
                "retrieved_at_utc": datetime.now(UTC).isoformat(),
            }
        ],
    )

    report = run_quality_gate(
        path, operations, ingest_log_path=log, previous_counts_path=baseline
    )

    codes = {alert["code"] for alert in report["alerts"]}
    assert "unoperated_source" not in codes
    assert "source_curated_mismatch" not in codes
    assert report["dashboard_eligible"]


def test_versioned_mapping_does_not_operate_an_unmapped_release(tmp_path):
    path = _database(tmp_path)
    con = duckdb.connect(str(path))
    con.execute("UPDATE counties SET source_name = 'eaglei', source_version = '2025'")
    con.close()
    operations = tmp_path / "operations.json"
    operations.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "id": "eaglei-2024",
                        "owner": "data-oncall",
                        "freshness_sla_hours": None,
                    }
                ],
                "curated_source_mappings": [
                    {
                        "source_name": "eaglei",
                        "source_version": "2024",
                        "operation_ids": ["eaglei-2024"],
                    }
                ],
            }
        )
    )
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"counties": 1}))

    report = run_quality_gate(path, operations, previous_counts_path=baseline)

    assert any(alert["code"] == "unoperated_source" for alert in report["alerts"])
    assert not report["dashboard_eligible"]


def test_composite_mapping_requires_all_inputs_without_double_counting(tmp_path):
    path = _database(tmp_path)
    con = duckdb.connect(str(path))
    con.execute("UPDATE counties SET source_name = 'census_tiger_county+fema_nri'")
    con.close()
    operations = tmp_path / "operations.json"
    operations.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "id": "census-tiger-counties",
                        "owner": "data-oncall",
                        "freshness_sla_hours": None,
                    },
                    {
                        "id": "fema-nri",
                        "owner": "data-oncall",
                        "freshness_sla_hours": None,
                    },
                ],
                "curated_source_mappings": [
                    {
                        "source_name": "census_tiger_county+fema_nri",
                        "operation_ids": ["census-tiger-counties", "fema-nri"],
                        "reconciliation_operation_ids": ["census-tiger-counties"],
                    }
                ],
            }
        )
    )
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"counties": 1}))
    log = _log(
        tmp_path,
        [
            {
                "source_id": "census-tiger-counties",
                "status": "ok",
                "row_count": 1,
                "curated_row_count": 1,
                "retrieved_at_utc": datetime.now(UTC).isoformat(),
            },
            {
                # The hazard release has its own row count.  Reconciling the
                # county table against it too would report 5 != 1, so this row
                # makes double counting visible instead of merely warned about.
                "source_id": "fema-nri",
                "status": "ok",
                "row_count": 5,
                "curated_row_count": 5,
                "retrieved_at_utc": datetime.now(UTC).isoformat(),
            },
        ],
    )

    report = run_quality_gate(
        path, operations, ingest_log_path=log, previous_counts_path=baseline
    )

    codes = {alert["code"] for alert in report["alerts"]}
    assert "unoperated_source" not in codes
    assert "source_curated_mismatch" not in codes
    assert "reconciliation_unavailable" not in codes
    assert report["dashboard_eligible"]


def test_invalid_mapping_is_an_explicit_release_blocker(tmp_path):
    path = _database(tmp_path)
    operations = tmp_path / "operations.json"
    operations.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "id": "eia-930",
                        "owner": "data-oncall",
                        "freshness_sla_hours": None,
                    }
                ],
                "curated_source_mappings": [
                    {"source_name": "eia930", "operation_ids": ["not-an-operation"]}
                ],
            }
        )
    )
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"counties": 1}))

    report = run_quality_gate(path, operations, previous_counts_path=baseline)

    assert any(alert["code"] == "invalid_source_mapping" for alert in report["alerts"])
    assert not report["dashboard_eligible"]
