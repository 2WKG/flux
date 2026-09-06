from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

import duckdb

from pipelines import preflight
from pipelines.db import connect


def _catalog(path, relative: str = "source/input.csv"):
    path.write_text(
        json.dumps(
            {"p0_raw_inputs": [{"label": relative, "paths": [relative.split("/")]}]}
        )
    )


def test_raw_receipt_records_observed_hash_and_a_matching_publisher_lock(tmp_path):
    raw = tmp_path / "raw"
    artifact = raw / "source" / "input.csv"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("a,b\n1,2\n")
    catalog = tmp_path / "catalog.json"
    _catalog(catalog)
    receipts = tmp_path / "receipts"
    receipts.mkdir()
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    (receipts / "source.json").write_text(
        json.dumps(
            {
                "retrieved_at": "2026-09-05T00:00:00+00:00",
                "files": {
                    "input.csv": {"sha256": digest, "bytes": artifact.stat().st_size}
                },
            }
        )
    )

    result = preflight.inspect_raw_inputs(raw, catalog=catalog, receipts_dir=receipts)

    item = result["artifacts"][0]
    assert item["status"] == "ready"
    assert item["observed"]["sha256"] == digest
    assert item["observed"]["schema_fingerprint"]
    assert item["lock"]["status"] == "verified"


def test_raw_receipt_distinguishes_unrecorded_and_mismatched_inputs(tmp_path):
    raw = tmp_path / "raw"
    artifact = raw / "source" / "input.csv"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("a\n")
    catalog = tmp_path / "catalog.json"
    _catalog(catalog)
    receipts = tmp_path / "receipts"
    receipts.mkdir()

    assert (
        preflight.inspect_raw_inputs(raw, catalog=catalog, receipts_dir=receipts)[
            "artifacts"
        ][0]["status"]
        == "present_unverified"
    )
    (receipts / "source.json").write_text(
        json.dumps({"files": {"input.csv": {"sha256": "0" * 64}}})
    )
    assert (
        preflight.inspect_raw_inputs(raw, catalog=catalog, receipts_dir=receipts)[
            "artifacts"
        ][0]["status"]
        == "checksum_mismatch"
    )


def test_legacy_database_inspection_is_read_only_and_requires_fresh_rebuild(tmp_path):
    database = tmp_path / "legacy.duckdb"
    con = duckdb.connect(str(database))
    con.execute("CREATE TABLE schema_meta(key TEXT, value TEXT)")
    con.execute("INSERT INTO schema_meta VALUES ('contract_version', '1.0.0')")
    con.close()
    before = hashlib.sha256(database.read_bytes()).hexdigest()

    result = preflight.inspect_database(database)

    assert result["status"] == "legacy_or_incompatible"
    assert result["compatibility"] == "incompatible"
    assert result["write_performed"] is False
    assert result["file_unchanged"] is True
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before
    assert "fresh output" in result["next_step"]


def test_strict_scenario_weather_readiness_rejects_empty_contract_database(
    tmp_path, monkeypatch
):
    database = tmp_path / "grid.duckdb"
    connect(database).close()
    monkeypatch.setattr(
        preflight,
        "inspect_raw_inputs",
        lambda *_args, **_kwargs: {
            "all_present": True,
            "no_checksum_mismatch": True,
            "all_locked_with_provenance": True,
            "artifacts": [],
        },
    )

    receipt = preflight.build_receipt(
        tmp_path / "raw", database=database, require_scenario_weather=True
    )

    assert receipt["built_database"]["scenario_weather"]["status"] == "unavailable"
    assert receipt["readiness"]["texas_full_flux_ready"] is False
    assert preflight._exit_code(receipt) == 1


def test_cli_returns_nonzero_for_required_scenario_weather(monkeypatch):
    monkeypatch.setattr(
        preflight,
        "build_receipt",
        lambda *_args, **_kwargs: {
            "readiness": {
                "texas_p0_safe_to_stage": True,
                "strict_provenance_ready": True,
                "texas_full_flux_ready": False,
            },
            "requirements": {
                "strict_provenance_requested": False,
                "scenario_weather_required": True,
            },
        },
    )

    assert preflight.main(["--state", "TX", "--require-scenario-weather"]) == 1


