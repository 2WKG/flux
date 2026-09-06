from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from pipelines import build as build_module
from pipelines.db import CONTRACT_TABLES, connect


def _seed_live_release(tmp_path: Path) -> tuple[Path, Path]:
    db_path = tmp_path / "data" / "duck" / "grid.duckdb"
    con = connect(db_path)
    try:
        con.execute("CREATE TABLE mn_private (value TEXT PRIMARY KEY)")
        con.execute("INSERT INTO mn_private VALUES ('preserve-me')")
        con.execute("CREATE TABLE release_marker (value TEXT PRIMARY KEY)")
        con.execute("INSERT INTO release_marker VALUES ('old')")
    finally:
        con.close()
    parquet_dir = tmp_path / "data" / "parquet"
    parquet_dir.mkdir(parents=True)
    (parquet_dir / "unrelated.parquet").write_bytes(b"unchanged-sentinel")
    return db_path, parquet_dir


def _published_state(
    db_path: Path, parquet_dir: Path
) -> tuple[tuple[str, ...], str, dict[str, bytes]]:
    con = connect(db_path, read_only=True)
    try:
        namespaces = tuple(
            row[0]
            for row in con.execute(
                "SELECT value FROM mn_private ORDER BY value"
            ).fetchall()
        )
        marker = con.execute("SELECT value FROM release_marker").fetchone()[0]
    finally:
        con.close()
    files = {
        path.name: path.read_bytes() for path in parquet_dir.iterdir() if path.is_file()
    }
    return namespaces, marker, files


def _staged_builder(marker: str):
    def build_stage(
        _raw_dir: str, db_path: str, _tz: str | None, parquet_dir: str, **_kwargs
    ) -> dict[str, int]:
        con = connect(db_path)
        try:
            con.execute("DELETE FROM release_marker")
            con.execute("INSERT INTO release_marker VALUES (?)", [marker])
            con.execute("CREATE TABLE IF NOT EXISTS staged_p0 (value TEXT PRIMARY KEY)")
            con.execute("INSERT OR REPLACE INTO staged_p0 VALUES (?)", [marker])
        finally:
            con.close()
        Path(parquet_dir, f"{marker}.parquet").write_bytes(marker.encode())
        return {"staged": 1}

    return build_stage


def _passing_checks(_db_path: str, _states=None) -> list[SimpleNamespace]:
    return [SimpleNamespace(name="fixture", passed=True)]


