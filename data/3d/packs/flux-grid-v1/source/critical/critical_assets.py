"""Shared pipeline entry point for the four critical-facility archetypes.

Imports are lazy and scene-free. The pipeline owns materials, final mesh
construction, glTF axis conversion, exports, and preview rendering.
"""

from importlib import import_module

MODULES = {
    "military_base": "critical.military",
    "hospital": "critical.hospital",
    "water_treatment_plant": "critical.water",
    "school_emergency_services": "critical.school",
}


def build(asset_id, lod):
    if asset_id not in MODULES:
        raise ValueError(f"Unsupported critical-facility archetype: {asset_id}")
    if lod not in (0, 1, 2):
        raise ValueError("lod must be 0, 1, or 2")
    return import_module(MODULES[asset_id]).build(asset_id, lod)