def _weather_scenario_database(tmp_path, *, weather_fips: str, weather_start: datetime):
    database = tmp_path / "weather.duckdb"
    scenario_start = datetime(2024, 2, 1, tzinfo=UTC)
    scenario_end = scenario_start + timedelta(hours=2)
    con = connect(database)
    try:
        for fips, state in (("48001", "TX"), ("27001", "MN")):
            con.execute(
                """INSERT INTO counties (county_fips, name, state, pop, geom_wkb, source_name, source_ref, fixture_batch_id)
                   VALUES (?, ?, ?, 1, 'x', 'fixture', 'fixture', 'fixture')""",
                [fips, state, state],
            )
        con.execute(
            """INSERT INTO scenarios (scenario_id, name, kind, ts_start, ts_end, source_name, source_ref, fixture_batch_id)
               VALUES ('weather_window', 'Weather window', 'historical', ?, ?, 'fixture', 'fixture', 'fixture')""",
            [scenario_start, scenario_end],
        )
        for hour in range(3):
            con.execute(
                """INSERT INTO weather_hourly (county_fips, ts, wind_ms, source_name, source_ref, fixture_batch_id)
                   VALUES (?, ?, 1.0, 'fixture', 'fixture', 'fixture')""",
                [weather_fips, weather_start + timedelta(hours=hour)],
            )
    finally:
        con.close()
    return database


def test_scenario_weather_rejects_complete_weather_from_another_state(tmp_path):
    database = _weather_scenario_database(
        tmp_path, weather_fips="27001", weather_start=datetime(2024, 2, 1, tzinfo=UTC)
    )

    result = preflight._scenario_weather_readiness(
        database, ("weather_window",), preflight.scope(["TX"])
    )

    state = result["scenarios"][0]["states"][0]
    assert result["status"] == "unavailable"
    assert state["weather_rows"] == 0
    assert state["ready"] is False


def test_scenario_weather_accepts_complete_in_scope_window(tmp_path):
    database = _weather_scenario_database(
        tmp_path, weather_fips="48001", weather_start=datetime(2024, 2, 1, tzinfo=UTC)
    )

    result = preflight._scenario_weather_readiness(
        database, ("weather_window",), preflight.scope(["Texas"])
    )

    state = result["scenarios"][0]["states"][0]
    assert result["status"] == "ready"
    assert state["weather_rows"] == state["expected_weather_rows"] == 3
    assert state["ready"] is True


def test_scenario_weather_rejects_in_scope_weather_outside_scenario_window(tmp_path):
    database = _weather_scenario_database(
        tmp_path, weather_fips="48001", weather_start=datetime(2024, 1, 1, tzinfo=UTC)
    )

    result = preflight._scenario_weather_readiness(
        database, ("weather_window",), preflight.scope(["TX"])
    )

    state = result["scenarios"][0]["states"][0]
    assert result["status"] == "unavailable"
    assert state["weather_rows"] == 0
    assert state["ready"] is False


def test_operations_alignment_blocks_dashboard_when_curated_source_has_no_canonical_id(
    tmp_path,
):
    database = tmp_path / "grid.duckdb"
    con = connect(database)
    try:
        con.execute(
            "INSERT INTO counties (county_fips, name, state, pop, geom_wkb, source_name, source_ref, fixture_batch_id) VALUES ('27001', 'fixture', 'MN', 1, 'x', 'unknown-source', 'x', 'fixture')"
        )
    finally:
        con.close()

    result = preflight._operation_id_alignment(database)

    assert result["status"] == "blocked"
    assert result["unoperated_source_ids"] == ["unknown-source"]


def test_operations_alignment_accepts_declared_loader_to_operation_mapping(tmp_path):
    database = tmp_path / "grid.duckdb"
    con = connect(database)
    try:
        con.execute(
            """INSERT INTO counties (county_fips, name, state, pop, geom_wkb, source_name, source_ref, fixture_batch_id)
               VALUES ('48001', 'fixture', 'TX', 1, 'x', 'eia930', 'x', 'fixture')"""
        )
    finally:
        con.close()

    result = preflight._operation_id_alignment(database)

    assert result["status"] == "ready"
    assert result["mapped_operation_ids"] == ["eia-930"]


