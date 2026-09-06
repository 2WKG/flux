from __future__ import annotations

import gzip
import hashlib
import io
import json
import re
import zipfile
from pathlib import Path

import openpyxl
import pytest

from pipelines.eia860_physical import (
    GENERATOR_MEMBER,
    PLANT_MEMBER,
    STORAGE_MEMBER,
    EIA860PhysicalError,
    build_eia860_physical_inventory,
)
from pipelines.physical_inventory import artifact_sha256, validate_artifact

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "eia860"
SLICE_PATH = FIXTURE_DIR / "eia8602025ER-slice.zip"
PROVENANCE_PATH = FIXTURE_DIR / "PROVENANCE.json"
_UNIT_SHEETS = ("Operable", "Proposed", "Retired and Canceled")
_MEMBER_SHEETS = {
    PLANT_MEMBER: ("Plant",),
    GENERATOR_MEMBER: _UNIT_SHEETS,
    STORAGE_MEMBER: _UNIT_SHEETS,
}


@pytest.fixture()
def eia860_slice() -> Path:
    """The committed slice of the real EIA-860 2025ER archive.

    Nothing here patches ``pd.read_excel``: the parser opens the published zip
    member names, reads the published sheet names at the published header
    offset, and sees the published column set.
    """
    return SLICE_PATH


def _archive_without_column(target: Path, member: str, sheet: str, column: str) -> Path:
    """Copy the slice with one published column deleted from one sheet."""
    with zipfile.ZipFile(SLICE_PATH) as source:
        payloads = {name: source.read(name) for name in _MEMBER_SHEETS}
    book = openpyxl.load_workbook(io.BytesIO(payloads[member]))
    worksheet = book[sheet]
    header_row = next(
        row for index, row in enumerate(worksheet.iter_rows()) if index == 2
    )
    index = next(
        cell.column for cell in header_row if str(cell.value).strip() == column
    )
    worksheet.delete_cols(index)
    buffer = io.BytesIO()
    book.save(buffer)
    payloads[member] = buffer.getvalue()
    with zipfile.ZipFile(target, "w") as destination:
        for name, payload in payloads.items():
            destination.writestr(name, payload)
    return target


def test_committed_slice_matches_its_provenance_receipt():
    provenance = json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))
    recorded = provenance["files"][SLICE_PATH.name]
    payload = SLICE_PATH.read_bytes()
    assert hashlib.sha256(payload).hexdigest() == recorded["sha256"]
    assert len(payload) == recorded["bytes"]
    with zipfile.ZipFile(SLICE_PATH) as archive:
        assert sorted(archive.namelist()) == sorted(_MEMBER_SHEETS)


def test_eia860_observations_keep_plant_point_and_unit_attachments_separate(
    eia860_slice: Path,
):
    inventory = build_eia860_physical_inventory(
        eia860_slice, states=["TX", "MN"], retrieved_at="2026-09-06T07:43:27Z"
    )
    assert [row["asset_id"] for row in inventory["records"]] == [
        "eia:plant:2038",
        "eia:plant:62908",
        "eia:plant:69414",
        "eia:plant:7732",
        "eia:plant:8063",
    ]
    decordova = next(
        row for row in inventory["records"] if row["asset_id"] == "eia:plant:8063"
    )
    # Published Schedule 2 values for plant 8063, read out of the slice.
    assert decordova["geometry"] == {
        "type": "Point",
        "coordinates": [-97.700556, 32.403056],
    }
    assert decordova["coordinate_status"] == "source"
    assert decordova["attributes"]["plant_name"] == "DeCordova Steam Electric Station"
    assert decordova["attributes"]["state"] == "TX"
    assert decordova["attributes"]["county_name"] == "Hood"
    assert decordova["attributes"]["balancing_authority_code"] == "ERCO"
    assert decordova["attributes"]["plant_grid_voltage_kv"] == 345.0
    assert decordova["attributes"]["unit_coordinate_status"] == "unavailable"
    assert decordova["attributes"]["electrical_connectivity_status"] == "unavailable"
    generators = {
        unit["generator_id"]: unit
        for unit in decordova["attributes"]["generator_units"]
    }
    assert generators["CT1"]["status_sheet"] == "Operable"
    assert generators["CT1"]["status_code"] == "OP"
    assert generators["CT1"]["nameplate_capacity_mw"] == 89.4
    assert generators["CT1"]["energy_source_1"] == "NG"
    assert generators["CT1"]["prime_mover"] == "GT"
    assert generators["1"]["status_sheet"] == "Retired and Canceled"
    assert generators["1"]["nameplate_capacity_mw"] == 799.2
    storage = decordova["attributes"]["storage_units"]
    assert [unit["generator_id"] for unit in storage] == ["BESS"]
    assert storage[0]["nameplate_energy_capacity_mwh"] == 263.0
    assert storage[0]["storage_technology_1"] == "LIB"

    # Plant 7732 is the real Schedule 2 row whose coordinate cells are blank.
    turbine = next(
        row for row in inventory["records"] if row["asset_id"] == "eia:plant:7732"
    )
    assert turbine["geometry"] is None
    assert turbine["coordinate_status"] == "unavailable"

    assert all(
        row["asset_kind"] == "generation_facility" for row in inventory["records"]
    )
    coverage = {row["class_id"]: row for row in inventory["coverage"]}
    assert coverage["generation_facility"]["denominator"] == 5
    assert coverage["generation_facility"]["known_count"] == 4
    assert coverage["generation_facility"]["unknown_count"] == 1
    assert coverage["generation_unit_attachment"]["denominator"] == 16
    assert coverage["storage_unit_attachment"]["denominator"] == 4
    assert coverage["unit_native_coordinate"]["unavailable_count"] == 20
    assert coverage["electrical_connectivity"]["denominator"] is None
    assert inventory["diagnostics"]["facilities_with_schedule3_attachments"] == 5
    assert (
        inventory["source"]["content_sha256"]
        == hashlib.sha256(eia860_slice.read_bytes()).hexdigest()
    )


