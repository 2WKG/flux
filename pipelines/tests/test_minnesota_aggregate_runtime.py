from __future__ import annotations

import hashlib
import json
from pathlib import Path

import duckdb
import pytest

from pipelines.fixtures.builder import artifact_id_for
from pipelines.minnesota_aggregate_runtime import (
    METRIC_NAME,
    AggregateRuntimeError,
    aggregate_identity,
    build_aggregate_runtime,
    load_aggregate_inputs,
    verify_gate0_inputs,
)

ROOT = Path(__file__).resolve().parents[2]


def _source_db(path: Path) -> None:
    con = duckdb.connect(str(path))
    try:
        con.execute("CREATE TABLE retained_source (value TEXT)")
        con.execute("INSERT INTO retained_source VALUES ('unchanged')")
    finally:
        con.close()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_gate0_input_verification_checks_the_exact_approved_inventory_and_hashes():
    inventory, approved = verify_gate0_inputs(repository_root=ROOT)

    assert inventory["inventory_id"] == "minnesota-accepted-artifacts-v1"
    assert [item.artifact_id for item in approved] == [
        "mn:aggregate:manifest:v1",
        "mn:facility_capacity:county:2024",
        "mn:facility_context:unassigned:2024",
        "mn:ba_context:miso:2024-h1",
    ]
    assert [item.content_sha256 for item in approved] == [
        "f287a1dfbafddff8bd9f0ec989d488ad6743609280b19338eca048c3d5858e05",
        "7757c6ece5c36a0ae15573acfe4dd2e02cb42e13a0aa9f8ac142663977e7d573",
        "926f6fb65715df19af1eb833df1560c6e592827d7ea47ed54091cf3cf08a4ed6",
        "395dad9aea19226744f8be5f91ca30c783ab776d1720e6486ff64880b8366e6f",
    ]


def test_runtime_build_is_atomic_preserves_source_and_persists_aggregate_truth(
    tmp_path: Path,
):
    source, output = tmp_path / "source.duckdb", tmp_path / "aggregate.duckdb"
    _source_db(source)
    source_hash = _sha256(source)

    receipt = build_aggregate_runtime(
        source_db=source, output_db=output, repository_root=ROOT
    )

    assert output.is_file()
    assert _sha256(source) == source_hash
    assert receipt["artifact_id"] == artifact_id_for(
        aggregate_identity(receipt["manifest_sha256"])
    )
    assert receipt["metric_name"] == METRIC_NAME
    assert receipt["metric_value"] == 109244.0
    assert receipt["window_peak_hour_utc"] == "2024-06-24T23:00:00Z"
    assert receipt["scored_hours"] == 4368

    source_con = duckdb.connect(str(source), read_only=True)
    try:
        assert source_con.execute("SHOW TABLES").fetchall() == [("retained_source",)]
    finally:
        source_con.close()
    con = duckdb.connect(str(output), read_only=True)
    try:
        assert con.execute("SELECT value FROM retained_source").fetchone() == (
            "unchanged",
        )
        assert con.execute("SELECT value FROM mn_schema_meta").fetchone() == (
            "2.0.0-mn",
        )
        manifest = con.execute(
            "SELECT model_mode, identity_json, input_artifact_ids_json FROM mn_artifact_manifests"
        ).fetchone()
        assert manifest[0] == "aggregate"
        assert json.loads(manifest[1]) == aggregate_identity(receipt["manifest_sha256"])
        assert json.loads(manifest[2]) == [
            "mn:aggregate:manifest:v1",
            "mn:facility_capacity:county:2024",
            "mn:facility_context:unassigned:2024",
            "mn:ba_context:miso:2024-h1",
        ]
        model = con.execute(
            "SELECT metric_name, metric_value, metric_unit, formula, base_mva, solver_version, converter_version FROM mn_model_results"
        ).fetchone()
        assert model[:3] == (METRIC_NAME, 109244.0, "MW")
        assert "not Minnesota demand" in model[3]
        assert model[4:] == (None, None, None)
        components = json.loads(
            con.execute(
                "SELECT score_components_json FROM mn_score_results"
            ).fetchone()[0]
        )
        assert components["artifact_version"] == "v1"
        assert components["aggregate_manifest"]["allocation_status"] == "unavailable"
        assert set(components["stress_context"]) == {
            "source_label",
            "time_basis",
            "window_start_utc",
            "window_end_utc",
            "window_peak_demand_mw",
            "window_peak_hour_utc",
            "scored_hours",
            "min_index",
            "mean_index",
            "p95_index",
        }
        assert components["stress_context"]["scored_hours"] == 4368
        assert (
            components["stress_context"]["window_peak_hour_utc"]
            == "2024-06-24T23:00:00Z"
        )
        assert "Minnesota demand allocation" in components["prohibited_claims"]
        assert con.execute(
            "SELECT count(*) FROM mn_artifact_provenance"
        ).fetchone() == (4,)
        assert con.execute(
            "SELECT count(*) FROM mn_geography_artifacts"
        ).fetchone() == (0,)
    finally:
        con.close()


