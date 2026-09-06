/**
 * Navigable, synthetic Texas model scene.
 *
 * This component draws only `/demo/model` elements whose server response marks
 * them resolved. IDs remain MATPOWER/pandapower model identities: it makes no
 * claim that a point is a physical Texas facility, and generic columns carry
 * no measured capacity or fuel type.
 */
import { useMemo, useState, type ReactNode } from "react";
import type { LayersList } from "@deck.gl/core";
import { ColumnLayer, PathLayer, ScatterplotLayer, TextLayer } from "@deck.gl/layers";
import Map from "react-map-gl/maplibre";
import { OFFLINE_BASEMAP_STYLE } from "./basemap";
import { DeckOverlay } from "./DeckOverlay";

type Position = readonly [number, number];
export interface SyntheticModelElement {
  readonly element_id?: string;
  readonly resolved?: boolean;
  readonly role?: "line" | "impedance_branch" | "generator" | "load" | string;
  readonly geometry?: { readonly type?: string; readonly coordinates?: unknown };
}
interface PointElement { readonly id: string; readonly role: string; readonly position: Position; }
interface LineElement { readonly id: string; readonly role: string; readonly path: readonly Position[]; }

export interface SyntheticModelSceneProps {
  readonly elements: readonly SyntheticModelElement[];
  /** The selected and highlighted IDs must come from the canonical model scene. */
  readonly selectedElementId?: string;
  readonly highlightedElementIds?: readonly string[];
  readonly onSelectElement?: (elementId: string) => void;
  readonly fallback?: ReactNode;
}

const MAX_LINES = 3_200;
const MAX_POINTS = 1_600;
const isPoint = (value: unknown): value is Position => Array.isArray(value)
  && value.length >= 2 && typeof value[0] === "number" && Number.isFinite(value[0])
  && typeof value[1] === "number" && Number.isFinite(value[1]);

function resolvedGeometry(elements: readonly SyntheticModelElement[]) {
  const points: PointElement[] = [];
  const lines: LineElement[] = [];
  for (const element of elements) {
    if (!element.resolved || !element.element_id) continue;
    const geometry = element.geometry;
    if (geometry?.type === "Point" && isPoint(geometry.coordinates)) {
      points.push({ id: element.element_id, role: element.role ?? "untyped", position: geometry.coordinates });
    } else if (geometry?.type === "LineString" && Array.isArray(geometry.coordinates)) {
      const path = geometry.coordinates.filter(isPoint);
      if (path.length >= 2) lines.push({ id: element.element_id, role: element.role ?? "line", path });
    }
  }
  return { points, lines };
}

function boundsOf(points: readonly PointElement[], lines: readonly LineElement[]) {
  const coordinates = [...points.map((item) => item.position), ...lines.flatMap((item) => item.path)];
  if (coordinates.length === 0) return null;
  const lons = coordinates.map((item) => item[0]);
  const lats = coordinates.map((item) => item[1]);
  return [[Math.min(...lons), Math.min(...lats)], [Math.max(...lons), Math.max(...lats)]] as const;
}

function limited<T extends { readonly id: string }>(items: readonly T[], max: number, keep: ReadonlySet<string>) {
  const base = items.slice(0, max);
  const included = new Set(base.map((item) => item.id));
  return [...base, ...items.filter((item) => keep.has(item.id) && !included.has(item.id))];
}

