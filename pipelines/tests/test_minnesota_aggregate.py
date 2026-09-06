"""Checks for the committed, aggregate-only Minnesota source evidence."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from pipelines.minnesota_aggregate import FORMAT, MISO_LABEL, _miso_context

INPUTS = Path(__file__).parents[1] / "fixtures" / "inputs"


def test_committed_aggregate_manifest_pins_sources_and_refuses_allocation():
    manifest = json.loads(
        (INPUTS / "minnesota_aggregate_manifest_v1.json").read_text(encoding="utf-8")
    )

    assert manifest["format"] == FORMAT
    assert manifest["model_mode"] == "aggregate"
    assert manifest["allocation_status"] == "unavailable"
    sources = {source["id"]: source for source in manifest["sources"]}
    assert sources["tiger_counties_2024"]["rows"] == 87
    assert sources["mngeo_service_areas_2026"]["rows"] == 181
    assert sources["eia930_balance_2024_h1"]["label"] == MISO_LABEL
    assert all(len(source["sha256"]) == 64 for source in sources.values())


def test_compact_evidence_preserves_capacity_units_and_ba_identity():
    capacity = pd.read_csv(INPUTS / "mn_county_plant_capacity_2024.csv")
    context = pd.read_csv(INPUTS / "miso_ba_context_2024_h1.csv")

    assert set(capacity) == {"county_fips", "plant_count", "summer_capacity_mw"}
    assert (capacity["summer_capacity_mw"] >= 0).all()
    assert (capacity["summer_capacity_mw"] > 0).any()
    assert len(context) == 4368
    assert context["UTC Time at End of Hour"].is_unique
    assert context["Demand (MW)"].notna().all()


def test_miso_context_rejects_duplicate_or_missing_utc_rows(tmp_path):
    frame = pd.DataFrame(
        {
            "Balancing Authority": ["MISO", "MISO"],
            "UTC Time at End of Hour": ["2024-01-01T01:00:00Z"] * 2,
            "Demand (MW)": [1.0, 1.0],
            "Demand (MW) (Adjusted)": [1.0, 1.0],
            "Net Generation (MW)": [1.0, 1.0],
            "Total Interchange (MW)": [0.0, 0.0],
        }
    )
    path = tmp_path / "bad.csv"
    frame.to_csv(path, index=False)

    with pytest.raises(ValueError, match="repeat a UTC hour"):
        _miso_context(path)