def test_non_texas_context_is_state_configurable_but_never_implies_topology(tmp_path):
    tiger, nri = tmp_path / "counties.zip", tmp_path / "nri.zip"
    tiger.write_bytes(b"county-boundaries")
    nri.write_bytes(b"hazards")

    result = preflight.inspect_state_context(
        preflight.scope(["New York"]), tiger=tiger, nri=nri
    )

    context = result["selected_states"][0]
    assert context["state"]["usps"] == "NY"
    assert context["public_context_status"] == "ready_to_stage"
    assert context["topology"]["status"] == "decision_required"


def _fake_receipt(**readiness):
    base = {
        "exit_code_gate": "texas_p0_safe_to_stage",
        "selected_states_public_context_ready": False,
        "texas_p0_safe_to_stage": True,
        "strict_provenance_ready": True,
        "texas_full_flux_ready": True,
    }
    base.update(readiness)
    return {
        "readiness": base,
        "requirements": {
            "strict_provenance_requested": False,
            "scenario_weather_required": False,
        },
    }


def test_cli_exits_nonzero_when_texas_p0_is_not_safe_to_stage(monkeypatch):
    monkeypatch.setattr(
        preflight,
        "build_receipt",
        lambda *_args, **_kwargs: _fake_receipt(texas_p0_safe_to_stage=False),
    )

    assert preflight.main(["--state", "TX"]) == 1
    assert preflight._exit_code(_fake_receipt(texas_p0_safe_to_stage=True)) == 0


def test_empty_raw_dir_is_not_safe_to_stage_and_exits_nonzero(tmp_path):
    receipt = preflight.build_receipt(tmp_path / "raw", states=preflight.scope(["TX"]))

    assert receipt["readiness"]["exit_code_gate"] == "texas_p0_safe_to_stage"
    assert receipt["readiness"]["texas_p0_safe_to_stage"] is False
    assert preflight._exit_code(receipt) == 1


def test_non_texas_scope_exit_code_follows_the_selected_state_context(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        preflight,
        "inspect_raw_inputs",
        lambda *_args, **_kwargs: {
            "all_present": False,
            "no_checksum_mismatch": True,
            "all_locked_with_provenance": False,
            "artifacts": [{"status": "missing"}],
        },
    )
    tiger, nri = tmp_path / "counties.zip", tmp_path / "nri.zip"
    tiger.write_bytes(b"county-boundaries")
    nri.write_bytes(b"hazards")

    ready = preflight.build_receipt(
        tmp_path / "raw",
        states=preflight.scope(["MN", "New York"]),
        context_tiger=tiger,
        context_nri=nri,
    )
    incomplete = preflight.build_receipt(
        tmp_path / "raw", states=preflight.scope(["MN"]), context_tiger=tiger
    )
    texas = preflight.build_receipt(
        tmp_path / "raw",
        states=preflight.scope(["TX"]),
        context_tiger=tiger,
        context_nri=nri,
    )

    assert (
        ready["readiness"]["exit_code_gate"] == "selected_states_public_context_ready"
    )
    assert ready["readiness"]["texas_p0_safe_to_stage"] is False
    assert ready["readiness"]["selected_states_public_context_ready"] is True
    assert preflight._exit_code(ready) == 0
    assert incomplete["readiness"]["selected_states_public_context_ready"] is False
    assert preflight._exit_code(incomplete) == 1
    assert texas["readiness"]["exit_code_gate"] == "texas_p0_safe_to_stage"
    assert preflight._exit_code(texas) == 1


def test_database_inspection_derives_write_performed_from_the_connection_mode(
    tmp_path,
):
    database = tmp_path / "legacy.duckdb"
    connect(database).close()

    result = preflight.inspect_database(database)

    assert result["status"] == "compatible"
    assert result["access_mode"] == "read_only"
    assert result["write_performed"] is False


