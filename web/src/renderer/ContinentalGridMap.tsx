/** Self-hosted CONUS context with source-backed TX/MN physical inventory. */
import { useEffect, useMemo, useState } from "react";
import type { LayersList } from "@deck.gl/core";
import { GeoJsonLayer, PathLayer, ScatterplotLayer, TextLayer } from "@deck.gl/layers";
import Map from "react-map-gl/maplibre";
import { loadGridLayer, GRID_LAYERS, type GridState } from "../data/grid-client";
import type { SpatialItem } from "../data/grid-inventory";
import { OFFLINE_BASEMAP_STYLE } from "./basemap";
import { DeckOverlay } from "./DeckOverlay";

export type ContinentalRegion = "texas" | "minnesota";
export interface ContinentalGridMapProps {
  readonly selectedRegion: ContinentalRegion;
  readonly onRegionSelect: (region: ContinentalRegion) => void;
  readonly onAssetSelect?: (asset: SpatialItem) => void;
  readonly className?: string;
}
type Position = readonly [number, number];
const states: Record<ContinentalRegion, { code: string; state: GridState; color: number[] }> = {
  texas: { code: "TX", state: "tx", color: [34, 211, 238, 220] },
  minnesota: { code: "MN", state: "mn", color: [167, 139, 250, 220] },
};
const point = (v: unknown): v is Position => Array.isArray(v) && typeof v[0] === "number" && typeof v[1] === "number";
const firstPoint = (v: unknown): Position | null => point(v) ? v : Array.isArray(v) ? v.map(firstPoint).find((x): x is Position => x !== null) ?? null : null;
const line = (v: unknown): Position[] => Array.isArray(v) ? v.filter(point) : [];

export function ContinentalGridMap({ selectedRegion, onRegionSelect, onAssetSelect, className = "" }: ContinentalGridMapProps) {
  const [boundaries, setBoundaries] = useState<any>(null);
  const [assets, setAssets] = useState<SpatialItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    void fetch("/assets/boundaries/conus-states-2024-5m.geojson", { signal: controller.signal }).then((r) => r.ok ? r.json() : Promise.reject(new Error(`boundary request ${r.status}`))).then(setBoundaries).catch((e) => { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : String(e)); });
    void Promise.all(Object.entries(GRID_LAYERS).flatMap(([state, layers]) => layers.map((layer) => loadGridLayer({ state: state as GridState, layer, maxPages: 2, signal: controller.signal })))).then((outcomes) => {
      if (!controller.signal.aborted) setAssets(outcomes.flatMap((outcome) => outcome.kind === "loaded" ? outcome.pages.flatMap((page) => page.items) : []));
    });
    return () => controller.abort();
  }, []);
  const layers = useMemo<LayersList>(() => {
    const selectedCode = states[selectedRegion].code;
    const sourceLines = assets.filter((item) => item.availability === "available" && item.display_geometry?.type === "LineString").map((item) => ({ item, path: line(item.display_geometry?.coordinates) })).filter((item) => item.path.length > 1);
    const sourcePoints = assets.filter((item) => item.availability === "available" && item.display_geometry?.type !== "LineString").map((item) => ({ item, position: firstPoint(item.display_geometry?.coordinates) })).filter((item): item is { item: SpatialItem; position: Position } => item.position !== null);
    const click = (info: { object?: { item: SpatialItem } | null }) => { if (info.object) onAssetSelect?.(info.object.item); };
    return [new GeoJsonLayer({ id: "conus-census-states", data: boundaries ?? { type: "FeatureCollection", features: [] }, stroked: true, filled: true, getFillColor: ((feature: any) => feature.properties?.state_usps === selectedCode ? [30, 64, 91, 210] : feature.properties?.state_usps === "TX" || feature.properties?.state_usps === "MN" ? [20, 44, 65, 180] : [7, 18, 33, 100]) as any, getLineColor: ((feature: any) => feature.properties?.state_usps === "TX" ? states.texas.color : feature.properties?.state_usps === "MN" ? states.minnesota.color : [55, 75, 95, 80]) as any, getLineWidth: (feature: any) => feature.properties?.state_usps === "TX" || feature.properties?.state_usps === "MN" ? 3 : 1, lineWidthUnits: "pixels", pickable: true, onClick: (info: any) => { const code = info.object?.properties?.state_usps; if (code === "TX") onRegionSelect("texas"); if (code === "MN") onRegionSelect("minnesota"); } }), new PathLayer({ id: "conus-source-lines", data: sourceLines, getPath: (x) => x.path, getColor: ((x: any) => x.item.provenance.source_id.includes("mn") ? states.minnesota.color : states.texas.color) as any, getWidth: 1.5, widthUnits: "pixels", pickable: true, onClick: click }), new ScatterplotLayer({ id: "conus-source-assets", data: sourcePoints, getPosition: (x) => x.position, getRadius: 4, radiusUnits: "pixels", getFillColor: ((x: any) => x.item.provenance.source_id.includes("mn") ? states.minnesota.color : states.texas.color) as any, pickable: true, onClick: click }), new TextLayer({ id: "conus-focus-labels", data: [{ label: "TEXAS · source inventory", position: [-99, 31] }, { label: "MINNESOTA · source inventory", position: [-94, 46.5] }], getText: (x) => x.label, getPosition: (x) => x.position, getSize: 12, getColor: [230, 245, 255, 255], getTextAnchor: "middle", background: true, getBackgroundColor: [4, 14, 25, 220], backgroundPadding: [5, 3] })];
  }, [assets, boundaries, onAssetSelect, onRegionSelect, selectedRegion]);
  if (error) return <section className={className} aria-label="Continental grid map"><p role="status">National map unavailable: {error}</p><button onClick={() => onRegionSelect("texas")}>Texas source inventory</button><button onClick={() => onRegionSelect("minnesota")}>Minnesota source inventory</button></section>;
  return <section className={className} aria-label="Continental grid map" data-map-scope="CONUS source inventory"><Map initialViewState={{ bounds: [[-125, 24], [-66, 50]], fitBoundsOptions: { padding: 24, maxZoom: 4.4 }, pitch: 35, bearing: 0 }} mapStyle={OFFLINE_BASEMAP_STYLE} style={{ width: "100%", height: "100%", minHeight: 460 }}><DeckOverlay layers={layers} /></Map><p role="status">CONUS context: Census TIGER/Line 2024 boundaries; Texas and Minnesota highlights show server-provided physical-inventory geometry in EPSG:4326. No physical connectivity is inferred.</p></section>;
}
