/**
 * The map, drawn once, by the merged #213 foundation.
 *
 * This module exists so MapLibre and deck.gl stay behind a dynamic import: the
 * shell paints its scenario explorer without them, and the panel above can be
 * rendered and asserted in a plain Node test without a WebGL context. It adds
 * no rendering of its own — that is the point of the finding it answers.
 */

import { MapLibreDeckFoundation } from "./MapLibreDeckFoundation";
import type { ScenePath } from "./grid-scene";
import type { SceneView } from "./scene-view";

export function GridMap({ view, paths, fitBounds }: {
  readonly view: SceneView;
  readonly paths: readonly ScenePath[];
  readonly fitBounds: readonly [readonly [number, number], readonly [number, number]] | null;
}) {
  return <MapLibreDeckFoundation view={view} paths={paths} fitBounds={fitBounds} />;
}