def test_eia860_reads_every_schedule3_status_sheet(eia860_slice: Path):
    inventory = build_eia860_physical_inventory(
        eia860_slice, states=["TX", "MN"], retrieved_at="2026-09-06T07:43:27Z"
    )
    generator_sheets: dict[str, list[str]] = {}
    storage_sheets: dict[str, list[str]] = {}
    for facility in inventory["records"]:
        for unit in facility["attributes"]["generator_units"]:
            generator_sheets.setdefault(unit["status_sheet"], []).append(
                unit["source_record_id"]
            )
        for unit in facility["attributes"]["storage_units"]:
            storage_sheets.setdefault(unit["status_sheet"], []).append(
                unit["source_record_id"]
            )
    # All three published Schedule 3.1 sheets contribute rows in this slice, so
    # dropping one from the read loses source records.
    assert sorted(generator_sheets) == sorted(_UNIT_SHEETS)
    assert len(generator_sheets["Operable"]) == 9
    assert len(generator_sheets["Proposed"]) == 3
    assert len(generator_sheets["Retired and Canceled"]) == 4
    assert sorted(storage_sheets) == ["Operable", "Proposed"]
    assert (
        "eia860:2025er:generation_unit:8063:CT5:retired_and_canceled"
        in generator_sheets["Retired and Canceled"]
    )


def test_eia860_requires_a_utc_offset_on_retrieved_at(eia860_slice: Path):
    with pytest.raises(EIA860PhysicalError, match="UTC offset"):
        build_eia860_physical_inventory(
            eia860_slice, states=["TX"], retrieved_at="2026-09-06T07:43:27"
        )


@pytest.mark.parametrize(
    ("member", "sheet", "column"),
    [
        (PLANT_MEMBER, "Plant", "Longitude"),
        (GENERATOR_MEMBER, "Operable", "Nameplate Capacity (MW)"),
        (STORAGE_MEMBER, "Operable", "Generator ID"),
    ],
)
def test_eia860_refuses_a_workbook_missing_a_published_column(
    tmp_path: Path, member: str, sheet: str, column: str
):
    damaged = _archive_without_column(tmp_path / "damaged.zip", member, sheet, column)
    with pytest.raises(
        EIA860PhysicalError, match=re.escape(f"missing columns: [{column!r}]")
    ):
        build_eia860_physical_inventory(
            damaged, states=["TX", "MN"], retrieved_at="2026-09-06T07:43:27Z"
        )


def test_eia860_refuses_an_archive_without_the_published_member(tmp_path: Path):
    archive_path = tmp_path / "incomplete.zip"
    with (
        zipfile.ZipFile(SLICE_PATH) as source,
        zipfile.ZipFile(archive_path, "w") as destination,
    ):
        for name in _MEMBER_SHEETS:
            if name != PLANT_MEMBER:
                destination.writestr(name, source.read(name))
    with pytest.raises(EIA860PhysicalError, match=re.escape(PLANT_MEMBER)):
        build_eia860_physical_inventory(
            archive_path, states=["TX"], retrieved_at="2026-09-06T07:43:27Z"
        )


def test_contract_adapter_preserves_units_without_promoting_their_plant_point(
    eia860_slice: Path,
):
    from pipelines.eia860_physical import build_physical_inventory_artifact

    artifact = build_physical_inventory_artifact(
        eia860_slice, state="TX", retrieved_at="2026-09-06T07:43:27Z"
    )
    by_kind: dict[str, list[dict]] = {}
    for asset in artifact["assets"]:
        by_kind.setdefault(asset["asset_kind"], []).append(asset)
    assert all(
        asset["geometry_status"] == "unavailable" for asset in by_kind["generator_unit"]
    )
    assert artifact["terminals"] == []
    assert artifact["connectivity_edges"] == []
    # TX slice: 3 plants, 12 Schedule 3.1 rows and 2 Schedule 3.4 rows. The two
    # storage rows are also listed in Schedule 3.1, so one physical unit yields
    # exactly one asset and the generator side drops to 10.
    assert len(by_kind["plant"]) == 3
    assert len(by_kind["generator_unit"]) == 10
    assert len(by_kind["storage_unit"]) == 2
    assert len(artifact["assets"]) == 15
    storage_ids = {asset["asset_id"] for asset in by_kind["storage_unit"]}
    assert storage_ids == {
        "eia860:2025er:storage_unit:69414:BSBES",
        "eia860:2025er:storage_unit:8063:BESS",
    }
    generator_units = {
        asset["source_record_id"].split(":")[4] for asset in by_kind["generator_unit"]
    }
    assert "BESS" not in generator_units
    assert "BSBES" not in generator_units
    assert artifact["content_sha256"] == artifact_sha256(artifact)
    assert validate_artifact(artifact) == artifact


def test_checked_state_artifacts_validate_and_link_back_to_source_intake():
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
