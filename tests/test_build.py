from __future__ import annotations

import json

import pytest

import pipelines.build as build_module


def test_incomplete_p0_build_does_not_mutate_or_export(tmp_path, monkeypatch) -> None:
    def should_not_run(*args, **kwargs):
        raise AssertionError("incomplete P0 build must not open or export a release")

    monkeypatch.setattr(build_module, "connect", should_not_run)
    monkeypatch.setattr(build_module, "export_parquet", should_not_run)

    with pytest.raises(build_module.IncompleteP0BuildError, match="EIA930_BALANCE_2024_Jul_Dec"):
        build_module.build(str(tmp_path / "raw"), str(tmp_path / "grid.duckdb"), "UTC")

    assert not (tmp_path / "grid.duckdb").exists()


def test_p0_preflight_reads_expected_paths_from_shared_dataset_catalog(tmp_path, monkeypatch) -> None:
    catalog = tmp_path / "catalog.json"
    catalog.write_text(json.dumps({"p0_raw_inputs": [{
        "label": "fixture input", "paths": [["current", "input.csv"], ["legacy.csv"]],
    }]}))
    monkeypatch.setattr(build_module, "P0_RAW_INPUTS_CATALOG", catalog)

    assert build_module._missing_p0_inputs(tmp_path / "raw", "UTC") == ["fixture input"]
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "legacy.csv").touch()
    assert build_module._missing_p0_inputs(raw, "UTC") == []
