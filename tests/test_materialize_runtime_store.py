from pathlib import Path

import duckdb
import pytest

from scripts.materialize_runtime_store import (
    MaterializationError,
    _derived_rows,
    _require_hash,
    sha256_file,
)


def test_require_hash_rejects_a_receipt_that_does_not_bind_the_bytes(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.bin"
    artifact.write_bytes(b"real bytes")
    assert _require_hash(artifact, sha256_file(artifact), "fixture") == sha256_file(artifact)
    with pytest.raises(MaterializationError, match="SHA-256 mismatch"):
        _require_hash(artifact, "0" * 64, "fixture")


def test_derived_rows_identifies_products_that_must_not_be_erased(tmp_path: Path) -> None:
    database = tmp_path / "runtime.duckdb"
    con = duckdb.connect(str(database))
    con.execute("CREATE TABLE cascade_runs (run_id TEXT)")
    con.execute("INSERT INTO cascade_runs VALUES ('uri_2021-s0')")
    con.execute("CREATE TABLE outage_predictions (scenario_id TEXT)")
    con.close()
    assert _derived_rows(database) == {"cascade_runs": 1}
