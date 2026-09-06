"""Read a published physical-inventory release for grounded map questions."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from copilot.api import UnavailableError
from copilot.tools.schemas import ArtifactRef


@dataclass(frozen=True)
class InventoryEvidence:
    """A bounded summary of the exact release behind the physical map."""

    status: Literal["available", "unavailable"]
    data: dict[str, object]
    provenance: tuple[ArtifactRef, ...] = ()
    limitations: tuple[str, ...] = ()
    reason: str | None = None


class PhysicalInventoryReader:
    """Read only a verified release; never infer a topology from it."""

    def __init__(self, root: Path, *, version: str = "1.1.0") -> None:
        self._root = root
        self._version = version

    async def read(
        self, region: str, selected_physical_asset_id: str | None = None
    ) -> InventoryEvidence:
        return await asyncio.to_thread(self._read, region, selected_physical_asset_id)

    def _read(
        self, region: str, selected_physical_asset_id: str | None = None
    ) -> InventoryEvidence:
        state = {"texas": "tx", "minnesota": "mn"}.get(region)
        if state is None:
            return InventoryEvidence(
                status="unavailable",
                data={},
                reason="Select a supported inventory region.",
            )
        try:
            from copilot.routes.physical_layers import _verified_release

            release = _verified_release(self._root, state, self._version)
        except UnavailableError:
            return InventoryEvidence(
                status="unavailable",
                data={},
                reason="The selected physical-inventory release is unavailable.",
            )
        assets = release.get("assets")
        sources = release.get("sources")
        if not isinstance(assets, list) or not isinstance(sources, list):
            return InventoryEvidence(
                status="unavailable",
                data={},
                reason="The selected physical-inventory release is invalid.",
            )
        classes = sorted(
            {
                str(asset["asset_class"])
                for asset in assets
                if isinstance(asset, dict) and isinstance(asset.get("asset_class"), str)
            }
        )
        source_rows = [
            {
                "source_id": item.get("source_id"),
                "authority": item.get("authority"),
                "source_ref": item.get("source_ref"),
                "source_version": item.get("source_version"),
            }
            for item in sources
            if isinstance(item, dict)
            and all(
                isinstance(item.get(key), str) and item[key]
                for key in ("source_id", "source_ref", "source_version")
            )
        ]
        if not source_rows:
            return InventoryEvidence(
                status="unavailable",
                data={},
                reason="The selected physical-inventory release has no source provenance.",
            )
        source_by_id = {
            str(item["source_id"]): item
            for item in source_rows
            if isinstance(item.get("source_id"), str)
        }
        selected_asset: dict[str, object] | None = None
        if selected_physical_asset_id is not None:
            asset = next(
                (
                    item
                    for item in assets
                    if isinstance(item, dict)
                    and item.get("asset_id") == selected_physical_asset_id
                ),
                None,
            )
            if asset is None:
                return InventoryEvidence(
                    status="unavailable",
                    data={},
                    reason="The selected physical asset is not in this inventory release.",
                )
            source_id = asset.get("source_id")
            source = source_by_id.get(str(source_id))
            if source is None:
                return InventoryEvidence(
                    status="unavailable",
                    data={},
                    reason="The selected physical asset has no source provenance.",
                )
            selected_asset = {
                "asset_id": asset["asset_id"],
                "asset_class": asset.get("asset_class"),
                "asset_kind": asset.get("asset_kind"),
                "source_id": source_id,
                "source_record_id": asset.get("source_record_id"),
                "source": source,
            }
        artifact_id = str(release.get("artifact_id", f"physical-inventory:{state}"))
        provenance = tuple(
            ArtifactRef(
                artifact_id=artifact_id,
                artifact_version=self._version,
                source_kind="observed",
                source_ref=str(row["source_ref"]),
            )
            for row in source_rows[:50]
        )
        return InventoryEvidence(
            status="available",
            data={
                "region": region,
                "artifact_id": artifact_id,
                "artifact_version": release.get("artifact_version"),
                "release_sha256": release.get("content_sha256"),
                "inventory_mode": release.get("inventory_mode"),
                "electrical_model_mode": release.get("electrical_model_mode"),
                "asset_count": len(assets),
                "asset_classes": classes,
                "source_records": source_rows,
                "selected_asset": selected_asset,
            },
            provenance=provenance,
            limitations=(
                "This is a physical inventory release, not a topology or cascade model.",
                "No physical asset is selected, so this answer does not identify a facility record.",
            ),
        )
