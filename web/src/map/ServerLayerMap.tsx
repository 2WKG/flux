import { useEffect, useState } from "react";
import Map, {
  Layer,
  Source,
  type MapLayerMouseEvent,
} from "react-map-gl/maplibre";
import "maplibre-gl/dist/maplibre-gl.css";
import type { Feature, Geometry, GeoJsonProperties } from "geojson";
import {
  featureProperties,
  toLayerDisplayState,
  type LayerDisplayState,
} from "./layerContract";
import "./serverLayerMap.css";

const DARK_BASEMAP = "https://tiles.openfreemap.org/styles/dark";
const RENDER_LAYER_IDS = ["server-polygons", "server-lines", "server-points"];

type ServerLayerMapProps = Readonly<{
  endpoint: string;
  title?: string;
}>;

/** Renders only declared geometry and properties returned by the map-layer API. */
export function ServerLayerMap({
  endpoint,
  title = "Server map layer",
}: ServerLayerMapProps) {
  const [displayState, setDisplayState] = useState<LayerDisplayState | "loading">("loading");
  const [selectedFeature, setSelectedFeature] = useState<
    Feature<Geometry, GeoJsonProperties> | undefined
  >();

  useEffect(() => {
    const controller = new AbortController();
    setDisplayState("loading");
    setSelectedFeature(undefined);
    void fetch(endpoint, { signal: controller.signal })
      .then(async (response) => response.json().catch(() => null))
      .then((payload: unknown) => {
        if (!controller.signal.aborted) {
          setDisplayState(toLayerDisplayState(payload));
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setDisplayState(toLayerDisplayState(null));
        }
      });
    return () => controller.abort();
  }, [endpoint]);

  if (displayState === "loading") {
    return null;
  }
  if (displayState.kind === "unavailable") {
    return <LayerStatePanel title={title} label="Layer unavailable" message={displayState.message} />;
  }
  if (displayState.kind === "empty") {
    return <LayerStatePanel title={title} label={`${displayState.layer} · ${displayState.crs}`} message={displayState.message} />;
  }
  const { presentation } = displayState;

  const onClick = (event: MapLayerMouseEvent) => {
    const feature = event.features?.[0];
    setSelectedFeature(
      feature
        ? {
            type: "Feature",
            geometry: feature.geometry as Geometry,
            properties: feature.properties,
          }
        : undefined,
    );
  };
  const properties = featureProperties(selectedFeature);

  return (
    <section className="server-layer-map" aria-label={title}>
      <header className="server-layer-map__legend">
        <div>
          <p className="server-layer-map__kicker">{presentation.layer}</p>
          <h2>{title}</h2>
        </div>
        <dl>
          <div>
            <dt>Status</dt>
            <dd>ok</dd>
          </div>
          <div>
            <dt>CRS</dt>
            <dd>{presentation.crs}</dd>
          </div>
          <div>
            <dt>Scenario</dt>
            <dd>{presentation.scenario ?? "not declared by server"}</dd>
          </div>
          <div>
            <dt>Source class</dt>
            <dd>{presentation.sourceClasses.join(", ") || "not declared by server"}</dd>
          </div>
        </dl>
      </header>
      <div className="server-layer-map__canvas">
        <Map
          initialViewState={{ longitude: -94, latitude: 46, zoom: 5 }}
          mapStyle={DARK_BASEMAP}
          interactiveLayerIds={RENDER_LAYER_IDS}
          onClick={onClick}
        >
          <Source
            id="server-geometry"
            type="geojson"
            data={presentation.featureCollection}
          >
            <Layer
              id="server-polygons"
              type="fill"
              filter={["==", ["geometry-type"], "Polygon"]}
              paint={{ "fill-color": "#38bdf8", "fill-opacity": 0.35 }}
            />
            <Layer
              id="server-lines"
              type="line"
              filter={["==", ["geometry-type"], "LineString"]}
              paint={{ "line-color": "#fbbf24", "line-width": 3 }}
            />
            <Layer
              id="server-points"
              type="circle"
              filter={["==", ["geometry-type"], "Point"]}
              paint={{
                "circle-color": "#38bdf8",
                "circle-radius": 6,
                "circle-stroke-color": "#f8fafc",
                "circle-stroke-width": 1,
              }}
            />
          </Source>
        </Map>
      </div>
      <div className="server-layer-map__details">
        <section aria-label="Layer field labels">
          <h3>Server field labels</h3>
          <ul>
            {Object.entries(presentation.attributes).map(([field, descriptor]) => (
              <li key={field}>
                <b>{field}</b>
                <span>{descriptor.unit}</span>
                <code>{descriptor.source}</code>
              </li>
            ))}
          </ul>
        </section>
        <section aria-label="Selected server feature values">
          <h3>Selected server feature values</h3>
          {properties.length === 0 ? (
            <p>Select rendered geometry to inspect its server values.</p>
          ) : (
            <dl>
              {properties.map(([key, value]) => (
                <div key={key}>
                  <dt>{key}</dt>
                  <dd>{value}</dd>
                </div>
              ))}
            </dl>
          )}
        </section>
      </div>
    </section>
  );
}

function LayerStatePanel({
  title,
  label,
  message,
}: Readonly<{ title: string; label: string; message: string }>) {
  return (
    <section className="server-layer-map server-layer-map--state" aria-label={title}>
      <p className="server-layer-map__kicker">{label}</p>
      <h2>{title}</h2>
      <p>{message}</p>
      <p className="server-layer-map__state-note">No geometry or values are rendered.</p>
    </section>
  );
}
