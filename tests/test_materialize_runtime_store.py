import shutil
from pathlib import Path

import duckdb
import pytest

from scripts.materialize_runtime_store import (
    MaterializationError,
    _derived_rows,
    _published_releases,
    _require_hash,
    sha256_file,
)


def test_require_hash_rejects_a_receipt_that_does_not_bind_the_bytes(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "artifact.bin"
    artifact.write_bytes(b"real bytes")
    assert _require_hash(artifact, sha256_file(artifact), "fixture") == sha256_file(
        artifact
    )
    with pytest.raises(MaterializationError, match="SHA-256 mismatch"):
        _require_hash(artifact, "0" * 64, "fixture")


def test_derived_rows_identifies_products_that_must_not_be_erased(
    tmp_path: Path,
) -> None:
    database = tmp_path / "runtime.duckdb"
    con = duckdb.connect(str(database))
    con.execute("CREATE TABLE cascade_runs (run_id TEXT)")
    con.execute("INSERT INTO cascade_runs VALUES ('uri_2021-s0')")
    con.execute("CREATE TABLE outage_predictions (scenario_id TEXT)")
    con.close()
    assert _derived_rows(database) == {"cascade_runs": 1}


def test_published_releases_rejects_a_self_consistent_replacement(
    tmp_path: Path,
) -> None:
    root = tmp_path / "physical_inventory"
    source_root = (
        Path(__file__).resolve().parents[1] / "data/artifacts/physical_inventory"
    )
    for state in ("tx", "mn"):
        directory = root / state
        directory.mkdir(parents=True)
        shutil.copy2(
            source_root / state / "physical-inventory-1.1.0.json.gz",
            directory / "physical-inventory-1.1.0.json.gz",
        )
    shutil.copy2(source_root / "manifest-1.1.0.json", root / "manifest-1.1.0.json")
    # The Minnesota release remains an internally valid, self-consistent artifact,
    # but it is not the TX release pinned by the published manifest.
    shutil.copy2(
        source_root / "mn/physical-inventory-1.1.0.json.gz",
        root / "tx/physical-inventory-1.1.0.json.gz",
    )

    with pytest.raises(
        MaterializationError, match="published tx inventory.*SHA-256 mismatch"
    ):
        _published_releases(root, "1.1.0")
