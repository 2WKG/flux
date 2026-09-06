"""Source-faithful EIA-860 facility observations for physical-map inventory.

EIA Schedule 2 publishes a *plant* coordinate.  Schedules 3.1 and 3.4 publish
generator and storage-unit attributes attached to that plant, but no separate
unit coordinates or electrical terminals.  This module deliberately keeps that
distinction in its output: a point is an EIA plant point and unit records are
attachments, never colocated physical geometry or inferred connectivity.
"""

from __future__ import annotations

import argparse
import io
import json
import math
import zipfile
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from pipelines.common import sha256_file

EIA860_2025ER_URL = "https://www.eia.gov/electricity/data/eia860/xls/eia8602025ER.zip"
EIA860_2025ER_VERSION = "2025 early release"
PLANT_MEMBER = "2___Plant_Y2025_Early_Release.xlsx"
GENERATOR_MEMBER = "3_1_Generator_Y2025_Early_Release.xlsx"
STORAGE_MEMBER = "3_4_Energy_Storage_Y2025_Early_Release.xlsx"
_HEADER_ROW = 2


class EIA860PhysicalError(ValueError):
    """The supplied EIA-860 release cannot support the requested observation."""


def _utc_timestamp(value: str) -> str:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise EIA860PhysicalError("retrieved_at must include a UTC offset")
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _required(frame: pd.DataFrame, names: Iterable[str], label: str) -> None:
    missing = set(names) - set(frame.columns)
    if missing:
        raise EIA860PhysicalError(f"{label} is missing columns: {sorted(missing)!r}")


def _read_member(
    archive: zipfile.ZipFile, member: str, sheet_name: str
) -> pd.DataFrame:
    try:
        payload = archive.read(member)
    except KeyError as exc:
        raise EIA860PhysicalError(f"EIA-860 archive lacks {member!r}") from exc
    return pd.read_excel(io.BytesIO(payload), sheet_name=sheet_name, header=_HEADER_ROW)


