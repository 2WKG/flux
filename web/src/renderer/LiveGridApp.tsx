import { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import Map, { Layer, Source, type MapRef } from "react-map-gl/maplibre";
import { OFFLINE_BASEMAP_STYLE } from "./basemap";
import { geometryAccounting, pageFrom, renderableFeatures, type SpatialItem, type SpatialPage } from "./spatial-scene";
import "maplibre-gl/dist/maplibre-gl.css";
import "./renderer.css";

const LAYERS = { tx: ["line", "generation", "storage"], mn: ["line", "substation", "generation", "storage"] } as const;
type State = keyof typeof LAYERS;
type Load = { kind: "loading" } | { kind: "ready"; pages: readonly SpatialPage[] } | { kind: "failure"; message: string; retryable: boolean };

class GridRequestError extends Error { constructor(message: string, readonly retryable: boolean) { super(message); } }

async function getAllPages(state: State, layer: string, bbox: string | null, signal: AbortSignal): Promise<readonly SpatialPage[]> {
  const pages: SpatialPage[] = [];
  let cursor: string | null = null;
  do {
    const query = new URLSearchParams({ state, version: "1.1.0", limit: "100" });
    if (cursor) query.set("cursor", cursor);
    if (bbox) query.set("bbox", bbox);
    const response = await fetch(`/api/v1/grid/layers/${encodeURIComponent(layer)}?${query}`, { signal });
    const payload = pageFrom(await response.json());
    if (!response.ok || payload === null || "status" in payload) throw new GridRequestError(payload && "status" in payload ? payload.error.message : `Grid API returned ${response.status}.`, response.status >= 500);
    pages.push(payload);
    cursor = payload.page.next_cursor;
  } while (cursor);
  return pages;
}

function Inspector({ item }: { item: SpatialItem | null }) {
  if (!item) return <aside className="grid-inspector"><h2>Inspector</h2><p>Select a rendered source feature to inspect its exact ID, source record, geometry and coverage evidence.</p></aside>;
  const native = item.native_crs ?? "Unavailable";
  return <aside className="grid-inspector" aria-label="Selected asset inspector">
    <h2>{item.asset_id}</h2><p>{item.asset_class} · {item.asset_kind}</p>
    <dl><div><dt>Availability</dt><dd>{item.availability}</dd></div><div><dt>Geometry status</dt><dd>{item.geometry_status}</dd></div>
      <div><dt>Display CRS</dt><dd>{item.display_crs ?? "Unavailable"}</dd></div><div><dt>Native CRS</dt><dd>{native}</dd></div>
      <div><dt>Accuracy basis</dt><dd>{item.geometry_accuracy_basis ?? "Unavailable"}</dd></div><div><dt>Precision</dt><dd>{item.geometry_precision_m === null ? "Unavailable" : `${item.geometry_precision_m} m`}</dd></div>
      <div><dt>Source ID</dt><dd>{item.provenance.source_id}</dd></div><div><dt>Source record</dt><dd>{item.provenance.source_record_id}</dd></div>
      <div><dt>Authority</dt><dd>{item.provenance.authority}</dd></div><div><dt>Version</dt><dd>{item.provenance.source_version}</dd></div>
      <div><dt>Transform</dt><dd>{item.transform_provenance ? `${item.transform_provenance.method}: ${item.transform_provenance.source_crs} → ${item.transform_provenance.display_crs}` : "Unavailable"}</dd></div>
    </dl>
  </aside>;
}

function boundsOf(features: ReturnType<typeof renderableFeatures>): [[number, number], [number, number]] | null {
  const points: [number, number][] = [];
  const visit = (value: unknown) => {
    if (!Array.isArray(value)) return;
    if (value.length >= 2 && typeof value[0] === "number" && typeof value[1] === "number") {
      if (Number.isFinite(value[0]) && Number.isFinite(value[1])) points.push([value[0], value[1]]);
      return;
    }
    value.forEach(visit);
  };
  features.forEach((feature) => visit(feature.geometry.coordinates));
  if (points.length === 0) return null;
  const longitudes = points.map((point) => point[0]); const latitudes = points.map((point) => point[1]);
  return [[Math.min(...longitudes), Math.min(...latitudes)], [Math.max(...longitudes), Math.max(...latitudes)]];
}

function coordinatesOf(value: unknown): [number, number][] {
  if (!Array.isArray(value)) return [];
  if (value.length >= 2 && typeof value[0] === "number" && typeof value[1] === "number") return [[value[0], value[1]]];
  return value.flatMap(coordinatesOf);
}

function LiveGridApp() {
  const [state, setState] = useState<State>("tx");
  const [layers, setLayers] = useState<readonly string[]>(LAYERS.tx);
  const [load, setLoad] = useState<Load>({ kind: "loading" });
  const [selected, setSelected] = useState<SpatialItem | null>(null);
  const [query, setQuery] = useState("");
  const [bbox, setBbox] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  const [projectionEpoch, setProjectionEpoch] = useState(0);
  const mapRef = useRef<MapRef>(null);
  useEffect(() => { setLayers(LAYERS[state]); setSelected(null); setBbox(null); }, [state]);
  useEffect(() => {
    let current = true;
    const controller = new AbortController();
    setLoad({ kind: "loading" });
    Promise.all(layers.map((layer) => getAllPages(state, layer, bbox, controller.signal))).then((pages) => current && setLoad({ kind: "ready", pages: pages.flat() })).catch((error) => {
      if (current && !(error instanceof DOMException && error.name === "AbortError")) setLoad({ kind: "failure", message: error instanceof Error ? error.message : String(error), retryable: error instanceof GridRequestError && error.retryable });
    });
    return () => { current = false; controller.abort(); };
  }, [state, layers, bbox, refresh]);
  const items = useMemo(() => load.kind === "ready" ? load.pages.flatMap((page) => page.items) : [], [load]);
  const filtered = useMemo(() => query.trim() ? items.filter((item) => item.asset_id.toLowerCase().includes(query.trim().toLowerCase()) || item.asset_kind.toLowerCase().includes(query.trim().toLowerCase())) : items, [items, query]);
  const features = useMemo(() => renderableFeatures(filtered), [filtered]);
  const featureCollection = useMemo(() => ({ type: "FeatureCollection" as const, features: features.map((feature) => ({ ...feature, properties: { asset_id: feature.id } })) }), [features]);
  const featureBounds = useMemo(() => boundsOf(features), [features]);
  const overlayGeometry = useMemo(() => {
    const map = mapRef.current; if (!map) return [];
    return features.map((feature) => ({ feature, points: coordinatesOf(feature.geometry.coordinates).map(([x, y]) => { const point = map.project([x, y]); return [point.x, point.y] as const; }) }));
  }, [features, projectionEpoch]);
  const overlayViewBox = useMemo(() => { const container = mapRef.current?.getContainer(); return `0 0 ${container?.clientWidth ?? 1} ${container?.clientHeight ?? 1}`; }, [projectionEpoch]);
  const accounting = geometryAccounting(items);
  const release = load.kind === "ready" && load.pages[0] ? load.pages[0] : null;
  const coverage = useMemo(() => {
    // Each layer response carries its own class coverage. Combine the loaded
    // envelopes before de-duplicating so the first selected layer cannot hide
    // EIA's unavailable-unit counts or another source scope.
    const rows = load.kind === "ready" ? load.pages.flatMap((page) => page.coverage) : [];
    const seen = new Set<string>();
    return rows.flatMap((row) => {
      if (typeof row !== "object" || row === null || Array.isArray(row)) return [];
      const value = row as Record<string, unknown>;
      const keys = ["asset_class", "status", "scope_id", "source_scope", "reason"];
      if (keys.some((key) => typeof value[key] !== "string")) return [];
      const key = `${value.asset_class}:${value.scope_id}`;
      if (seen.has(key)) return []; seen.add(key);
      return [{ assetClass: value.asset_class as string, status: value.status as string, scope: value.source_scope as string, reason: value.reason as string, observed: value.observed_count, denominator: value.denominator_count, unknown: value.unknown_count, unavailable: value.unavailable_count }];
    });
  }, [load]);
  const updateLayer = (layer: string, checked: boolean) => setLayers((current) => checked ? [...current, layer] : current.filter((id) => id !== layer));
  useEffect(() => {
    if (featureBounds && bbox === null) mapRef.current?.fitBounds(featureBounds, { padding: 64, maxZoom: 11, duration: 0 });
  }, [featureBounds, state, bbox]);
  return <main className="grid-app" data-runtime="spatial-api">
    <header><p>Flux physical inventory</p><h1>Source-backed map</h1><span>Read-only spatial API · physical inventory; electrical model: none</span></header>
    <section className="grid-controls" aria-label="Map controls"><label>State <select value={state} onChange={(event) => setState(event.target.value as State)}><option value="tx">Texas</option><option value="mn">Minnesota</option></select></label>
      <fieldset><legend>Layers</legend>{LAYERS[state].map((layer) => <label key={layer}><input type="checkbox" checked={layers.includes(layer)} onChange={(event) => updateLayer(layer, event.target.checked)} /> {layer}</label>)}</fieldset>
      <label>Search rendered inventory <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Asset ID or kind" /></label></section>
    <section className="grid-map" aria-label="Source-backed physical inventory map"><Map key={state} ref={mapRef} initialViewState={state === "tx" ? { longitude: -99, latitude: 31, zoom: 5 } : { longitude: -94, latitude: 46, zoom: 5.6 }} mapStyle={OFFLINE_BASEMAP_STYLE} onLoad={() => setProjectionEpoch((value) => value + 1)} onMove={() => setProjectionEpoch((value) => value + 1)} onMoveEnd={(event) => { const b = event.target.getBounds(); setBbox([b.getWest(), b.getSouth(), b.getEast(), b.getNorth()].join(",")); }}><Source id="physical-inventory-source" type="geojson" data={featureCollection as never}><Layer id="physical-inventory-lines" type="line" paint={{ "line-color": "#3ee3ff", "line-width": 4 }} /></Source></Map><svg className="grid-geometry-overlay" viewBox={overlayViewBox} aria-label="Visible source geometry">{overlayGeometry.map(({ feature, points }) => feature.geometry.type.includes("Point") ? points.map(([x, y], index) => <circle key={`${feature.id}:${index}`} cx={x} cy={y} r="9" onClick={(event) => { event.stopPropagation(); setSelected(feature.properties); }} />) : <polyline key={feature.id} points={points.map((point) => point.join(",")).join(" ")} onClick={(event) => { event.stopPropagation(); setSelected(feature.properties); }} />)}</svg>
      <div className="grid-map-note" role="status">{load.kind === "loading" ? "Loading source-backed inventory…" : load.kind === "failure" ? <><span>Unavailable: {load.message}</span>{load.retryable && <button type="button" onClick={() => setRefresh((value) => value + 1)}>Retry inventory request</button>}</> : <><strong>{release?.artifact_id} · {release?.artifact_version}</strong><span>{accounting.renderable} rendered from {accounting.totalLoaded} loaded {bbox ? "viewport" : "state"} records; {accounting.unavailableGeometry} loaded records have unavailable geometry and no marker was created.</span><span>Release SHA-256: {release?.release_sha256}; coverage disclosure follows.</span></>}</div></section>
    <section className="grid-coverage" aria-label="Coverage and geometry availability"><h2>Coverage and geometry availability</h2>{coverage.map((row) => <article key={`${row.assetClass}:${row.scope}`}><strong>{row.assetClass} · {row.status}</strong><p>{row.scope}</p><p>Observed: {String(row.observed ?? "Unknown")} / denominator: {String(row.denominator ?? "Unknown")}; unknown: {String(row.unknown ?? "Unknown")}; unavailable: {String(row.unavailable ?? "Unknown")}</p><p>{row.reason}</p></article>)}</section>
    <section className="grid-results" aria-label="Rendered inventory search results"><h2>Rendered inventory</h2>{features.slice(0, 25).map((feature) => <button key={feature.id} type="button" onClick={() => setSelected(feature.properties)}>{feature.id} · {feature.properties.asset_kind}</button>)}{features.length > 25 && <p>Showing the first 25 matching rendered features. Refine search to narrow this list.</p>}</section>
    <Inspector item={selected} />
  </main>;
}

createRoot(document.getElementById("root")!).render(<LiveGridApp />);