def test_build_requires_a_new_distinct_output_and_leaves_existing_files_untouched(
    tmp_path: Path,
):
    source, output = tmp_path / "source.duckdb", tmp_path / "existing.duckdb"
    _source_db(source)
    _source_db(output)
    existing_hash = _sha256(output)

    with pytest.raises(AggregateRuntimeError, match="already exists"):
        build_aggregate_runtime(
            source_db=source, output_db=output, repository_root=ROOT
        )
    assert _sha256(output) == existing_hash
    with pytest.raises(AggregateRuntimeError, match="must differ"):
        build_aggregate_runtime(
            source_db=source, output_db=source, repository_root=ROOT
        )


def test_runtime_rejects_symlink_source_or_output_paths(tmp_path: Path):
    source, output = tmp_path / "source.duckdb", tmp_path / "aggregate.duckdb"
    _source_db(source)
    source_link = tmp_path / "source-link.duckdb"
    output_link = tmp_path / "output-link.duckdb"
    source_link.symlink_to(source)
    output_link.symlink_to(output)

    with pytest.raises(
        AggregateRuntimeError, match="source database path must not be a symlink"
    ):
        build_aggregate_runtime(
            source_db=source_link, output_db=output, repository_root=ROOT
        )
    with pytest.raises(
        AggregateRuntimeError, match="output database path must not be a symlink"
    ):
        build_aggregate_runtime(
            source_db=source, output_db=output_link, repository_root=ROOT
        )
    assert not output.exists()


def test_runtime_rejects_a_source_that_already_has_a_minnesota_namespace(
    tmp_path: Path,
):
    source, output = tmp_path / "source.duckdb", tmp_path / "aggregate.duckdb"
    _source_db(source)
    con = duckdb.connect(str(source))
    try:
        con.execute("CREATE TABLE mn_unrelated (value TEXT)")
    finally:
        con.close()

    with pytest.raises(
        AggregateRuntimeError, match="already has a Minnesota namespace"
    ):
        build_aggregate_runtime(
            source_db=source, output_db=output, repository_root=ROOT
        )
    assert not output.exists()


def test_bad_gate0_hash_creates_no_output(tmp_path: Path):
    source, output = tmp_path / "source.duckdb", tmp_path / "aggregate.duckdb"
    _source_db(source)
    inventory = json.loads(
        (ROOT / "data/sources/minnesota-accepted-artifact-inventory.json").read_text()
    )
    inventory["accepted_product_artifacts"][0]["content_sha256"] = "sha256:" + "0" * 64
    tampered = tmp_path / "inventory.json"
    tampered.write_text(json.dumps(inventory), encoding="utf-8")

    with pytest.raises(AggregateRuntimeError, match="SHA-256 mismatch"):
        build_aggregate_runtime(
            source_db=source,
            output_db=output,
            repository_root=ROOT,
            inventory_path=tampered,
        )
    assert not output.exists()


def test_aggregate_input_metric_stays_miso_context_without_allocation():
    inputs = load_aggregate_inputs(repository_root=ROOT)

    assert inputs.manifest["allocation_status"] == "unavailable"
    assert inputs.peak_demand_mw == 109244.0
    assert inputs.peak_hour_utc == "2024-06-24T23:00:00Z"
    assert inputs.scored_hours == 4368
    assert inputs.window_start_utc == "2024-01-01T06:00:00Z"
    assert inputs.window_end_utc == "2024-07-01T05:00:00Z"
    assert 0 < inputs.min_index <= inputs.mean_index <= inputs.p95_index <= 1
