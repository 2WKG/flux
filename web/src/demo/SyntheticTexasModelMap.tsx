import type { ModelGeometryElement } from "./runtime";

type Point = readonly [number, number];

function point(value: unknown): Point | null {
  if (!Array.isArray(value) || value.length < 2 || typeof value[0] !== "number" || typeof value[1] !== "number") return null;
  return [value[0], value[1]];
}

function points(element: ModelGeometryElement): readonly Point[] {
  const geometry = element.geometry;
  if (geometry?.type === "Point") { const item = point(geometry.coordinates); return item ? [item] : []; }
  if (geometry?.type === "LineString" && Array.isArray(geometry.coordinates)) return geometry.coordinates.flatMap((item) => { const value = point(item); return value ? [value] : []; });
  const coords = element.coordinates as { lon?: unknown; lat?: unknown; from?: { lon?: unknown; lat?: unknown }; to?: { lon?: unknown; lat?: unknown } } | undefined;
  const direct = point([coords?.lon, coords?.lat]);
  if (direct) return [direct];
  return [point([coords?.from?.lon, coords?.from?.lat]), point([coords?.to?.lon, coords?.to?.lat])].filter((item): item is Point => item !== null);
}

/** Renders only exact synthetic coordinates supplied by `/demo/model`. */
export function SyntheticTexasModelMap({ elements, selectedElementId, onSelect }: { elements: readonly ModelGeometryElement[]; selectedElementId?: string; onSelect?: (id: string) => void }) {
  const drawable = elements.flatMap((element) => element.resolved && element.element_id ? [{ element, points: points(element) }] : []);
  const all = drawable.flatMap((entry) => entry.points);
  if (all.length === 0) return <p className="control-room__unavailable" role="status">Model visual unavailable: the server supplied no resolved synthetic coordinates.</p>;
  const minLon = Math.min(...all.map((item) => item[0])); const maxLon = Math.max(...all.map((item) => item[0]));
  const minLat = Math.min(...all.map((item) => item[1])); const maxLat = Math.max(...all.map((item) => item[1]));
  const x = (lon: number) => 20 + ((lon - minLon) / (maxLon - minLon || 1)) * 440;
  const y = (lat: number) => 220 - ((lat - minLat) / (maxLat - minLat || 1)) * 180;
  return <svg className="synthetic-model-map" viewBox="0 0 480 240" role="img" aria-label="Synthetic Texas model geometry using exact server-supplied canonical IDs">
    <rect x="0" y="0" width="480" height="240" rx="10" />
    {drawable.map(({ element, points: geometry }) => {
      const selected = element.element_id === selectedElementId;
      const first = geometry[0]; const last = geometry[geometry.length - 1];
      return <g key={element.element_id} className={selected ? "is-selected" : ""} onClick={() => onSelect?.(element.element_id!)}>
        {geometry.length > 1 ? <line x1={x(first[0])} y1={y(first[1])} x2={x(last[0])} y2={y(last[1])} /> : <circle cx={x(first[0])} cy={y(first[1])} r="7" />}
        <text x={x(first[0]) + 8} y={y(first[1]) - 8}>{element.element_id}</text>
      </g>;
    })}
  </svg>;
}
