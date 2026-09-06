/**
 * Full synthetic Texas model scene. Geometry and IDs arrive only from
 * `/demo/model`; this layer is intentionally separate from physical inventory
 * placements and their 3D asset LOD.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import type { LayersList } from "@deck.gl/core";
import { PathLayer, ScatterplotLayer } from "@deck.gl/layers";
import Map, { NavigationControl } from "react-map-gl/maplibre";
import { OFFLINE_BASEMAP_STYLE } from "./basemap";
import { DeckOverlay } from "./DeckOverlay";
import { loadFluxGridPlacements, type AssetPlacementBounds } from "../data/flux-grid-assets";
import { createFluxAssetLayers, FluxAssetCache, loadFluxGroups, lodForZoom, type FluxAssetManifest, type FluxPlacement, type LoadedFluxGroup } from "../map/layers/fluxGridAssets";

type Position = readonly [number, number];
export type TexasModelElement = Readonly<{
  element_id?: string;
  resolved?: boolean;
  role?: string;
  geometry?: Readonly<{ type?: string; coordinates?: unknown }>;
}>;
export type TexasModelPayload = Readonly<{
  status: "available" | "partial" | "unavailable";
  reason?: string;
  data?: Readonly<{
    topology?: Readonly<{ label?: string; synthetic?: boolean; solver?: string }>;
    counts?: Readonly<{ buses?: number; branches?: number; generators?: number; loads?: number }>;
    elements?: readonly TexasModelElement[];
  }>;
}>;
type Point = Readonly<{ id: string; position: Position; role: string }>;
type Line = Readonly<{ id: string; path: readonly Position[] }>;
type AssetOverlay = Readonly<{ placements: readonly FluxPlacement[]; groups: readonly LoadedFluxGroup[] }>;
type AssetSource = Readonly<{ manifest: FluxAssetManifest; placements: readonly FluxPlacement[] }>;

function position(value: unknown): Position | null {
  return Array.isArray(value) && typeof value[0] === "number" && Number.isFinite(value[0]) &&
    typeof value[1] === "number" && Number.isFinite(value[1]) ? [value[0], value[1]] : null;
}

function geometry(elements: readonly TexasModelElement[]): { points: readonly Point[]; lines: readonly Line[] } {
  const points: Point[] = [], lines: Line[] = [];
  for (const element of elements) {
    if (!element.resolved || !element.element_id) continue;
    if (element.geometry?.type === "Point") {
      const item = position(element.geometry.coordinates);
      if (item) points.push({ id: element.element_id, position: item, role: element.role ?? "unknown" });
    } else if (element.geometry?.type === "LineString" && Array.isArray(element.geometry.coordinates)) {
      const path = element.geometry.coordinates.flatMap((item) => {
        const value = position(item);
        return value ? [value] : [];
      });
      if (path.length >= 2) lines.push({ id: element.element_id, path });
    }
  }
  return { points, lines };
}

function boundsOf(points: readonly Point[], lines: readonly Line[]) {
  const all = [...points.map((point) => point.position), ...lines.flatMap((line) => line.path)];
  if (!all.length) return null;
  return [[Math.min(...all.map((item) => item[0])), Math.min(...all.map((item) => item[1]))],
    [Math.max(...all.map((item) => item[0])), Math.max(...all.map((item) => item[1]))]] as const;
}

export function isTexasModelPayload(value: unknown): value is TexasModelPayload {
  if (!value || typeof value !== "object") return false;
  const status = (value as Record<string, unknown>).status;
  return status === "available" || status === "partial" || status === "unavailable";
}

/** All resolved branches remain in the PathLayer at every zoom. */
export function TexasTopologyMap({ payload }: { readonly payload: TexasModelPayload }) {
  const { points, lines } = useMemo(() => geometry(payload.data?.elements ?? []), [payload]);
  const buses = useMemo(() => points.filter((point) => point.role === "bus"), [points]);
  const generators = useMemo(() => points.filter((point) => point.role === "generator"), [points]);
  const loads = useMemo(() => points.filter((point) => point.role === "load"), [points]);
  const declared = payload.data?.counts;
  const count = (value: number | undefined, fallback: number) =>
    typeof value === "number" && Number.isInteger(value) && value >= 0 ? value : fallback;
  const bounds = useMemo(() => boundsOf(points, lines), [points, lines]);
  const [error, setError] = useState<string | null>(null);
  const [zoom, setZoom] = useState(5.4);
  const [assetSource, setAssetSource] = useState<AssetSource | null>(null);
  const [assets, setAssets] = useState<AssetOverlay | null>(null);
  const cache = useRef<FluxAssetCache | null>(null);
  const lod = lodForZoom(zoom);
  useEffect(() => {
    cache.current = new FluxAssetCache("/assets/flux-grid/");
    return () => { cache.current?.dispose(); cache.current = null; };
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    if (bounds === null) return () => controller.abort();
    const manifest = fetch("/assets/flux-grid/manifest.json", { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error(`3D asset manifest request failed (${response.status}).`);
        const value: unknown = await response.json();
        if (!value || typeof value !== "object" || (value as { contract_id?: unknown }).contract_id !== "flux:3d-asset-archetypes:v1") throw new Error("3D asset manifest is not Flux v1.");
        return value as FluxAssetManifest;
      });
    Promise.all([manifest, loadFluxGridPlacements(bounds as AssetPlacementBounds, controller.signal)])
      .then(([manifest, placements]) => { if (!controller.signal.aborted) setAssetSource({ manifest, placements }); })
      .catch(() => { if (!controller.signal.aborted) setAssetSource(null); });
    return () => controller.abort();
  }, [bounds]);
  // LOD changes reuse the retained manifest, placements and FluxAssetCache bytes.
  useEffect(() => {
    const controller = new AbortController();
    const activeCache = cache.current;
    if (assetSource === null || activeCache === null) return () => controller.abort();
    loadFluxGroups(activeCache, assetSource.manifest, assetSource.placements, { zoom, mode: "accepted" })
      .then((groups) => { if (!controller.signal.aborted) setAssets({ placements: assetSource.placements, groups }); })
      .catch(() => { if (!controller.signal.aborted) setAssets(null); });
    return () => controller.abort();
  }, [assetSource, lod]);
  const layers = useMemo<LayersList>(() => [
    new PathLayer<Line>({ id: "texas-model-branches", data: lines, getPath: (line) => line.path as Position[],
      getColor: [74, 222, 128, 170], getWidth: 1.5, widthUnits: "pixels", pickable: true }),
    new ScatterplotLayer<Point>({ id: "texas-model-buses", data: buses, getPosition: (point) => point.position,
      getRadius: 3, radiusUnits: "pixels", getFillColor: [148, 163, 184, 210], pickable: true }),
    ...(assets ? createFluxAssetLayers({ zoom, mode: "accepted" }, assets) : []),
    new ScatterplotLayer<Point>({ id: "texas-model-generators", data: generators, getPosition: (point) => point.position,
      getRadius: 4, radiusUnits: "pixels", getFillColor: [251, 191, 36, 220], pickable: true }),
    new ScatterplotLayer<Point>({ id: "texas-model-loads", data: loads, getPosition: (point) => point.position,
      getRadius: 3, radiusUnits: "pixels", getFillColor: [96, 165, 250, 210], pickable: true }),
  ], [assets, buses, generators, lines, loads, zoom]);
  if (payload.status === "unavailable" || bounds === null || error) return <p role="status">Texas model unavailable: {error ?? payload.reason ?? "the API supplied no resolved model geometry"}.</p>;
  return <section className="texas-topology-map" aria-label="Full synthetic Texas topology" data-topology={payload.data?.topology?.label ?? "synthetic topology"} data-visual-lod={zoom >= 17 ? "lod0" : zoom >= 15 ? "lod1" : zoom >= 12 ? "lod2" : "symbol"} data-map-zoom={zoom.toFixed(2)}>
    <Map initialViewState={{ bounds: bounds as [[number, number], [number, number]], fitBoundsOptions: { padding: 32, maxZoom: 6.8 }, pitch: 40, bearing: -12 }} mapStyle={OFFLINE_BASEMAP_STYLE} onLoad={(event) => setZoom(event.target.getZoom())} onMoveEnd={(event) => setZoom(event.viewState.zoom)} onZoomEnd={(event) => setZoom(event.target.getZoom())} onError={(event) => setError(event.error.message)}>
      <NavigationControl position="top-right" showCompass />
      <DeckOverlay layers={layers} />
    </Map>
    <p role="status">{payload.data?.topology?.label ?? "Synthetic topology"} · {count(declared?.buses, buses.length)} resolved buses · {count(declared?.branches, lines.length)} resolved branches · {count(declared?.generators, generators.length)} generators · {count(declared?.loads, loads.length)} loads. Topology remains complete at every zoom; {assets ? `${assets.placements.length} observed physical visual placement${assets.placements.length === 1 ? "" : "s"} use a separate LOD layer.` : "observed physical model placements are loading or unavailable."}</p>
  </section>;
}
