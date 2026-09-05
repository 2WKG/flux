"""Behavioural checks for the Minnesota artifact fixture framework."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import duckdb
import pytest

from pipelines.fixtures.builder import (
    FixtureError,
    artifact_id_for,
    build_artifacts,
    load_manifest,
    main,
    write_minnesota_fixture,
)
from pipelines.fixtures.make_fixture_db import main as make_fixture_db
from pipelines.minnesota_schema import SCHEMA_VERSION

H = "a" * 64


def _identity(kind: str, content: str) -> dict[str, str]:
    return {
        "artifact_kind": kind,
        "geography_id": "mn",
        "model_mode": "not_applicable",
        "source_identity": "mngeo:utility-service-areas:2026-09",
        "source_version": "2026-09",
        "content_sha256": content,
    }


def _provenance(content: str = H) -> list[dict[str, object]]:
    return [
        {
            "source_name": "MnGeo utilities",
            "source_ref": "https://example.invalid/mngeo",
            "source_version": "2026-09",
            "retrieved_at": "2026-09-05T00:00:00Z",
            "license_or_terms": "public terms verified",
            "source_record_id": "utilities-2026-09",
            "content_sha256": content,
            "is_derived": False,
        }
    ]


def _artifact(kind: str, content: str, **extra: object) -> dict[str, object]:
    return {
        "artifact_kind": kind,
        "geography_id": "mn",
        "availability": "available",
        "model_mode": "not_applicable",
        "identity": _identity(kind, content),
        "created_at": "2026-09-05T00:00:00+00:00",
        "assumptions": ["metadata only"],
        "limitations": ["not a topology or scenario"],
        "input_artifact_ids": [],
        "provenance": _provenance(content),
        **extra,
    }


def _manifest() -> dict[str, object]:
    source = _artifact("source_manifest", H)
    source_id = artifact_id_for(source["identity"])
    fixture = _artifact(
        "fixture",
        "b" * 64,
        input_artifact_ids=[source_id],
        fixture={
            "source_manifest_id": source_id,
            "fixture_label": "Minnesota source-backed fixture metadata",
            "fallback_label": "no topology or scenario data included",
        },
    )
    return {"contract_version": SCHEMA_VERSION, "artifacts": [fixture, source]}


def _write_manifest(tmp_path: Path, manifest: dict[str, object]) -> Path:
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def test_framework_builds_only_contract_valid_minnesota_metadata():
    artifacts = build_artifacts(_manifest())
    assert [artifact["artifact_kind"] for artifact in artifacts] == [
        "fixture",
        "source_manifest",
    ]
    assert all(artifact["artifact_id"].startswith("mn:") for artifact in artifacts)


def test_artifact_identity_is_deterministic_and_requires_all_contract_fields():
    identity = _identity("source_manifest", H)
    assert artifact_id_for(identity) == artifact_id_for(
        dict(reversed(identity.items()))
    )
    with pytest.raises(FixtureError, match="identity fields must be exactly"):
        artifact_id_for({"artifact_kind": "fixture"})


def test_legacy_table_manifest_is_rejected_before_any_database_write(tmp_path):
    path = _write_manifest(
        tmp_path, {"contract_version": SCHEMA_VERSION, "tables": {"buses": {}}}
    )
    with pytest.raises(FixtureError, match="legacy table fixtures"):
        load_manifest(path)
    db = tmp_path / "grid.duckdb"
    with pytest.raises(FixtureError, match="legacy table fixtures"):
        main(path, db)
    assert not db.exists()


def test_bundled_default_refuses_to_invent_a_minnesota_fixture(tmp_path):
    db = tmp_path / "grid.duckdb"
    with pytest.raises(FixtureError, match="accepted source manifest"):
        main(db_path=db)
    assert not db.exists()


def test_available_fixture_requires_source_backed_provenance():
    manifest = _manifest()
    manifest["artifacts"][0]["provenance"] = []
    with pytest.raises(FixtureError, match="nonempty provenance"):
        build_artifacts(manifest)


def test_fixture_framework_rejects_an_implied_topology_or_aggregate_model():
    manifest = _manifest()
    manifest["artifacts"][0]["model_mode"] = "topology"
    manifest["artifacts"][0]["identity"]["model_mode"] = "topology"
    with pytest.raises(FixtureError, match="must not claim a model mode"):
        build_artifacts(manifest)


def test_fixture_must_reference_a_source_manifest_in_the_same_build():
    manifest = _manifest()
    manifest["artifacts"][0]["fixture"]["source_manifest_id"] = (
        "mn:source_manifest:missing"
    )
    with pytest.raises(FixtureError, match="source_manifest"):
        build_artifacts(manifest)


def test_writer_preserves_the_shared_database_and_uses_mn_namespace(tmp_path):
    db = tmp_path / "grid.duckdb"
    con = duckdb.connect(str(db))
    try:
        con.execute("CREATE TABLE legacy_data (value TEXT)")
        con.execute("INSERT INTO legacy_data VALUES ('preserve me')")
    finally:
        con.close()

    write_minnesota_fixture(build_artifacts(_manifest()), db)

    con = duckdb.connect(str(db), read_only=True)
    try:
        assert con.execute("SELECT value FROM legacy_data").fetchone() == (
            "preserve me",
        )
        assert con.execute("SELECT count(*) FROM mn_artifact_manifests").fetchone() == (
            2,
        )
        assert con.execute("SELECT count(*) FROM mn_fixture_artifacts").fetchone() == (
            1,
        )
        assert con.execute(
            "SELECT count(*) FROM mn_artifact_provenance"
        ).fetchone() == (2,)
    finally:
        con.close()


def test_failed_repeat_write_rolls_back_without_partial_metadata(tmp_path):
    db = tmp_path / "grid.duckdb"
    artifacts = build_artifacts(_manifest())
    write_minnesota_fixture(artifacts, db)
    with pytest.raises(duckdb.ConstraintException):
        write_minnesota_fixture(deepcopy(artifacts), db)
    con = duckdb.connect(str(db), read_only=True)
    try:
        assert con.execute("SELECT count(*) FROM mn_artifact_manifests").fetchone() == (
            2,
        )
    finally:
        con.close()


def test_cli_requires_an_explicit_source_backed_manifest(tmp_path):
    manifest_path = _write_manifest(tmp_path, _manifest())
    db = tmp_path / "fixture.duckdb"
    assert make_fixture_db(["--manifest", str(manifest_path), "--db", str(db)]) == 0
    assert db.exists()