/** Pure deck layer seam for the primary-model owner and renderer tests. */
export function syntheticModelLayers({
  points, lines, selectedElementId, highlightedElementIds = [], zoom, onSelectElement,
}: {
  readonly points: readonly PointElement[];
  readonly lines: readonly LineElement[];
  readonly selectedElementId?: string;
  readonly highlightedElementIds?: readonly string[];
  readonly zoom: number;
  readonly onSelectElement?: (id: string) => void;
}): LayersList {
  const emphasized = new Set([selectedElementId, ...highlightedElementIds].filter((id): id is string => Boolean(id)));
  // At overview zoom, retain the complete network strokes and only emphasized
  // nodes. Closer navigation admits deterministic, bounded generic columns.
  const visibleLines = limited(lines, MAX_LINES, emphasized);
  const visiblePoints = zoom < 5.75
    ? points.filter((item) => emphasized.has(item.id))
    : limited(points, MAX_POINTS, emphasized);
  const color = (id: string, normal: Uint8Array): Uint8Array => id === selectedElementId
    ? new Uint8Array([250, 204, 21, 255])
    : emphasized.has(id) ? new Uint8Array([249, 115, 22, 255]) : normal;
  const click = (info: { object?: { id: string } | null }) => { if (info.object) onSelectElement?.(info.object.id); };
  const layers: LayersList = [new PathLayer<LineElement>({
    id: "synthetic-model-lines", data: visibleLines, getPath: (item) => item.path as Position[],
    getColor: (item) => color(item.id, new Uint8Array([74, 222, 128, 170])), getWidth: (item) => emphasized.has(item.id) ? 5 : 2,
    widthUnits: "pixels", pickable: true, onClick: click,
  })];
  if (visiblePoints.length) layers.push(new ColumnLayer<PointElement>({
    id: "synthetic-model-generic-columns", data: visiblePoints, getPosition: (item) => item.position,
    getFillColor: (item) => color(item.id, new Uint8Array(item.role === "generator" ? [96, 165, 250, 220] : [148, 163, 184, 205])),
    getLineColor: (item) => color(item.id, new Uint8Array([15, 23, 42, 255])), radius: 5_500,
    getElevation: (item) => item.role === "generator" ? 110 : 55,
    elevationScale: 8, radiusUnits: "meters", extruded: true, diskResolution: 8,
    pickable: true, onClick: click,
  }));
  const selected = [...points, ...lines].find((item) => item.id === selectedElementId);
  if (selected) {
    const position = "position" in selected ? selected.position : selected.path[0];
    layers.push(new ScatterplotLayer({ id: "synthetic-model-selection", data: [{ id: selected.id, position }], getPosition: (item) => item.position, getRadius: 22, radiusUnits: "pixels", getFillColor: [250, 204, 21, 45], getLineColor: [250, 204, 21, 255], stroked: true, lineWidthUnits: "pixels", getLineWidth: 3 }));
    layers.push(new TextLayer({ id: "synthetic-model-selection-label", data: [{ id: selected.id, position }], getPosition: (item) => item.position, getText: (item) => item.id, getSize: 13, getColor: [255, 255, 255, 255], getPixelOffset: [18, -14], background: true, getBackgroundColor: [15, 23, 42, 235], backgroundPadding: [6, 3] }));
  }
  return layers;
}

/** A navigable model-only visual; its fallback is deliberately supplied by its owner. */
export function SyntheticModelScene({ elements, selectedElementId, highlightedElementIds, onSelectElement, fallback }: SyntheticModelSceneProps) {
  const { points, lines } = useMemo(() => resolvedGeometry(elements), [elements]);
  const [zoom, setZoom] = useState(5.4);
  const [mapError, setMapError] = useState<string | null>(null);
  const layers = useMemo(() => syntheticModelLayers({ points, lines, selectedElementId, highlightedElementIds, zoom, onSelectElement }), [points, lines, selectedElementId, highlightedElementIds, zoom, onSelectElement]);
  const bounds = useMemo(() => boundsOf(points, lines), [points, lines]);
  if (bounds === null || mapError) return <>{fallback ?? <p role="status">3D model view unavailable: {mapError ?? "no resolved model geometry"}.</p>}</>;
  const rendered = Math.min(lines.length, MAX_LINES) + (zoom < 5.75 ? 0 : Math.min(points.length, MAX_POINTS));
  return <section aria-label="Navigable synthetic Texas model" data-topology="synthetic (ACTIVSg2000)">
    <Map initialViewState={{ bounds: bounds as [[number, number], [number, number]], fitBoundsOptions: { padding: 32, maxZoom: 6.8 }, pitch: 48, bearing: -14 }} mapStyle={OFFLINE_BASEMAP_STYLE} onMove={(event) => setZoom(event.viewState.zoom)} onError={(event) => setMapError(event.error.message)} style={{ height: 440, width: "100%" }}>
      <DeckOverlay layers={layers} />
    </Map>
    <p role="status">Synthetic ACTIVSg2000 model · {rendered} of {points.length + lines.length} resolved elements at this LOD · generic columns are illustrative geometry, not measured capacity or fuel.</p>
  </section>;
}