class _PassedCheck:
    def __init__(self):
        self.name = "fixture"
        self.passed = True


def test_texas_full_flux_ready_requires_scenario_weather_on_an_otherwise_ready_db(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(preflight, "run_checks", lambda _path: [_PassedCheck()])
    monkeypatch.setattr(
        preflight, "_operation_id_alignment", lambda _path: {"status": "ready"}
    )
    monkeypatch.setattr(
        preflight,
        "inspect_raw_inputs",
        lambda *_args, **_kwargs: {
            "all_present": True,
            "no_checksum_mismatch": True,
            "all_locked_with_provenance": True,
            "artifacts": [],
        },
    )
    database = _weather_scenario_database(
        tmp_path, weather_fips="48001", weather_start=datetime(2024, 2, 1, tzinfo=UTC)
    )

    without_weather = preflight.build_receipt(
        tmp_path / "raw",
        database=database,
        states=preflight.scope(["TX"]),
        scenarios=("missing_scenario",),
    )
    with_weather = preflight.build_receipt(
        tmp_path / "raw",
        database=database,
        states=preflight.scope(["TX"]),
        scenarios=("weather_window",),
    )

    assert without_weather["built_database"]["status"] == "ready"
    assert without_weather["readiness"]["dashboard_release_ready"] is True
    assert without_weather["readiness"]["texas_full_flux_ready"] is False
    assert with_weather["readiness"]["texas_full_flux_ready"] is True


def test_database_open_elsewhere_is_reported_locked_not_rebuild(tmp_path):
    database = tmp_path / "grid.duckdb"
    holder = duckdb.connect(str(database))
    try:
        result = preflight.inspect_database(database)
    finally:
        holder.close()

    assert result["status"] == "locked"
    assert result["compatibility"] == "unknown"
    assert result["write_performed"] is False
    assert result["next_step"].startswith("Close the other process")
    # Once the holder is gone the same file inspects normally.
    assert preflight.inspect_database(database)["status"] != "locked"


def test_unreadable_raw_artifact_is_enveloped_not_raised(tmp_path, monkeypatch):
    raw = tmp_path / "raw"
    artifact = raw / "source" / "input.csv"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("a\n")
    catalog = tmp_path / "catalog.json"
    _catalog(catalog)
    receipts = tmp_path / "receipts"
    receipts.mkdir()

    def denied(_path):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(preflight, "sha256_file", denied)

    result = preflight.inspect_raw_inputs(raw, catalog=catalog, receipts_dir=receipts)

    item = result["artifacts"][0]
    assert item["status"] == "unreadable"
    assert "PermissionError" in item["error"]
    assert item["lock"]["status"] == "not_checked"
    assert result["no_checksum_mismatch"] is False


def test_unwritable_report_path_returns_error_envelope(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        preflight, "build_receipt", lambda *_args, **_kwargs: _fake_receipt()
    )
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("file")

    code = preflight.main(["--state", "TX", "--report", str(blocker / "receipt.json")])

    captured = capsys.readouterr()
    envelope = json.loads(captured.err)
    assert code == preflight.ERROR_EXIT_CODE == 2
    assert envelope["status"] == "error"
    assert envelope["reason"] == "report_not_written"
    assert envelope["write_performed"] is False


def test_invalid_catalog_returns_error_envelope(tmp_path, monkeypatch, capsys):
    catalog = tmp_path / "catalog.json"
    catalog.write_text("{not json")
    monkeypatch.setattr(preflight, "P0_RAW_INPUTS_CATALOG", catalog)

    code = preflight.main(["--state", "TX", "--raw-dir", str(tmp_path / "raw")])

    captured = capsys.readouterr()
    envelope = json.loads(captured.err)
    assert code == 2
    assert captured.out == ""
    assert envelope["status"] == "error"
    assert envelope["reason"] == "receipt_not_built"
    assert "invalid P0 raw-input catalog" in envelope["error"]


def test_preflight_reads_the_builders_p0_contract():
    from pipelines import build

    assert preflight._p0_raw_inputs is build._p0_raw_inputs
    assert not hasattr(preflight, "_catalog_inputs")
