/** Source-backed inventory geometry plus optional verified 3D asset layers. */
import { useCallback, useMemo, useState } from "react";
import type { LayersList } from "@deck.gl/core";
import type { SpatialItem } from "../data/grid-inventory";
import { FluxAssetLayer, type FluxAssetPlacementInput } from "./FluxAssetLayer";
import { positionsOf, type ScenePath } from "./grid-scene";
import { MapLibreDeckFoundation } from "./MapLibreDeckFoundation";
import { assetPackNotice, type AssetPackLoadState } from "./asset-pack";
import type { SceneView } from "./scene-view";

const ARCHETYPE_FOR_SOURCE_TYPE: Readonly<Record<string, string>> = {
  "line:AC; OVERHEAD": "transmission_line_segment",
  "line:AC; UNDERGROUND": "transmission_line_segment",
  "line:OVERHEAD": "transmission_line_segment",
  "line:transmission_or_subtransmission_line": "transmission_line_segment",
  "substation:substation": "substation_transformer_yard",
  "storage:storage_unit": "battery_storage",
};

/** Maps only explicit source class/kind and server-produced EPSG:4326 geometry. */
export function assetPlacementsForItems(items: readonly SpatialItem[]): readonly FluxAssetPlacementInput[] {
  return items.flatMap((item) => {
    if (item.availability !== "available" || item.display_geometry === null) return [];
    const archetypeId = ARCHETYPE_FOR_SOURCE_TYPE[`${item.asset_class}:${item.asset_kind}`];
    const position = positionsOf(item.display_geometry.coordinates)[0];
    if (!archetypeId || position === undefined) return [];
    return [{
      id: item.asset_id, archetypeId, position, label: item.asset_id,
      artifactId: item.provenance.source_record_id,
      status: item.geometry_status === "source" ? "source_supported" : "source_screened",
    }];
  });
}

export function GridMap({ view, paths, fitBounds, assetItems = [], onAssetSelect }: {
  readonly view: SceneView;
  readonly paths: readonly ScenePath[];
  readonly fitBounds: readonly [readonly [number, number], readonly [number, number]] | null;
  readonly assetItems?: readonly SpatialItem[];
  readonly onAssetSelect?: (item: SpatialItem) => void;
}) {
  const [assetLayers, setAssetLayers] = useState<LayersList>([]);
  // Do not guess a LOD from a fixture default. MapLibre reports the camera's
  // real zoom after bounds fitting and on every user move.
  const [zoom, setZoom] = useState<number | null>(null);
  const [assetState, setAssetState] = useState<{ readonly state: AssetPackLoadState; readonly detail: string } | null>(null);
  const placements = useMemo(() => assetPlacementsForItems(assetItems), [assetItems]);
  const selectAsset = useCallback((placement: { readonly id: string }) => {
    const item = assetItems.find((candidate) => candidate.asset_id === placement.id);
    if (item !== undefined) onAssetSelect?.(item);
  }, [assetItems, onAssetSelect]);
  const notice = assetState === null
    ? { heading: "3D asset renderer", detail: "Waiting for the map camera before selecting a model LOD.", action: null }
    : assetPackNotice(assetState.state, assetState.detail);
  return <>
    {zoom === null ? null : <FluxAssetLayer
      mode="physical_inventory"
      placements={placements}
      zoom={zoom}
      onLayersChange={setAssetLayers}
      onStateChange={(state, detail) => setAssetState({ state, detail })}
      onSelect={selectAsset}
    />}
    <MapLibreDeckFoundation
      view={view}
      paths={paths}
      fitBounds={fitBounds}
      additionalLayers={assetLayers}
      onZoomChange={setZoom}
    />
    <section className={`grid-map-note grid-asset-pack is-${assetState?.state ?? "loading"}`} role={assetState?.state === "install_required" ? "alert" : "status"} data-asset-pack-state={assetState?.state ?? "loading"}>
      <strong>{notice.heading}</strong>
      <span>{notice.detail}</span>
      {notice.action ? <span>{notice.action}</span> : null}
    </section>
  </>;
}
