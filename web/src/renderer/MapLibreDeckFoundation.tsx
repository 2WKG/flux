import { useCallback, useMemo, useState } from "react";
import { PathLayer, ScatterplotLayer } from "@deck.gl/layers";
import type { LayersList } from "@deck.gl/core";
import type { StyleSpecification } from "maplibre-gl";
import Map from "react-map-gl/maplibre";
import { OFFLINE_BASEMAP_STYLE } from "./basemap";
import { acceptedPoints, type SceneView } from "./scene-view";
import { acceptedPaths, type ScenePath } from "./grid-scene";
import { DeckOverlay } from "./DeckOverlay";
import "../styles.css";

/** Observed overlay health. `request_failed` is one of the six shared status tokens. */
type OverlayState = "initializing" | "initialized" | "request_failed";

export interface MapLibreDeckFoundationProps {
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

/**
 * MapLibre + deck.gl foundation. It renders only server-accepted point
 * positions. It has no synthetic-XY conversion, feature fallback, model fetch,
 * or asset placement, and its default basemap issues no network request.
 */
export function MapLibreDeckFoundation({ view, basemapStyle = OFFLINE_BASEMAP_STYLE, paths = [], fitBounds = null }: MapLibreDeckFoundationProps) {
  const [basemapError, setBasemapError] = useState<string | null>(null);
  const [overlayState, setOverlayState] = useState<OverlayState>("initializing");
  const [overlayError, setOverlayError] = useState<string | null>(null);
  const markOverlayReady = useCallback(() => setOverlayState("initialized"), []);
  const markOverlayFailed = useCallback((message: string) => {
    setOverlayState("request_failed");
    setOverlayError(message);
  }, []);

  const drawable = useMemo(() => acceptedPoints(view), [view]);
  const drawablePaths = useMemo(() => acceptedPaths(paths, view), [paths, view]);
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
    if (drawable.length === 0) return list;
    return [...list, new ScatterplotLayer({
      id: "accepted-scene-nodes",
      data: drawable,
      getPosition: point => point.position as [number, number],
      getRadius: 75,
      radiusUnits: "meters",
      getFillColor: [134, 187, 255, 210],
      pickable: true,
      // The adapter guarantees EPSG:4326; MapboxOverlay synchronizes MapView with MapLibre.
      coordinateSystem: "lnglat",
    })];
  }, [drawable, drawablePaths]);

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
      <span>3D model assets are unavailable until an accepted placement and verified immutable artifact are supplied.</span>
    </div>
  </section>;
}
