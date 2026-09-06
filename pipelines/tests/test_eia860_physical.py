from __future__ import annotations

import gzip
import hashlib
import json
import zipfile
from pathlib import Path

import pandas as pd
import pytest

from pipelines.eia860_physical import (
    GENERATOR_MEMBER,
    PLANT_MEMBER,
    STORAGE_MEMBER,
    EIA860PhysicalError,
    build_eia860_physical_inventory,
)


@pytest.fixture()
def eia860_archive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    archive_path = tmp_path / "eia8602025ER.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        for member in (PLANT_MEMBER, GENERATOR_MEMBER, STORAGE_MEMBER):
            archive.writestr(member, b"placeholder")
    frames = iter(
        [
            pd.DataFrame(
                [
                    {
                        "Plant Code": 10,
                        "Plant Name": "Texas Plant",
                        "State": "TX",
                        "Latitude": 31.25,
                        "Longitude": -98.5,
                        "County": "Example",
                        "Balancing Authority Code": "ERCO",
                        "Grid Voltage (kV)": 138,
                    },
                    {
                        "Plant Code": 20,
                        "Plant Name": "Minnesota Plant",
                        "State": "MN",
                        "Latitude": 45.0,
                        "Longitude": -93.0,
                        "County": "Example",
                        "Balancing Authority Code": "MISO",
                        "Grid Voltage (kV)": 115,
                    },
                    {
                        "Plant Code": 30,
                        "Plant Name": "Missing location",
                        "State": "TX",
                        "Latitude": None,
                        "Longitude": None,
                    },
                ]
            ),
            pd.DataFrame(
                [
                    {
                        "Plant Code": 10,
                        "State": "TX",
                        "Generator ID": "G1",
                        "Status": "OP",
                        "Nameplate Capacity (MW)": 90,
                        "Summer Capacity (MW)": 80,
                        "Winter Capacity (MW)": 100,
                        "Technology": "Combustion",
                        "Prime Mover": "CT",
                        "Energy Source 1": "NG",
                    }
                ]
            ),
            pd.DataFrame(
                [
                    {
                        "Plant Code": 10,
                        "State": "TX",
                        "Generator ID": "G2",
                        "Status": "V",
                        "Nameplate Capacity (MW)": 20,
                    }
                ]
            ),
            pd.DataFrame(
                [
                    {
                        "Plant Code": 10,
                        "State": "TX",
                        "Generator ID": "G3",
                        "Status": "RE",
                        "Nameplate Capacity (MW)": 10,
                    }
                ]
            ),
            pd.DataFrame(
                [
                    {
                        "Plant Code": 10,
                        "State": "TX",
                        "Generator ID": "G1",
                        "Status": "OP",
                        "Nameplate Capacity (MW)": 50,
                        "Nameplate Energy Capacity (MWh)": 200,
                        "Maximum Charge Rate (MW)": 50,
                        "Maximum Discharge Rate (MW)": 50,
                        "Technology": "Batteries",
                        "Prime Mover": "BA",
                        "Storage Technology 1": "LIB",
                    }
                ]
            ),
            pd.DataFrame(
                columns=[
                    "Plant Code",
                    "State",
                    "Generator ID",
                    "Status",
                    "Nameplate Capacity (MW)",
                ]
            ),
            pd.DataFrame(
                columns=[
                    "Plant Code",
                    "State",
                    "Generator ID",
                    "Status",
                    "Nameplate Capacity (MW)",
                ]
            ),
        ]
    )
    monkeypatch.setattr(
        "pipelines.eia860_physical.pd.read_excel", lambda *args, **kwargs: next(frames)
    )
    return archive_path


def test_eia860_observations_keep_plant_point_and_unit_attachments_separate(
    eia860_archive: Path,
):
    inventory = build_eia860_physical_inventory(
        eia860_archive, states=["TX", "MN"], retrieved_at="2026-09-06T12:00:00Z"
    )
    texas = next(
        row for row in inventory["records"] if row["asset_id"] == "eia:plant:10"
    )
    assert texas["geometry"] == {"type": "Point", "coordinates": [-98.5, 31.25]}
    assert texas["attributes"]["unit_coordinate_status"] == "unavailable"
    assert texas["attributes"]["electrical_connectivity_status"] == "unavailable"
    assert texas["attributes"]["generator_units"][0]["energy_source_1"] == "NG"
    assert (
        texas["attributes"]["storage_units"][0]["nameplate_energy_capacity_mwh"]
        == 200.0
    )
    assert all(
        row["asset_kind"] == "generation_facility" for row in inventory["records"]
    )
    coverage = {row["class_id"]: row for row in inventory["coverage"]}
    assert coverage["generation_facility"]["denominator"] == 3
    assert coverage["generation_facility"]["unknown_count"] == 1
    assert coverage["unit_native_coordinate"]["unavailable_count"] == 4
    assert coverage["electrical_connectivity"]["denominator"] is None
    assert (
        inventory["source"]["content_sha256"]
        == hashlib.sha256(eia860_archive.read_bytes()).hexdigest()
    )


def test_eia860_requires_explicit_timezone_and_expected_source_columns(
    eia860_archive: Path,
):
    with pytest.raises(EIA860PhysicalError, match="UTC offset"):
        build_eia860_physical_inventory(
            eia860_archive, states=["TX"], retrieved_at="2026-09-06T12:00:00"
        )


def test_contract_adapter_preserves_units_without_promoting_their_plant_point(
    eia860_archive: Path, monkeypatch: pytest.MonkeyPatch
):
    pytest.importorskip("pipelines.physical_inventory")
    from pipelines.eia860_physical import build_physical_inventory_artifact

    artifact = build_physical_inventory_artifact(
        eia860_archive, state="TX", retrieved_at="2026-09-06T12:00:00Z"
    )
    units = [
        asset for asset in artifact["assets"] if asset["asset_kind"] == "generator_unit"
    ]
    assert units and all(asset["geometry_status"] == "unavailable" for asset in units)
    assert artifact["terminals"] == []
    assert artifact["connectivity_edges"] == []
    assert (
        len(
            [
                asset
                for asset in artifact["assets"]
                if asset["asset_kind"] == "storage_unit"
            ]
        )
        == 1
    )
    assert len(units) == 2


def test_checked_state_artifacts_validate_and_link_back_to_source_intake():
    pytest.importorskip("pipelines.physical_inventory")
    from pipelines.physical_inventory import artifact_sha256, validate_artifact

    root = Path(__file__).resolve().parents[2]
    for state, expected_count in (("tx", 4907), ("mn", 2405)):
        artifact_path = (
            root
            / "data/artifacts/physical_inventory"
            / state
            / "eia860-2025er-physical-inventory-1.0.0.json"
        )
        intake_path = (
            root
            / "data/sources/ingest"
            / f"eia860-2025er-{state}-source-intake-v1.json.gz"
        )
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        with gzip.open(intake_path, "rt", encoding="utf-8") as stream:
            intake = json.load(stream)
        source_records = {
            record["source_record_id"]
            for facility in intake["records"]
            for record in [
                facility,
                *facility["attributes"]["generator_units"],
                *facility["attributes"]["storage_units"],
            ]
        }
        assert len(artifact["assets"]) == expected_count
        assert artifact["content_sha256"] == artifact_sha256(artifact)
        assert validate_artifact(artifact) == artifact
        assert {
            asset["source_record_id"] for asset in artifact["assets"]
        } <= source_records
