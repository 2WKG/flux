"""Validation-only Minnesota SMR placement boundary.

This route deliberately delegates eligibility to ``bind_asset``.  It does not
score, simulate, recommend, or make a permitting assertion.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

import duckdb
from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from copilot.api import InvalidInputError, UnavailableError
from pipelines.minnesota_asset_binding import (
    AssetBindingError,
    bind_asset,
    load_catalog,
    load_inventory,
)

router = APIRouter(prefix="/minnesota/smr", tags=["minnesota-smr"])
ROOT = Path(__file__).resolve().parents[2]


class SmrPlacementRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    scene_id: str = Field(min_length=1, max_length=256)
    source_artifact_id: str = Field(min_length=1, max_length=256)
    longitude: float
    latitude: float
    crs: Literal["EPSG:4326"]


def validate_placement(path: Path, proposal: SmrPlacementRequest) -> dict:
    """Return only server-derived placement status; opens DuckDB read-only."""
    model = {
        "archetype_id": "nuclear_smr_module",
        "contract_id": "flux:3d-asset-archetypes:v1",
        "glb_uri": "/assets/flux-grid/nuclear_smr_module/nuclear_smr_module.glb",
        "footprint_m": {"length": 120, "width": 100},
        "connectors": ["HV_OUT"],
        "lod_triangles": {"lod0": 32000, "lod1": 12000, "lod2": 3400},
    }
    placement = {
        "scene_id": proposal.scene_id,
        "source_artifact_id": proposal.source_artifact_id,
        "coordinates": {
            "longitude": proposal.longitude,
            "latitude": proposal.latitude,
            "crs": proposal.crs,
        },
    }
    try:
        con = duckdb.connect(str(path), read_only=True)
    except duckdb.Error as exc:
        raise UnavailableError(
            "Minnesota placement evidence is unavailable.",
            details={
                "artifact": "mn_artifact_manifests",
                "reason": "database_unavailable",
            },
        ) from exc
    try:
        binding = bind_asset(
            con,
            load_catalog(ROOT / "data/3d/asset-archetypes-v1.json"),
            load_inventory(
                ROOT / "data/sources/minnesota-accepted-artifact-inventory.json"
            ),
            model,
            placement,
        )
    except AssetBindingError as exc:
        raise InvalidInputError(
            "Minnesota placement context is invalid.",
            details={"reason": "invalid_placement"},
        ) from exc
    except duckdb.Error as exc:
        raise UnavailableError(
            "Minnesota placement evidence is unavailable.",
            details={
                "artifact": "mn_artifact_manifests",
                "reason": "evidence_unavailable",
            },
        ) from exc
    finally:
        con.close()
    if binding["render_mode"] == "placed":
        return {
            "status": "valid",
            "placement": binding,
            "limitations": [
                "Validation only; no siting score, simulation, permitability, or "
                "construction claim is made."
            ],
        }
    return {
        "status": "unknown",
        "placement": binding,
        "limitations": [
            "No accepted placement evidence is available; the result is an "
            "illustrative catalogue preview."
        ],
    }


@router.post("/validate")
def validate_smr(proposal: SmrPlacementRequest, request: Request) -> dict:
    return validate_placement(request.app.state.settings.duckdb_path, proposal)
