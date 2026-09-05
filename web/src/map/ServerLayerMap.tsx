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
  toLayerPresentation,
  type LayerPresentation,
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
  const [presentation, setPresentation] = useState<LayerPresentation | null>(null);
  const [selectedFeature, setSelectedFeature] = useState<
    Feature<Geometry, GeoJsonProperties> | undefined
  >();

  useEffect(() => {
    const controller = new AbortController();
    setPresentation(null);
    setSelectedFeature(undefined);
    void fetch(endpoint, { signal: controller.signal })
      .then(async (response) => (response.ok ? response.json() : null))
      .then((payload: unknown) => {
        if (!controller.signal.aborted) {
          setPresentation(toLayerPresentation(payload));
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setPresentation(null);
        }
      });
    return () => controller.abort();
  }, [endpoint]);

  if (!presentation) {
    return null;
  }

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
