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
    assert unavailable[0]["input"] == "county_grain_store"
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
    # One relation answered and six did not, so the store is partial, not
    # measured: a partial store must not read as a satisfied input.
    assert probe["status"] == "partial"
    assert probe["measured_relations"] == ["counties"]
    assert probe["relations"]["counties"]["minnesota_rows"] == 1
    # Relations the store does not carry are reported, never assumed to be zero.
    assert probe["relations"]["eia_plants"]["status"] == "unavailable"
    assert probe["next_steps"]


def test_a_full_store_is_measured_and_leaves_the_unavailable_list(
    tmp_path: Path,
) -> None:
    database = tmp_path / "grid.duckdb"
    with duckdb.connect(database.as_posix()) as connection:
        connection.execute("CREATE TABLE counties(county_fips TEXT)")
        connection.execute("CREATE TABLE nri_hazards(county_fips TEXT)")
        connection.execute("CREATE TABLE eia_plants(state TEXT)")
        connection.execute("CREATE TABLE storm_events(county_fips TEXT)")
        connection.execute("CREATE TABLE eaglei_outage_observations(county_fips TEXT)")
        connection.execute("CREATE TABLE county_customers(county_fips TEXT)")
        connection.execute("CREATE TABLE eaglei_coverage(state TEXT)")
        connection.execute("INSERT INTO counties VALUES ('27001')")
    probe = readiness.probe_county_grain_store(database)
    assert probe["status"] == "measured"
    assert probe["unmeasured_relations"] == []
    receipt = readiness.build_receipt(database=database)
    assert "county_grain_store" not in [
        entry["input"] for entry in receipt["readiness"]["unavailable"]
    ]


def test_an_empty_or_incompatible_store_is_never_reported_as_measured(
    tmp_path: Path,
) -> None:
    """Mira-Krishnaiah on #272: a readable but empty store took the measured path.

    Every STORE_QUERIES entry fails against a store with none of the relations,
    so the outer status must stay unavailable and the store must stay in
    readiness.unavailable rather than reading as a satisfied input.
    """
    database = tmp_path / "empty.duckdb"
    with duckdb.connect(database.as_posix()) as connection:
        connection.execute("CREATE TABLE unrelated(x INTEGER)")
    probe = readiness.probe_county_grain_store(database)
    assert probe["status"] == "unavailable"
    assert probe["measured_relations"] == []
    assert probe["unmeasured_relations"] == sorted(readiness.STORE_QUERIES)
    assert probe["reason"] and probe["next_steps"]

    receipt = readiness.build_receipt(database=database)
    store = next(
        entry
        for entry in receipt["readiness"]["unavailable"]
        if entry["input"] == "county_grain_store"
    )
    assert store["status"] == "unavailable"
    assert store["next_steps"]


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


DOC = ROOT / "docs/data/minnesota-aggregate-readiness-receipt.md"


def _two_cell_rows(text: str) -> dict[str, str]:
    """Return every ``| `label` | value |`` row in the prose receipt.

    Only two-column tables match, which is exactly the set of tables in the
    document that publish a measured value: the committed-evidence digests and
    the two "Measured values" tables. The wider narrative tables have more
    columns and are skipped.
    """
    rows: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|") or not line.endswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) != 2:
            continue
        label, value = cells
        if not (label.startswith("`") and label.endswith("`")):
            continue
        rows[label.strip("`")] = value
    return rows


def _number(value: str) -> float:
    """Read the numeral out of a documented value such as ``18,211.53 MW``."""
    cleaned = value.strip("`").replace(",", "").replace("*", "")
    cleaned = cleaned.split(" of ")[0].removesuffix(" MW").strip()
    return float(cleaned)


