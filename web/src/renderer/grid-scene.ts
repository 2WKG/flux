/**
 * Physical-inventory items to the renderer's own scene vocabulary.
 *
 * This is the one written translation between the spatial API's two-value
 * `availability` / three-value `geometry_status` axes and the six shared status
 * tokens (`src/labels.ts`), and it exists here — at a named seam — rather than
 * inside a component. It never invents a placement: geometry comes from
 * `display_geometry`, which the server produced in EPSG:4326, and an item whose
 * geometry is unavailable produces no point and no path at all.
 *
 * The display *words* for these tokens are `STATUS_COPY`'s and are not restated
 * anywhere in this directory.
 */

import { renderableFeatures, type RenderableFeature, type SpatialItem } from "../data/grid-inventory";
import { PLACEABLE_STATUS_LABELS, sceneViewFor, type SceneView, type StatusLabel } from "./scene-view";

/**
 * The status token an item's own geometry provenance asserts.
 *
 * `source` is geometry the source itself carries, which is what
 * `source_supported` means. `derived` is geometry the pipeline produced by a
 * disclosed transform from a source record, which is `source_screened`:
 * screened against the recorded source but not directly supported by it.
 * `unavailable` maps to itself. There is no fourth case, and no default.
 */
export function statusLabelForItem(item: SpatialItem): StatusLabel {
  if (item.availability === "unavailable" || item.geometry_status === "unavailable") return "unavailable";
  return item.geometry_status === "source" ? "source_supported" : "source_screened";
}

function firstPosition(coordinates: unknown): readonly [number, number] | null {
  if (!Array.isArray(coordinates)) return null;
  if (coordinates.length >= 2 && typeof coordinates[0] === "number" && typeof coordinates[1] === "number") {
    return Number.isFinite(coordinates[0]) && Number.isFinite(coordinates[1])
      ? [coordinates[0], coordinates[1]]
      : null;
  }
  for (const entry of coordinates) {
    const position = firstPosition(entry);
    if (position !== null) return position;
  }
  return null;
}

/** Every [lon, lat] pair inside a geometry, in order. */
export function positionsOf(coordinates: unknown): readonly (readonly [number, number])[] {
  if (!Array.isArray(coordinates)) return [];
  if (coordinates.length >= 2 && typeof coordinates[0] === "number" && typeof coordinates[1] === "number") {
    return Number.isFinite(coordinates[0]) && Number.isFinite(coordinates[1]) ? [[coordinates[0], coordinates[1]]] : [];
  }
  return coordinates.flatMap(positionsOf);
}

export type ScenePath = Readonly<{ id: string; path: readonly (readonly [number, number])[]; statusLabel: StatusLabel }>;

/** Point features become scene points; anything with two or more positions becomes a path. */
export function sceneFor(items: readonly SpatialItem[]): { view: SceneView; paths: readonly ScenePath[] } {
  const features: readonly RenderableFeature[] = renderableFeatures(items);
  const nodes = features.flatMap((feature) => {
    if (!feature.geometry.type.includes("Point")) return [];
    const position = firstPosition(feature.geometry.coordinates);
    return position === null ? [] : [{ id: feature.id, position, statusLabel: statusLabelForItem(feature.properties) }];
  });
  const paths = features.flatMap((feature) => {
    if (feature.geometry.type.includes("Point")) return [];
    const path = positionsOf(feature.geometry.coordinates);
    return path.length < 2 ? [] : [{ id: feature.id, path, statusLabel: statusLabelForItem(feature.properties) }];
  });
  if (nodes.length > 0) return { view: sceneViewFor({ nodes }), paths };
  if (paths.length === 0) return { view: sceneViewFor({ nodes: [] }), paths };
  // A line-only release has no points for `sceneViewFor` to read, so the same
  // rule is applied to the paths: the scene is only as accepted as its least
  // accepted member, and a non-placeable member is named, not dropped.
  const blocking = paths.find((entry) => !PLACEABLE_STATUS_LABELS.includes(entry.statusLabel));
  const status = blocking ? blocking.statusLabel : paths[0].statusLabel;
  const detail = blocking
    ? `Geometry labelled ${status} is not rendered as a geographic feature layer.`
    : `${paths.length} server-accepted line${paths.length === 1 ? "" : "s"} may be drawn; 3D asset placement remains unavailable until a verified asset artifact is supplied.`;
  return { view: { status, points: [], detail }, paths };
}

/** The bounds of every drawn position, or null when nothing is drawable. */
export function boundsOf(paths: readonly ScenePath[], view: SceneView): readonly [readonly [number, number], readonly [number, number]] | null {
  const positions = [...paths.flatMap((entry) => entry.path), ...view.points.map((point) => point.position)];
  if (positions.length === 0) return null;
  const longitudes = positions.map((position) => position[0]);
  const latitudes = positions.map((position) => position[1]);
  return [
    [Math.min(...longitudes), Math.min(...latitudes)],
    [Math.max(...longitudes), Math.max(...latitudes)],
  ];
}

/**
 * The paths the renderer may draw, under the same refusal `acceptedPoints`
 * applies to points: one path carrying a non-placeable label suppresses the
 * whole set rather than being drawn beside accepted ones.
 */
export function acceptedPaths(paths: readonly ScenePath[], view: SceneView): readonly ScenePath[] {
  if (paths.length === 0) return [];
  if (!PLACEABLE_STATUS_LABELS.includes(view.status) && view.points.length > 0) return [];
  return paths.every((entry) => PLACEABLE_STATUS_LABELS.includes(entry.statusLabel)) ? paths : [];
}
