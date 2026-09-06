import { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { GeoJsonLayer } from "@deck.gl/layers";
import type { LayersList } from "@deck.gl/core";
import Map from "react-map-gl/maplibre";
import { DeckOverlay } from "./DeckOverlay";
import { OFFLINE_BASEMAP_STYLE } from "./basemap";
import { geometryAccounting, pageFrom, renderableFeatures, type SpatialItem, type SpatialPage } from "./spatial-scene";
import "maplibre-gl/dist/maplibre-gl.css";
import "./renderer.css";

const LAYERS = { tx: ["line", "generation", "storage"], mn: ["line", "substation", "generation", "storage"] } as const;
type State = keyof typeof LAYERS;
type Load = { kind: "loading" } | { kind: "ready"; pages: readonly SpatialPage[] } | { kind: "failure"; message: string };

async function getAllPages(state: State, layer: string, bbox: string | null, signal: AbortSignal): Promise<readonly SpatialPage[]> {
  const pages: SpatialPage[] = [];
  let cursor: string | null = null;
  do {
    const query = new URLSearchParams({ state, version: "1.1.0", limit: "100" });
    if (cursor) query.set("cursor", cursor);
    if (bbox) query.set("bbox", bbox);
    const response = await fetch(`/api/v1/grid/layers/${encodeURIComponent(layer)}?${query}`, { signal });
    const payload = pageFrom(await response.json());
    if (!response.ok || payload === null || "status" in payload) throw new Error(payload && "status" in payload ? payload.error.message : `Grid API returned ${response.status}.`);
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

function LiveGridApp() {
  const [state, setState] = useState<State>("tx");
  const [layers, setLayers] = useState<readonly string[]>(LAYERS.tx);
  const [load, setLoad] = useState<Load>({ kind: "loading" });
  const [selected, setSelected] = useState<SpatialItem | null>(null);
  const [query, setQuery] = useState("");
  const [bbox, setBbox] = useState<string | null>(null);
  useEffect(() => { setLayers(LAYERS[state]); setSelected(null); }, [state]);
  useEffect(() => {
    let current = true;
    const controller = new AbortController();
    setLoad({ kind: "loading" });
    Promise.all(layers.map((layer) => getAllPages(state, layer, bbox, controller.signal))).then((pages) => current && setLoad({ kind: "ready", pages: pages.flat() })).catch((error) => {
      if (current && !(error instanceof DOMException && error.name === "AbortError")) setLoad({ kind: "failure", message: error instanceof Error ? error.message : String(error) });
    });
    return () => { current = false; controller.abort(); };
  }, [state, layers, bbox]);
  const items = useMemo(() => load.kind === "ready" ? load.pages.flatMap((page) => page.items) : [], [load]);
  const filtered = useMemo(() => query.trim() ? items.filter((item) => item.asset_id.toLowerCase().includes(query.trim().toLowerCase()) || item.asset_kind.toLowerCase().includes(query.trim().toLowerCase())) : items, [items, query]);
  const features = useMemo(() => renderableFeatures(filtered), [filtered]);
  const accounting = geometryAccounting(items);
  const release = load.kind === "ready" && load.pages[0] ? load.pages[0] : null;
  const deckLayers = useMemo<LayersList>(() => [new GeoJsonLayer({ id: "physical-inventory-display-geometry", data: features as never, pickable: true,
    stroked: true, filled: true, lineWidthMinPixels: 2, pointRadiusMinPixels: 5, getLineColor: [112, 213, 255, 235], getFillColor: [255, 191, 94, 220], getPointRadius: 60,
    onClick: ({ object }) => object && setSelected((object as { properties: SpatialItem }).properties),
  })], [features]);
  const updateLayer = (layer: string, checked: boolean) => setLayers((current) => checked ? [...current, layer] : current.filter((id) => id !== layer));
  return <main className="grid-app" data-runtime="spatial-api">
    <header><p>Flux physical inventory</p><h1>Source-backed map</h1><span>Read-only spatial API · physical inventory; electrical model: none</span></header>
    <section className="grid-controls" aria-label="Map controls"><label>State <select value={state} onChange={(event) => setState(event.target.value as State)}><option value="tx">Texas</option><option value="mn">Minnesota</option></select></label>
      <fieldset><legend>Layers</legend>{LAYERS[state].map((layer) => <label key={layer}><input type="checkbox" checked={layers.includes(layer)} onChange={(event) => updateLayer(layer, event.target.checked)} /> {layer}</label>)}</fieldset>
      <label>Search rendered inventory <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Asset ID or kind" /></label></section>
    <section className="grid-map" aria-label="Source-backed physical inventory map"><Map key={state} initialViewState={state === "tx" ? { longitude: -99, latitude: 31, zoom: 5 } : { longitude: -94, latitude: 46, zoom: 5.6 }} mapStyle={OFFLINE_BASEMAP_STYLE} onMoveEnd={(event) => { const b = event.target.getBounds(); setBbox([b.getWest(), b.getSouth(), b.getEast(), b.getNorth()].join(",")); }}><DeckOverlay layers={deckLayers} /></Map>
      <div className="grid-map-note" role="status">{load.kind === "loading" ? "Loading source-backed inventory…" : load.kind === "failure" ? `Unavailable: ${load.message}` : <><strong>{release?.artifact_id} · {release?.artifact_version}</strong><span>{accounting.renderable} rendered from {accounting.totalLoaded} loaded {bbox ? "viewport" : "state"} records; {accounting.unavailableGeometry} loaded records have unavailable geometry and no marker was created.</span><span>Release SHA-256: {release?.release_sha256}; coverage rows remain available in the response.</span></>}</div></section>
    <section className="grid-results" aria-label="Rendered inventory search results"><h2>Rendered inventory</h2>{features.slice(0, 25).map((feature) => <button key={feature.id} type="button" onClick={() => setSelected(feature.properties)}>{feature.id} · {feature.properties.asset_kind}</button>)}{features.length > 25 && <p>Showing the first 25 matching rendered features. Refine search to narrow this list.</p>}</section>
    <Inspector item={selected} />
  </main>;
}

createRoot(document.getElementById("root")!).render(<LiveGridApp />);
