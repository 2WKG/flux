import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { PathLayer, ScatterplotLayer } from "@deck.gl/layers";
import type { LayersList } from "@deck.gl/core";
import type { StyleSpecification } from "maplibre-gl";
import Map from "react-map-gl/maplibre";
import { OFFLINE_BASEMAP_STYLE } from "./basemap";
import { acceptedPoints, type SceneView } from "./scene-view";
import { acceptedPaths, type ScenePath } from "./grid-scene";
import { DeckOverlay } from "./DeckOverlay";
import { loadFluxGridPlacements, type AssetPlacementBounds } from "../data/flux-grid-assets";
import {
  createFluxAssetLayers, FluxAssetCache, loadFluxGroups, type FluxAssetManifest, type FluxPlacement, type LoadedFluxGroup,
} from "../map/layers/fluxGridAssets";
import type { GridState } from "../data/grid-client";
import "../styles.css";

/** Observed overlay health. `request_failed` is one of the six shared status tokens. */
type OverlayState = "initializing" | "initialized" | "request_failed";

export interface MapLibreDeckFoundationProps {
  /** The published 3D placement route currently serves Texas only. */
  readonly state?: GridState;
  /** The renderer's view of the adapter's output; see `scene-view.ts`. */
  readonly view: SceneView;
  /** Defaults to the offline, geometry-free style. A remote style is opt-in. */
  readonly basemapStyle?: string | StyleSpecification;
  /**
   * Server-produced line geometry, under the same placement refusal the points
   * are under (`acceptedPaths`). Added so the physical-inventory map renders
   * through this foundation instead of a second map beside it.
   */
  readonly paths?: readonly ScenePath[];
  /** Fit the camera to these bounds once, when they change. */
  readonly fitBounds?: readonly [readonly [number, number], readonly [number, number]] | null;
}

type AssetState =
  | { readonly kind: "loading" }
  | { readonly kind: "ready"; readonly manifest: FluxAssetManifest; readonly placements: readonly FluxPlacement[]; readonly groups: readonly LoadedFluxGroup[] }
  | { readonly kind: "unavailable"; readonly detail: string };

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** The runtime accepts only the published v1 manifest before requesting a GLB. */
function assetManifest(value: unknown): FluxAssetManifest | null {
  if (!record(value) || value.schema_version !== 1 || value.contract_id !== "flux:3d-asset-archetypes:v1" ||
    !record(value.transform) || value.transform.unit !== "meter" || value.transform.up !== "Y" ||
    value.transform.forward !== "-Z" || value.transform.pivot !== "ground_center" || !Array.isArray(value.assets) || value.assets.length === 0) return null;
  const validFile = (file: unknown) => record(file) && typeof file.path === "string" && typeof file.sha256 === "string" &&
    typeof file.bytes === "number" && Number.isFinite(file.bytes);
  const validAsset = (asset: unknown) => record(asset) && typeof asset.archetype_id === "string" && typeof asset.semantic_name === "string" &&
    typeof asset.category === "string" && record(asset.footprint_m) && typeof asset.footprint_m.width === "number" &&
    typeof asset.footprint_m.length === "number" && record(asset.lods) && ["lod0", "lod1", "lod2"].every((lod) => validFile(asset.lods[lod]) && typeof asset.lods[lod].triangles === "number");
  return value.assets.every(validAsset) ? value as FluxAssetManifest : null;
}

/**
 * MapLibre + deck.gl foundation. It renders only server-accepted point
 * positions. It has no synthetic-XY conversion or feature fallback. For Texas,
 * it separately reads the published asset manifest and source-authenticated
 * viewport placements; its default basemap issues no network request.
 */