def test_preflight_failure_does_not_create_or_change_live_release(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    db_path, parquet_dir = _seed_live_release(tmp_path)
    before = _published_state(db_path, parquet_dir)

    with pytest.raises(build_module.IncompleteP0BuildError):
        build_module.build(str(tmp_path / "raw-missing"), str(db_path), "UTC")

    assert _published_state(db_path, parquet_dir) == before


@pytest.mark.parametrize("phase", ["early_loader", "late_loader"])
def test_loader_failure_never_publishes_staged_database_or_parquet(
    tmp_path, monkeypatch, phase
):
    monkeypatch.chdir(tmp_path)
    db_path, parquet_dir = _seed_live_release(tmp_path)
    before = _published_state(db_path, parquet_dir)
    monkeypatch.setattr(build_module, "_missing_p0_inputs", lambda *_args: [])

    def fail_after_staging(
        _raw_dir: str, stage_db: str, _tz: str | None, stage_parquet: str, **_kwargs
    ) -> dict[str, int]:
        _staged_builder(phase)(_raw_dir, stage_db, _tz, stage_parquet)
        raise RuntimeError(f"{phase} failed")

    monkeypatch.setattr(build_module, "_build_mutating", fail_after_staging)
    with pytest.raises(RuntimeError, match=phase):
        build_module.build(str(tmp_path / "raw"), str(db_path), "UTC")

    assert _published_state(db_path, parquet_dir) == before


def test_failed_staged_validation_never_publishes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db_path, parquet_dir = _seed_live_release(tmp_path)
    before = _published_state(db_path, parquet_dir)
    monkeypatch.setattr(build_module, "_missing_p0_inputs", lambda *_args: [])
    monkeypatch.setattr(
        build_module, "_build_mutating", _staged_builder("validation-only")
    )
    monkeypatch.setattr(
        build_module,
        "run_checks",
        lambda _path, _states=None: [SimpleNamespace(name="reject", passed=False)],
    )

    with pytest.raises(RuntimeError, match="staged P0 quality checks failed"):
        build_module.build(str(tmp_path / "raw"), str(db_path), "UTC")

    assert _published_state(db_path, parquet_dir) == before


def test_promotion_failure_restores_database_and_parquet_release(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db_path, parquet_dir = _seed_live_release(tmp_path)
    before = _published_state(db_path, parquet_dir)
    monkeypatch.setattr(build_module, "_missing_p0_inputs", lambda *_args: [])
    monkeypatch.setattr(build_module, "_build_mutating", _staged_builder("new"))
    monkeypatch.setattr(build_module, "run_checks", _passing_checks)
    real_replace = build_module.os.replace

    def fail_parquet_publish(source, destination):
        if (
            Path(source).name == "parquet"
            and Path(destination).resolve() == parquet_dir
        ):
            raise OSError("simulated parquet promotion failure")
        return real_replace(source, destination)

    monkeypatch.setattr(build_module.os, "replace", fail_parquet_publish)
    with pytest.raises(OSError, match="simulated parquet promotion failure"):
        build_module.build(str(tmp_path / "raw"), str(db_path), "UTC")

    assert _published_state(db_path, parquet_dir) == before


def test_successful_publish_preserves_existing_namespaces_and_parquet(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    db_path, parquet_dir = _seed_live_release(tmp_path)
    monkeypatch.setattr(build_module, "_missing_p0_inputs", lambda *_args: [])
    monkeypatch.setattr(build_module, "_build_mutating", _staged_builder("new"))
    monkeypatch.setattr(build_module, "run_checks", _passing_checks)

    assert build_module.build(str(tmp_path / "raw"), str(db_path), "UTC") == {
        "staged": 1
    }
    namespaces, marker, files = _published_state(db_path, parquet_dir)
    assert namespaces == ("preserve-me",)
    assert marker == "new"
    # The staged manifest is promoted together with the Parquet export.
    manifest = json.loads(files.pop("manifest.json"))
    assert set(manifest["tables"]) == set(CONTRACT_TABLES)
    assert files == {"unrelated.parquet": b"unchanged-sentinel", "new.parquet": b"new"}


@pytest.mark.parametrize("failed_restore", ["previous.duckdb", "previous-parquet"])
def test_failed_rollback_retains_recovery_and_restores_other_artifact(
    tmp_path, monkeypatch, failed_restore
):
    monkeypatch.chdir(tmp_path)
    db_path, parquet_dir = _seed_live_release(tmp_path)
    monkeypatch.setattr(build_module, "_missing_p0_inputs", lambda *_args: [])
    monkeypatch.setattr(build_module, "_build_mutating", _staged_builder("new"))
    monkeypatch.setattr(build_module, "run_checks", _passing_checks)
    real_replace = build_module.os.replace

    def fail_publish_and_one_restore(source, destination):
        if (
            Path(source).name == "parquet"
            and Path(destination).resolve() == parquet_dir
        ):
            raise OSError("promotion failed")
        if Path(source).name == failed_restore:
            raise OSError("restore failed")
        return real_replace(source, destination)

    monkeypatch.setattr(build_module.os, "replace", fail_publish_and_one_restore)
    with pytest.raises(
        build_module.PublicationRecoveryError, match="recovery files retained at"
    ) as error:
        build_module.build(str(tmp_path / "raw"), str(db_path), "UTC")

    recovery_roots = list(db_path.parent.glob(".grid-stage-*"))
    assert len(recovery_roots) == 1
    recovery = recovery_roots[0]
    assert str(recovery) in str(error.value)
    recovered_db = (
        recovery / failed_restore if failed_restore == "previous.duckdb" else db_path
    )
    con = connect(recovered_db, read_only=True)
    try:
        assert con.execute("SELECT value FROM release_marker").fetchone() == ("old",)
        assert con.execute("SELECT value FROM mn_private").fetchone() == (
            "preserve-me",
        )
    finally:
        con.close()
    recovered_parquet = (
        recovery / failed_restore
        if failed_restore == "previous-parquet"
        else parquet_dir
    )
    assert (
        recovered_parquet / "unrelated.parquet"
    ).read_bytes() == b"unchanged-sentinel"


def test_snapshot_copies_populated_foreign_keys_and_unrelated_namespaces(tmp_path):
    source, stage = tmp_path / "live.duckdb", tmp_path / "staged.duckdb"
    con = connect(source)
    try:
        con.execute(
            "INSERT INTO counties (county_fips, name, state, pop, geom_wkb, source_name, "
            "source_ref, fixture_batch_id) VALUES ('27001','fixture','MN',1,'fixture','test','test','test')"
        )
        con.execute(
            "INSERT INTO eaglei_outages (county_fips, ts, customers_out, source_name, "
            "source_ref, fixture_batch_id) VALUES ('27001','2024-01-01',7,'test','test','test')"
        )
        con.execute('CREATE SCHEMA "other space"')
        con.execute('CREATE TABLE "other space".z_parent (id INTEGER PRIMARY KEY)')
        con.execute(
            'CREATE TABLE "other space".a_child (id INTEGER REFERENCES "other space".z_parent(id))'
        )
        con.execute('INSERT INTO "other space".z_parent VALUES (42)')
        con.execute('INSERT INTO "other space".a_child VALUES (42)')
        con.execute(
            'CREATE VIEW "other space".summary AS SELECT count(*) AS n FROM "other space".a_child'
        )
    finally:
        con.close()
    build_module._copy_database(source, stage)
    copied = connect(stage, read_only=True)
    try:
        assert copied.execute(
            "SELECT county_fips, customers_out FROM eaglei_outages"
        ).fetchall() == [("27001", 7)]
        assert copied.execute('SELECT * FROM "other space".a_child').fetchall() == [
            (42,)
        ]
        assert copied.execute('SELECT * FROM "other space".summary').fetchone() == (1,)
        assert copied.execute(
            "SELECT count(*) FROM duckdb_constraints() WHERE schema_name = 'other space' "
            "AND constraint_type = 'FOREIGN KEY'"
        ).fetchone() == (1,)
    finally:
        copied.close()