def test_the_prose_receipt_numbers_come_from_the_rebuilt_receipt(
    receipt: dict,
) -> None:
    """Every measured number printed in the markdown must match the receipt.

    The prose companion is the document the PR body's tables were written from.
    Without this test a transcription error, or a later hand-edit, is invisible:
    the JSON is rebuilt and compared, the markdown was not.
    """
    documented = _two_cell_rows(DOC.read_text(encoding="utf-8"))
    measurements = receipt["aggregate_output"]["measurements"]
    stress = measurements["mn_agg_miso_demand_stress_index_v1"]["result"]
    capacity = measurements["mn_county_capacity_coverage"]["result"]
    window = measurements["miso_context_window"]["result"]
    digests = {
        check["file"]: check["observed_sha256"]
        for check in receipt["artifact_manifest"]["committed_evidence_checks"]
    }

    expected_numbers = {**stress, **capacity}
    expected_numbers.pop("window_peak_hour_utc")
    checked = 0
    for field, measured in expected_numbers.items():
        assert field in documented, f"{field} is not published in {DOC.name}"
        assert _number(documented[field]) == pytest.approx(float(measured)), field
        checked += 1
    assert checked == len(expected_numbers)

    assert documented["window_peak_hour_utc"] == stress["window_peak_hour_utc"]
    for name, observed in digests.items():
        assert documented[name].strip("`") == observed, name
    assert set(digests) <= set(documented)

    # The window sentence and the county denominator are prose, not table rows.
    text = " ".join(DOC.read_text(encoding="utf-8").split())
    assert (
        f"{window['hours']:,} hours from `{window['window_start_utc']}` to "
        f"`{window['window_end_utc']}`, with {window['null_demand_hours']} null "
        "demand hours" in text
    )
    assert (
        f"{capacity['counties_with_assigned_plants']} of 87"
        in documented["counties_with_assigned_plants"]
    )


def test_the_prose_gate_and_reconciliation_agree_with_the_receipt(
    receipt: dict,
) -> None:
    text = " ".join(DOC.read_text(encoding="utf-8").split())
    gate = receipt["topology_gate"]
    unmet = len(gate["unmet_items"])
    assert unmet == 5, "update the prose word 'five' if the gate item count moves"
    assert "has five required items" in text
    assert "Five of five items unmet" in text
    reconciliation = receipt["source_authority_ledger"][
        "retail_service_area_count_reconciliation"
    ]
    assert f"records {reconciliation['manifest_count']} rows" in text
    assert f"records {reconciliation['ledger_count']} features" in text
    assert reconciliation["ledger_count"] != reconciliation["manifest_count"]


def test_the_manifest_model_mode_is_read_and_must_agree(
    receipt: dict, tmp_path: Path
) -> None:
    """A manifest that declares a different mode stops the receipt."""
    assert receipt["artifact_manifest"]["model_mode"] == "aggregate"

    inputs = tmp_path / "inputs"
    inputs.mkdir()
    for name in (
        readiness.AGGREGATE_MANIFEST_FILE,
        readiness.CAPACITY_FILE,
        readiness.CONTEXT_FILE,
        "mn_unassigned_plant_capacity_2024.csv",
    ):
        (inputs / name).write_bytes((readiness.DEFAULT_INPUTS_DIR / name).read_bytes())
    manifest_path = inputs / readiness.AGGREGATE_MANIFEST_FILE
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["model_mode"] = "topology"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    with pytest.raises(readiness.ReadinessError, match="model_mode"):
        readiness.build_receipt(inputs_dir=inputs)

    del manifest["model_mode"]
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    with pytest.raises(readiness.ReadinessError, match="declares no model_mode"):
        readiness.build_receipt(inputs_dir=inputs)


