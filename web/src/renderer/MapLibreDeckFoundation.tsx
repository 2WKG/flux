import { useCallback, useMemo, useState } from "react";
import { ScatterplotLayer } from "@deck.gl/layers";
import type { LayersList } from "@deck.gl/core";
import type { StyleSpecification } from "maplibre-gl";
import Map from "react-map-gl/maplibre";
import { OFFLINE_BASEMAP_STYLE } from "./basemap";
import { acceptedPoints, type SceneView } from "./scene-view";
import { DeckOverlay } from "./DeckOverlay";
import "maplibre-gl/dist/maplibre-gl.css";
import "./renderer.css";

/** Observed overlay health. `request_failed` is one of the six shared status tokens. */
type OverlayState = "initializing" | "initialized" | "request_failed";

export interface MapLibreDeckFoundationProps {
  /** The renderer's view of the adapter's output; see `scene-view.ts`. */
  readonly view: SceneView;
  /** Defaults to the offline, geometry-free style. A remote style is opt-in. */
  readonly basemapStyle?: string | StyleSpecification;
}

/**
 * MapLibre + deck.gl foundation. It renders only server-accepted point
 * positions. It has no synthetic-XY conversion, feature fallback, model fetch,
 * or asset placement, and its default basemap issues no network request.
 */
export function MapLibreDeckFoundation({ view, basemapStyle = OFFLINE_BASEMAP_STYLE }: MapLibreDeckFoundationProps) {
  const [basemapError, setBasemapError] = useState<string | null>(null);
  const [overlayState, setOverlayState] = useState<OverlayState>("initializing");
  const [overlayError, setOverlayError] = useState<string | null>(null);
  const markOverlayReady = useCallback(() => setOverlayState("initialized"), []);
  const markOverlayFailed = useCallback((message: string) => {
    setOverlayState("request_failed");
    setOverlayError(message);
  }, []);

  const drawable = useMemo(() => acceptedPoints(view), [view]);
  const layers = useMemo<LayersList>(() => {
    if (drawable.length === 0) return [];
    return [new ScatterplotLayer({
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
  }, [drawable]);

  const overlayText = overlayState === "initialized"
    ? `initialized with ${drawable.length} accepted feature layer${drawable.length === 1 ? "" : "s"}`
    : overlayState === "request_failed"
      ? `unavailable (request_failed): ${overlayError ?? "deck reported an error"}`
      : "initializing";

  return <section className="map-foundation" aria-label="Map and renderer status">
    <Map
      initialViewState={{ longitude: -94.2, latitude: 46.2, zoom: 5.6 }}
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
