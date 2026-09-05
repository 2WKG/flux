from __future__ import annotations

import pytest

import pipelines.build as build_module
from pipelines.texas_db import TEXAS_DB_PATH, TEXAS_PARQUET_DIR


def test_texas_build_defaults_are_isolated_from_the_shared_release() -> None:
    assert build_module.build.__kwdefaults__ is None
    assert build_module.build.__defaults__ == ("data/raw", TEXAS_DB_PATH, None, TEXAS_PARQUET_DIR)
    assert TEXAS_PARQUET_DIR == "data/parquet/texas"


def test_incomplete_p0_build_does_not_mutate_or_export(tmp_path, monkeypatch) -> None:
    def should_not_run(*args, **kwargs):
        raise AssertionError("incomplete P0 build must not open or export a release")

    monkeypatch.setattr(build_module, "connect", should_not_run)
    monkeypatch.setattr(build_module, "export_parquet", should_not_run)

    with pytest.raises(build_module.IncompleteP0BuildError, match="EIA930_BALANCE_2024_Jul_Dec"):
        build_module.build(str(tmp_path / "raw"), str(tmp_path / "grid.duckdb"), "UTC")

    assert not (tmp_path / "grid.duckdb").exists()