def _clean_text(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


def _number(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _plant_key(value: object) -> str:
    number = _number(value)
    if number is not None and number.is_integer():
        return str(int(number))
    text = _clean_text(value)
    if text is None:
        raise EIA860PhysicalError("EIA-860 row has no Plant Code")
    return text


def _unit_rows(
    archive: zipfile.ZipFile, member: str, *, asset_kind: str, states: set[str]
) -> dict[str, list[dict[str, Any]]]:
    rows: dict[str, list[dict[str, Any]]] = {}
    for sheet in ("Operable", "Proposed", "Retired and Canceled"):
        frame = _read_member(archive, member, sheet)
        _required(
            frame,
            (
                "Plant Code",
                "State",
                "Generator ID",
                "Status",
                "Nameplate Capacity (MW)",
            ),
            f"{member}:{sheet}",
        )
        selected = frame[frame["State"].astype(str).str.strip().isin(states)]
        for row in selected.to_dict("records"):
            plant_id = _plant_key(row["Plant Code"])
            generator_id = _clean_text(row["Generator ID"])
            if generator_id is None:
                # A source row without its Schedule 3 identity cannot be safely
                # attached or deduplicated, so it remains an explicit coverage gap.
                continue
            values = {
                "asset_kind": asset_kind,
                "source_record_id": (
                    f"eia860:2025er:{asset_kind}:{plant_id}:{generator_id}:{sheet.lower().replace(' ', '_')}"
                ),
                "generator_id": generator_id,
                "status_code": _clean_text(row["Status"]),
                "status_sheet": sheet,
                "nameplate_capacity_mw": _number(row["Nameplate Capacity (MW)"]),
                "summer_capacity_mw": _number(row.get("Summer Capacity (MW)")),
                "winter_capacity_mw": _number(row.get("Winter Capacity (MW)")),
                "technology": _clean_text(row.get("Technology")),
                "prime_mover": _clean_text(row.get("Prime Mover")),
            }
            if asset_kind == "generation_unit":
                values["energy_source_1"] = _clean_text(row.get("Energy Source 1"))
            else:
                values.update(
                    {
                        "nameplate_energy_capacity_mwh": _number(
                            row.get("Nameplate Energy Capacity (MWh)")
                        ),
                        "maximum_charge_rate_mw": _number(
                            row.get("Maximum Charge Rate (MW)")
                        ),
                        "maximum_discharge_rate_mw": _number(
                            row.get("Maximum Discharge Rate (MW)")
                        ),
                        "storage_technology_1": _clean_text(
                            row.get("Storage Technology 1")
                        ),
                    }
                )
            rows.setdefault(plant_id, []).append(values)
    return rows


def build_eia860_physical_inventory(
    archive_path: str | Path, *, states: Iterable[str], retrieved_at: str
) -> dict[str, Any]:
    """Return a versioned physical-observation artifact for selected states.

    The artifact is intentionally JSON-only until the shared physical inventory
    writer is available.  It is a normalized source artifact, not a topology
    artifact or a claim that every facility in a state is represented.
    """
    selected_states = {state.upper() for state in states}
    if not selected_states:
        raise EIA860PhysicalError("at least one USPS state code is required")
    retrieved = _utc_timestamp(retrieved_at)
    archive_path = Path(archive_path)
    with zipfile.ZipFile(archive_path) as archive:
        plants = _read_member(archive, PLANT_MEMBER, "Plant")
        _required(
            plants,
            ("Plant Code", "Plant Name", "State", "Latitude", "Longitude"),
            PLANT_MEMBER,
        )
        generation = _unit_rows(
            archive,
            GENERATOR_MEMBER,
            asset_kind="generation_unit",
            states=selected_states,
        )
        storage = _unit_rows(
            archive, STORAGE_MEMBER, asset_kind="storage_unit", states=selected_states
        )

    selected_plants = plants[
        plants["State"].astype(str).str.strip().isin(selected_states)
    ]
    records: list[dict[str, Any]] = []
    coordinates_unavailable = 0
    facility_with_unit_rows = 0
    for row in selected_plants.to_dict("records"):
        plant_id = _plant_key(row["Plant Code"])
        lon, lat = _number(row["Longitude"]), _number(row["Latitude"])
        attachments = [*generation.get(plant_id, []), *storage.get(plant_id, [])]
        if attachments:
            facility_with_unit_rows += 1
        if lon is None or lat is None or not (-180 <= lon <= 180 and -90 <= lat <= 90):
            coordinates_unavailable += 1
            geometry = None
            coordinate_status = "unavailable"
        else:
            geometry = {"type": "Point", "coordinates": [lon, lat]}
            coordinate_status = "source"
        records.append(
            {
                "class_id": "generation_facility",
                "asset_id": f"eia:plant:{plant_id}",
                "source_record_id": f"eia860:2025er:plant:{plant_id}",
                "asset_kind": "generation_facility",
                "geometry": geometry,
                "coordinate_status": coordinate_status,
                "coordinate_precision_m": None,
                "accuracy_basis": (
                    "EIA-860 Schedule 2 plant latitude/longitude as published; "
                    "the workbook does not publish a positional-accuracy value."
                    if geometry is not None
                    else "EIA-860 Schedule 2 has no valid plant coordinate for this source record."
                ),
                "attributes": {
                    "plant_id_eia": plant_id,
                    "plant_name": _clean_text(row["Plant Name"]),
                    "state": _clean_text(row["State"]),
                    "county_name": _clean_text(row.get("County")),
                    "balancing_authority_code": _clean_text(
                        row.get("Balancing Authority Code")
                    ),
                    "plant_grid_voltage_kv": _number(row.get("Grid Voltage (kV)")),
                    "unit_coordinate_status": "unavailable",
                    "unit_coordinate_reason": "EIA-860 Schedule 3 unit rows are attached to a plant but do not publish unit coordinates.",
                    "electrical_connectivity_status": "unavailable",
                    "electrical_connectivity_reason": "EIA-860 does not publish terminals or network edges in these schedules.",
                    "generator_units": sorted(
                        generation.get(plant_id, []),
                        key=lambda item: item["source_record_id"],
                    ),
                    "storage_units": sorted(
                        storage.get(plant_id, []),
                        key=lambda item: item["source_record_id"],
                    ),
                },
            }
        )
    records.sort(key=lambda item: item["asset_id"])
    all_generation_units = [unit for units in generation.values() for unit in units]
    all_storage_units = [unit for units in storage.values() for unit in units]
    return {
        "artifact_version": "eia860-2025er-physical-observed-v1",
        "geography_id": "us-"
        + "-".join(sorted(state.lower() for state in selected_states)),
        "inventory_mode": "physical_observed",
        "source": {
            "authority": "U.S. Energy Information Administration",
            "uri": EIA860_2025ER_URL,
            "version": EIA860_2025ER_VERSION,
            "retrieved_at": retrieved,
            "license_or_terms": "Public EIA data; see EIA terms of use.",
            "content_sha256": sha256_file(archive_path),
        },
        "limitations": [
            "The 2025 Early Release states that it is not fully edited and is inappropriate for aggregation; final complete data follows later in 2026.",
            "A Schedule 2 plant point does not locate individual generation or storage units.",
            "No electrical attachment, terminal, edge, state of charge, or facility polygon is inferred from EIA-860.",
        ],
        "coverage": [
            {
                "class_id": "generation_facility",
                "scope": sorted(selected_states),
                "denominator": len(selected_plants),
                "known_count": len(selected_plants) - coordinates_unavailable,
                "unknown_count": coordinates_unavailable,
                "unavailable_count": 0,
                "status": "source_observed",
                "reason": "EIA-860 Schedule 2 state-filtered plant rows; denominator is source coverage, not a statewide completeness claim.",
            },
            {
                "class_id": "generation_unit_attachment",
                "scope": sorted(selected_states),
                "denominator": len(all_generation_units),
                "known_count": len(all_generation_units),
                "unknown_count": 0,
                "unavailable_count": 0,
                "status": "source_observed",
                "reason": "Schedule 3.1 unit attributes attached to EIA plants; no unit geometry or connectivity is represented.",
            },
            {
                "class_id": "storage_unit_attachment",
                "scope": sorted(selected_states),
                "denominator": len(all_storage_units),
                "known_count": len(all_storage_units),
                "unknown_count": 0,
                "unavailable_count": 0,
                "status": "source_observed",
                "reason": "Schedule 3.4 unit attributes attached to EIA plants; storage duration and state of charge are not inferred.",
            },
            {
                "class_id": "unit_native_coordinate",
                "scope": sorted(selected_states),
                "denominator": len(all_generation_units) + len(all_storage_units),
                "known_count": 0,
                "unknown_count": 0,
                "unavailable_count": len(all_generation_units) + len(all_storage_units),
                "status": "source_unavailable",
                "reason": "EIA-860 Schedule 3 does not provide native unit coordinates.",
            },
            {
                "class_id": "electrical_connectivity",
                "scope": sorted(selected_states),
                "denominator": None,
                "known_count": 0,
                "unknown_count": 0,
                "unavailable_count": None,
                "status": "source_unavailable",
                "reason": "EIA-860 does not establish plant or unit terminals/edges; statewide denominator is not available from this source.",
            },
        ],
        "records": records,
        "diagnostics": {
            "facilities_with_schedule3_attachments": facility_with_unit_rows
        },
    }


def build_physical_inventory_artifact(
    archive_path: str | Path,
    *,
    state: str,
    retrieved_at: str,
    artifact_version: str = "1.0.0",
) -> dict[str, Any]:
    """Build the exact 2WKG-441 artifact for one EIA state scope.

    ``eia860_unit_attachments`` remains a separate source-intake payload above
    because the shared physical artifact intentionally has no free-form
    attributes column.  Each Schedule 3 row is nevertheless represented as an
    asset with unavailable geometry, which preserves the source identity while
    preventing a plant point from being presented as a unit point.

    The import is deliberately local: this lane is a dependent PR while 2WKG-441
    publishes the shared contract module.
    """
    try:
        from pipelines.physical_inventory import (  # type: ignore[import-not-found]
            CONTRACT_VERSION,
            artifact_sha256,
            validate_artifact,
        )
    except ModuleNotFoundError as exc:  # pragma: no cover - dependency handoff
        raise EIA860PhysicalError(
            "2WKG-441 physical inventory contract is required before publishing EIA observations"
        ) from exc
    state = state.upper()
    intake = build_eia860_physical_inventory(
        archive_path, states=[state], retrieved_at=retrieved_at
    )
    source = intake["source"]
    assets: list[dict[str, Any]] = []
    generator_units = 0
    storage_units = 0
    missing_plant_geometry = 0
    for facility in intake["records"]:
        geometry = facility["geometry"]
        if geometry is None:
            missing_plant_geometry += 1
        assets.append(
            {
                "asset_id": facility["asset_id"],
                "asset_class": "generation",
                "asset_kind": "plant",
                "source_id": "eia860_2025er",
                "source_record_id": facility["source_record_id"],
                "geometry": geometry,
                "geometry_crs": "EPSG:4326" if geometry is not None else None,
                # EIA reports latitude/longitude but no positional accuracy in metres.
                "geometry_precision_m": None,
                "geometry_accuracy_basis": facility["accuracy_basis"]
                if geometry is not None
                else None,
                "geometry_derivation_method": None,
                "geometry_status": facility["coordinate_status"],
            }
        )
        storage_ids = {
            unit["generator_id"] for unit in facility["attributes"]["storage_units"]
        }
        for unit in facility["attributes"]["generator_units"]:
            # Schedule 3.1 also lists the units detailed in Schedule 3.4.
            # One physical unit gets one asset, classified as storage here.
            if unit["generator_id"] in storage_ids:
                continue
            generator_units += 1
            assets.append(
                {
                    "asset_id": unit["source_record_id"],
                    "asset_class": "generation",
                    "asset_kind": "generator_unit",
                    "source_id": "eia860_2025er",
                    "source_record_id": unit["source_record_id"],
                    "geometry": None,
                    "geometry_crs": None,
                    "geometry_precision_m": None,
                    "geometry_accuracy_basis": None,
                    "geometry_derivation_method": None,
                    "geometry_status": "unavailable",
                }
            )
        for unit in facility["attributes"]["storage_units"]:
            storage_units += 1
            assets.append(
                {
                    "asset_id": (
                        "eia860:2025er:storage_unit:"
                        f"{facility['attributes']['plant_id_eia']}:{unit['generator_id']}"
                    ),
                    "asset_class": "storage",
                    "asset_kind": "storage_unit",
                    "source_id": "eia860_2025er",
                    "source_record_id": unit["source_record_id"],
                    "geometry": None,
                    "geometry_crs": None,
                    "geometry_precision_m": None,
                    "geometry_accuracy_basis": None,
                    "geometry_derivation_method": None,
                    "geometry_status": "unavailable",
                }
            )
    facility_count = len(intake["records"])
    artifact = {
        "artifact_id": f"{state.lower()}:physical-inventory:{artifact_version}",
        "contract_version": CONTRACT_VERSION,
        "geography_id": state.lower(),
        "artifact_version": artifact_version,
        "inventory_mode": "physical_observed",
        "electrical_model_mode": "none",
        "created_at": intake["source"]["retrieved_at"],
        "content_sha256": "0" * 64,
        "sources": [
            {
                "source_id": "eia860_2025er",
                "authority": source["authority"],
                "source_ref": source["uri"],
                "source_version": source["version"],
                "retrieved_at": source["retrieved_at"],
                "license_or_terms": source["license_or_terms"],
                "content_sha256": source["content_sha256"],
            }
        ],
        "assets": sorted(assets, key=lambda row: row["asset_id"]),
        "terminals": [],
        "connectivity_edges": [],
        "coverage": [
            {
                "asset_class": "generation",
                "scope_id": state.lower(),
                "status": "partial",
                "observed_count": facility_count + generator_units,
                "denominator_count": facility_count + generator_units,
                "unknown_count": 0,
                "unavailable_count": missing_plant_geometry + generator_units,
                "denominator_basis": "State-filtered EIA-860 2025 Early Release Schedule 2 and Schedule 3.1 rows.",
                "source_scope": "EIA-860 2025 Early Release reporting scope; excludes records pending validation and does not establish statewide completeness.",
                "reason": "EIA-860 2025 Early Release Schedule 2 plants and Schedule 3.1 generator rows excluding units represented once as Schedule 3.4 storage; EIA warns the early release excludes pending-validation records and is not a statewide completeness claim. Generator-unit coordinates are not published.",
            },
            {
                "asset_class": "storage",
                "scope_id": state.lower(),
                "status": "partial",
                "observed_count": storage_units,
                "denominator_count": storage_units,
                "unknown_count": 0,
                "unavailable_count": storage_units,
                "denominator_basis": "State-filtered EIA-860 2025 Early Release Schedule 3.4 rows.",
                "source_scope": "EIA-860 2025 Early Release reporting scope; excludes records pending validation and does not establish statewide completeness.",
                "reason": "EIA-860 2025 Early Release Schedule 3.4 storage rows; plant association does not supply storage-unit geometry, duration, state of charge, or electrical connectivity.",
            },
        ],
    }
    artifact["content_sha256"] = artifact_sha256(artifact)
    return validate_artifact(artifact)


def write_eia860_physical_inventory(
    inventory: dict[str, Any], output: str | Path
) -> Path:
    """Write canonical JSON for handoff to the shared physical-inventory writer."""
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(inventory, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    return target


def publish_physical_inventory_artifact(
    con: Any,
    archive_path: str | Path,
    *,
    state: str,
    retrieved_at: str,
    artifact_version: str = "1.0.0",
) -> str:
    """Write one immutable EIA physical-observation artifact through 2WKG-441."""
    try:
        from pipelines.physical_inventory import (
            write_artifact,  # type: ignore[import-not-found]
        )
    except ModuleNotFoundError as exc:  # pragma: no cover - dependency handoff
        raise EIA860PhysicalError(
            "2WKG-441 physical inventory contract is required before publishing EIA observations"
        ) from exc
    artifact = build_physical_inventory_artifact(
        archive_path,
        state=state,
        retrieved_at=retrieved_at,
        artifact_version=artifact_version,
    )
    return write_artifact(con, artifact)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument(
        "--states", required=True, help="comma-separated USPS state codes, e.g. TX,MN"
    )
    parser.add_argument(
        "--retrieved-at", required=True, help="ISO-8601 timestamp with UTC offset"
    )
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    inventory = build_eia860_physical_inventory(
        args.archive,
        states=[state.strip() for state in args.states.split(",") if state.strip()],
        retrieved_at=args.retrieved_at,
    )
    write_eia860_physical_inventory(inventory, args.output)
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI shim
    raise SystemExit(main())
