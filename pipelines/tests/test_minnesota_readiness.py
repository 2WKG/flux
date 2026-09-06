"""Guard the Minnesota readiness receipt against silent readiness claims."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest

from pipelines import minnesota_readiness as readiness

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def receipt() -> dict:
    return readiness.build_receipt()


def test_topology_gate_is_unmet_so_aggregate_mode_is_selected(receipt: dict) -> None:
    gate = receipt["topology_gate"]
    assert gate["topology_mode_available"] is False
    assert gate["unmet_items"] == [item["id"] for item in gate["items"]]
    for item in gate["items"]:
        assert item["evidence"] and item["next_step"]
    assert receipt["selected_model_mode"] == "aggregate"
    assert "ACTIVSg2000" in gate["texas_topology_exclusion"]


def test_aggregate_mode_publishes_the_prohibition_list(receipt: dict) -> None:
    prohibited = " ".join(receipt["prohibited_claims"]).lower()
    for banned in (
        "flow",
        "rating",
        "loading",
        "dc power flow",
        "n-1",
        "trip",
        "cascade",
        "outage replay",
        "interconnection study",
    ):
        assert banned in prohibited


def test_stress_metric_states_formula_units_allocation_and_labels(
    receipt: dict,
) -> None:
    metric = receipt["aggregate_output"]["stress_metric"]
    assert metric["metric_id"] == "mn_agg_miso_demand_stress_index_v1"
    assert "D_MISO" in metric["formula"]
    assert "MW" in metric["units"]
    assert metric["source_label"] == "source_backed"
    assert "None applied" in metric["allocation_assumptions"]
    assert receipt["artifact_manifest"]["allocation_status"] == "unavailable"


def test_every_published_number_carries_its_query(
    receipt: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The published SQL must rerun verbatim from a checkout root and match."""
    measurements = receipt["aggregate_output"]["measurements"]
    assert set(measurements) == set(readiness.AGGREGATE_QUERIES)
    monkeypatch.chdir(ROOT)
    with duckdb.connect(":memory:") as connection:
        for name, measured in measurements.items():
            assert measured["query"].startswith(("SELECT", "WITH"))
            replayed = readiness._as_row(connection, measured["query"])
            assert replayed == measured["result"], name


def test_committed_evidence_identity_is_reverified(receipt: dict) -> None:
    checks = receipt["artifact_manifest"]["committed_evidence_checks"]
    assert checks
    for check in checks:
        assert check["status"] == "verified"
        assert check["observed_sha256"] == check["expected_sha256"]


def test_tampered_evidence_stops_the_receipt(tmp_path: Path) -> None:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    for name in (
        readiness.AGGREGATE_MANIFEST_FILE,
        readiness.CAPACITY_FILE,
        readiness.CONTEXT_FILE,
        "mn_unassigned_plant_capacity_2024.csv",
    ):
        (inputs / name).write_bytes((readiness.DEFAULT_INPUTS_DIR / name).read_bytes())
    with (inputs / readiness.CONTEXT_FILE).open("a", encoding="utf-8") as stream:
        stream.write("2024-07-01 06:00:00+00:00,1.0,1.0,1.0,0.0\n")
    with pytest.raises(readiness.ReadinessError, match="identity verification"):
        readiness.build_receipt(inputs_dir=inputs)


def test_missing_store_is_a_structured_unavailable_with_next_steps(
    receipt: dict, tmp_path: Path
) -> None:
    assert receipt["county_grain_store"]["status"] == "unavailable"
    unavailable = receipt["readiness"]["unavailable"]
    assert [entry["input"] for entry in unavailable] == ["county_grain_store"]
    assert all(entry["next_steps"] for entry in unavailable)
    assert receipt["readiness"]["topology_mode_ready"] is False

    absent = readiness.probe_county_grain_store(tmp_path / "grid.duckdb")
    assert absent["status"] == "unavailable"
    assert absent["next_steps"]


def test_a_present_store_is_measured_by_real_queries(tmp_path: Path) -> None:
    database = tmp_path / "grid.duckdb"
    with duckdb.connect(database.as_posix()) as connection:
        connection.execute("CREATE TABLE counties(county_fips TEXT)")
        connection.execute("INSERT INTO counties VALUES ('27001'), ('48001')")
    probe = readiness.probe_county_grain_store(database)
    assert probe["status"] == "measured"
    assert probe["relations"]["counties"]["minnesota_rows"] == 1
    # Relations the store does not carry are reported, never assumed to be zero.
    assert probe["relations"]["eia_plants"]["status"] == "unavailable"


def test_source_decision_record_covers_the_committed_receipts(receipt: dict) -> None:
    records = receipt["source_decision_record"]["county_grain_public_context"]
    assert [record["receipt"] for record in records] == list(
        readiness.COUNTY_GRAIN_SOURCE_RECEIPTS
    )
    for record in records:
        assert record["status"] == "recorded"
        assert record["source_url"] and record["retrieved_at"]
        assert record["license_or_terms"] and record["version_or_vintage"]
        assert record["state_scope"] == "MN"


def test_cli_writes_the_receipt(tmp_path: Path) -> None:
    report = tmp_path / "nested" / "receipt.json"
    assert readiness.main(["--report", report.as_posix()]) == 0
    written = json.loads(report.read_text(encoding="utf-8"))
    assert written["format"] == readiness.FORMAT
    assert written["state_scope"] == "MN"


def test_cli_reports_a_missing_manifest_as_an_error_envelope(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert readiness.main(["--inputs-dir", tmp_path.as_posix()]) == 2
    error = json.loads(capsys.readouterr().err)
    assert "aggregate manifest not found" in error["error"]


def test_the_published_receipt_is_current() -> None:
    published = json.loads(
        (ROOT / "data/artifacts/minnesota/readiness-receipt-v1.json").read_text(
            encoding="utf-8"
        )
    )
    rebuilt = readiness.build_receipt()
    for field in ("generated_at",):
        published.pop(field)
        rebuilt.pop(field)
    assert published == rebuilt