export function MapLibreDeckFoundation({ state = "tx", view, basemapStyle = OFFLINE_BASEMAP_STYLE, paths = [], fitBounds = null }: MapLibreDeckFoundationProps) {
  const [basemapError, setBasemapError] = useState<string | null>(null);
  const [overlayState, setOverlayState] = useState<OverlayState>("initializing");
  const [overlayError, setOverlayError] = useState<string | null>(null);
  const [zoom, setZoom] = useState(5.6);
  const [placementBounds, setPlacementBounds] = useState<AssetPlacementBounds | null>(null);
  const [manifest, setManifest] = useState<FluxAssetManifest | null>(null);
  const [assetState, setAssetState] = useState<AssetState>({ kind: "loading" });
  const cache = useRef<FluxAssetCache | null>(null);
  const markOverlayReady = useCallback(() => setOverlayState("initialized"), []);
  const markOverlayFailed = useCallback((message: string) => {
    setOverlayState("request_failed");
    setOverlayError(message);
  }, []);

  const drawable = useMemo(() => acceptedPoints(view), [view]);
  const drawablePaths = useMemo(() => acceptedPaths(paths, view), [paths, view]);
  useEffect(() => {
    const controller = new AbortController();
    setManifest(null);
    setAssetState(state === "tx" ? { kind: "loading" } : { kind: "unavailable", detail: "Published 3D placements are currently available for Texas only." });
    if (state !== "tx") return () => controller.abort();
    fetch("/assets/flux-grid/manifest.json", { signal: controller.signal, headers: { Accept: "application/json" } })
      .then(async (response) => {
        if (!response.ok) throw new Error(`3D asset manifest request failed (${response.status}).`);
        const parsed = assetManifest(await response.json());
        if (parsed === null) throw new Error("3D asset manifest does not satisfy the Flux v1 contract.");
        setManifest(parsed);
      })
      .catch((error: unknown) => { if (!controller.signal.aborted) setAssetState({ kind: "unavailable", detail: error instanceof Error ? error.message : "3D asset manifest request failed." }); });
    return () => controller.abort();
  }, [state]);
  useEffect(() => {
    cache.current = new FluxAssetCache("/assets/flux-grid/");
    return () => { cache.current?.dispose(); cache.current = null; };
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    if (state !== "tx" || manifest === null || placementBounds === null || cache.current === null) return () => controller.abort();
    setAssetState({ kind: "loading" });
    loadFluxGridPlacements(placementBounds, controller.signal)
      .then(async (placements) => {
        const activeCache = cache.current;
        if (activeCache === null) return;
        const groups = await loadFluxGroups(activeCache, manifest, placements, { zoom, mode: "accepted" });
        if (!controller.signal.aborted) setAssetState({ kind: "ready", manifest, placements, groups });
      })
      .catch((error: unknown) => { if (!controller.signal.aborted) setAssetState({ kind: "unavailable", detail: error instanceof Error ? error.message : "3D asset request failed." }); });
    return () => controller.abort();
  }, [manifest, placementBounds, state, zoom]);
  const layers = useMemo<LayersList>(() => {
    const list: LayersList = [];
    if (drawablePaths.length > 0) {
      list.push(new PathLayer({
        id: "accepted-scene-paths",
        data: drawablePaths,
        getPath: (entry: ScenePath) => entry.path as [number, number][],
        getColor: [110, 214, 255, 220],
        getWidth: 3,
        widthUnits: "pixels",
        pickable: true,
      }));
    }
    if (drawable.length > 0) list.push(new ScatterplotLayer({
      id: "accepted-scene-nodes",
      data: drawable,
      getPosition: point => point.position as [number, number],
      getRadius: 75,
      radiusUnits: "meters",
      getFillColor: [134, 187, 255, 210],
      pickable: true,
      // The adapter guarantees EPSG:4326; MapboxOverlay synchronizes MapView with MapLibre.
      coordinateSystem: "lnglat",
    }));
    if (assetState.kind === "ready") list.push(...createFluxAssetLayers(
      { zoom, mode: "accepted" }, { placements: assetState.placements, groups: assetState.groups },
    ));
    return list;
  }, [assetState, drawable, drawablePaths, zoom]);

  const overlayText = overlayState === "initialized"
    ? `initialized with ${drawable.length + drawablePaths.length} accepted feature${drawable.length + drawablePaths.length === 1 ? "" : "s"}`
    : overlayState === "request_failed"
      ? `unavailable (request_failed): ${overlayError ?? "deck reported an error"}`
      : "initializing";

  return <section className="map-foundation" aria-label="Map and renderer status">
    <Map
      initialViewState={fitBounds
        ? { bounds: fitBounds as [[number, number], [number, number]], fitBoundsOptions: { padding: 48, maxZoom: 11 } }
        : { longitude: -94.2, latitude: 46.2, zoom: 5.6 }}
      mapStyle={basemapStyle}
      onError={(event) => setBasemapError(event.error.message)}
      onLoad={(event) => { setZoom(event.target.getZoom()); setPlacementBounds(event.target.getBounds().toArray() as AssetPlacementBounds); }}
      onMoveEnd={(event) => { setZoom(event.target.getZoom()); setPlacementBounds(event.target.getBounds().toArray() as AssetPlacementBounds); }}
    >
      <DeckOverlay layers={layers} onInitialized={markOverlayReady} onFailed={markOverlayFailed} />
    </Map>
    <div className="map-foundation-notice" role="status">
      <strong>Map context</strong>
      <span>Scene state: {view.status}</span>
      <span>Offline geometry-free basemap; no tiles, glyphs, sprites, or geography are fetched. No accepted feature layer is inferred from the basemap.</span>
      <span>Deck overlay: {overlayText}.</span>
      {basemapError && <span>Basemap unavailable: {basemapError}</span>}
      <span>Scene availability: {view.detail}</span>
      <span>3D assets: {assetState.kind === "ready"
        ? `${assetState.placements.length} source-authenticated placement${assetState.placements.length === 1 ? "" : "s"}; ${assetState.groups.length} visible model group${assetState.groups.length === 1 ? "" : "s"} at the current LOD.`
        : assetState.kind === "unavailable" ? `unavailable: ${assetState.detail}` : "loading the published manifest and current viewport placements."}</span>
    </div>
  </section>;
}