def test_the_gate_verdict_is_tied_to_the_documents_it_cites(tmp_path: Path) -> None:
    """A revised or missing frozen record stops the gate instead of going stale."""
    gate = readiness.evaluate_topology_gate()
    assert gate["verdict_basis"]["derivation"] == "declared, not derived"
    cited = {entry["document"] for entry in gate["verdict_basis"]["checked_documents"]}
    assert cited == {
        document for item in gate["items"] for document in item["evidence_documents"]
    } | {readiness.GATE_0_APPROVAL_DOC, readiness.SOLVER_FEASIBILITY_DOC}
    for document in cited:
        assert (ROOT / document).is_file()

    # A checkout whose Gate 0 approval no longer names aggregate the only mode.
    for document in cited:
        target = tmp_path / document
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / document).read_bytes())
    approval = tmp_path / readiness.GATE_0_APPROVAL_DOC
    approval.write_text(
        approval.read_text(encoding="utf-8").replace(
            "Aggregate mode is the default\n  and only mode.",
            "Topology mode is now selectable.",
        ),
        encoding="utf-8",
    )
    with pytest.raises(readiness.ReadinessError, match="no longer states"):
        readiness.evaluate_topology_gate(root=tmp_path)

    approval.unlink()
    with pytest.raises(readiness.ReadinessError, match="is not present"):
        readiness.evaluate_topology_gate(root=tmp_path)


def test_the_source_authority_ledger_is_consulted(
    receipt: dict, tmp_path: Path
) -> None:
    """#224's ledger corroborates the verdict and cannot silently contradict it."""
    consulted = receipt["source_authority_ledger"]
    assert consulted["corroborates_topology_gate"] is True
    statuses = {
        entry["class_id"]: entry["status"]
        for entry in consulted["physical_class_coverage"]
    }
    assert statuses[readiness.CONNECTIVITY_LEDGER_CLASS] == "unavailable"

    ledger_path = readiness.DEFAULT_SOURCES_DIR / readiness.SOURCE_AUTHORITY_LEDGER_FILE
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    for entry in ledger["physical_class_coverage"]:
        if entry["class_id"] == readiness.CONNECTIVITY_LEDGER_CLASS:
            entry["status"] = "available"
    (tmp_path / readiness.SOURCE_AUTHORITY_LEDGER_FILE).write_text(
        json.dumps(ledger, indent=2), encoding="utf-8"
    )
    with pytest.raises(readiness.ReadinessError, match="disagree"):
        readiness.build_receipt(sources_dir=tmp_path)


def test_the_two_service_area_counts_are_reconciled_from_the_files(
    receipt: dict,
) -> None:
    """Both counts are read from their own record; neither is hardcoded prose."""
    reconciliation = receipt["source_authority_ledger"][
        "retail_service_area_count_reconciliation"
    ]
    ledger = json.loads(
        (
            readiness.DEFAULT_SOURCES_DIR / readiness.SOURCE_AUTHORITY_LEDGER_FILE
        ).read_text(encoding="utf-8")
    )
    ledger_count = next(
        record["verified_query"]["returned_feature_count"]
        for record in ledger["source_records"]
        if record["source_id"] == readiness.LEDGER_SERVICE_AREA_SOURCE
    )
    manifest = json.loads(
        (readiness.DEFAULT_INPUTS_DIR / readiness.AGGREGATE_MANIFEST_FILE).read_text(
            encoding="utf-8"
        )
    )
    manifest_count = next(
        source["rows"]
        for source in manifest["sources"]
        if source["id"] == readiness.MANIFEST_SERVICE_AREA_SOURCE
    )
    assert reconciliation["ledger_count"] == ledger_count
    assert reconciliation["manifest_count"] == manifest_count
    assert "authoritative_for_source_authority_and_class_coverage" in reconciliation
    assert "authoritative_for_this_receipt" in reconciliation
    assert reconciliation["why_they_differ"]


def test_the_readiness_unavailable_list_names_every_missing_input(
    receipt: dict,
) -> None:
    inputs = [entry["input"] for entry in receipt["readiness"]["unavailable"]]
    assert inputs == [
        "county_grain_store",
        "minnesota_solver_case",
        "ba_to_service_area_allocation_crosswalk",
    ]
    for entry in receipt["readiness"]["unavailable"]:
        assert entry["reason"] or entry.get("published_evidence")
        assert entry["next_steps"]
