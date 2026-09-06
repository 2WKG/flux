import { useCallback, useMemo, useState } from "react";
import { ScatterplotLayer } from "@deck.gl/layers";
import type { LayersList } from "@deck.gl/core";
import Map from "react-map-gl/maplibre";
import type { SceneAdaptation } from "../scene/minnesota-adapter";
import { DeckOverlay } from "./DeckOverlay";
import "maplibre-gl/dist/maplibre-gl.css";
import "./renderer.css";

export const OPEN_FREE_MAP_DARK = "https://tiles.openfreemap.org/styles/dark";

export interface MapLibreDeckFoundationProps {
  /** Output of the authoritative adapter. The renderer does not parse source payloads. */
  readonly adaptation: SceneAdaptation;
  readonly basemapStyle?: string;
}

function reasonFor(adaptation: SceneAdaptation): string {
  if (adaptation.kind === "rejected") return adaptation.detail;
  if (adaptation.kind === "aggregate_zones") return "Accepted aggregate coverage has no renderable geometry.";
  if (adaptation.nodes.some((node) => node.truthLabel !== "source_backed")) {
    return "Synthetic or unlabeled topology is not rendered as a geographic feature layer.";
  }
  return "Accepted point placements are available; 3D asset placement remains unavailable until a verified asset artifact is supplied.";
}

/**
 * MapLibre + deck.gl foundation. It renders only authoritative accepted point positions.
 * It has no synthetic-XY conversion, feature fallback, model fetch, or asset placement.
 */
export function MapLibreDeckFoundation({ adaptation, basemapStyle = OPEN_FREE_MAP_DARK }: MapLibreDeckFoundationProps) {
  const [basemapError, setBasemapError] = useState<string | null>(null);
  const [overlayReady, setOverlayReady] = useState(false);
  const markOverlayReady = useCallback(() => setOverlayReady(true), []);
  const layers = useMemo<LayersList>(() => {
    if (adaptation.kind !== "topology_scene" || adaptation.nodes.some((node) => node.truthLabel !== "source_backed")) return [];
    return [new ScatterplotLayer({
      id: "accepted-scene-nodes",
      data: adaptation.nodes,
      getPosition: node => node.position,
      getRadius: 75,
      radiusUnits: "meters",
      getFillColor: [134, 187, 255, 210],
      pickable: true,
      // The adapter guarantees EPSG:4326; MapboxOverlay synchronizes MapView with MapLibre.
      coordinateSystem: "lnglat",
    })];
  }, [adaptation]);

  return <section className="map-foundation" aria-label="Map and renderer status">
    <Map
      initialViewState={{ longitude: -94.2, latitude: 46.2, zoom: 5.6 }}
      mapStyle={basemapStyle}
      onError={(event) => setBasemapError(event.error.message)}
    >
      <DeckOverlay layers={layers} onInitialized={markOverlayReady} />
    </Map>
    <div className="map-foundation-notice" role="status">
      <strong>Map context</strong>
      <span>OpenFreeMap basemap; attribution remains enabled. No accepted feature layer is inferred from the basemap.</span>
      <span>Deck overlay: {overlayReady ? "initialized with zero accepted feature layers" : "initializing"}.</span>
      {basemapError && <span>Basemap unavailable: {basemapError}</span>}
      <span>Scene availability: {reasonFor(adaptation)}</span>
      <span>3D model assets are unavailable until an accepted placement and verified immutable artifact are supplied.</span>
    </div>
  </section>;
}
