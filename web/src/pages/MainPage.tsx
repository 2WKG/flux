/**
 * The primary `/` experience: a deck.gl view over the layer API.
 *
 * The API currently publishes the ACTIVSg2000 bus geometry with its synthetic
 * topology provenance. That makes it useful for inspecting the simulation
 * input, but it does not make it a real transmission map. A checked-in
 * five-bus bundle is retained below only as the explicit offline fallback.
 */
import { useCallback, useEffect, useMemo, useReducer, useState } from "react";
import type { LayersList, PickingInfo } from "@deck.gl/core";
import { ColumnLayer, TextLayer } from "@deck.gl/layers";
import Map from "react-map-gl/maplibre";
import fixture from "../../../data/demo/bundle.json";
import { FailureState } from "../failure-states/FailureState";
import { Inspector, type InspectorAsset } from "../inspector/Inspector";
import { OFFLINE_BASEMAP_STYLE } from "../renderer/basemap";
import { DeckOverlay } from "../renderer/DeckOverlay";
import "maplibre-gl/dist/maplibre-gl.css";

type Feature = {
  readonly id: string;
  readonly geometry: { readonly type: "Point"; readonly coordinates: readonly [number, number] };
  readonly properties: {
    readonly bus_id?: string;
    readonly name?: string;
    readonly kv?: number;
    readonly coord_source?: string;
    readonly source_name?: string;
    readonly county_fips?: string | null;
    readonly ba_code?: string | null;
  };
};

type LayerCollection = {
  readonly type: "FeatureCollection";
  readonly crs: { readonly properties: { readonly name: "EPSG:4326" } };
  readonly provenance: {
    readonly source_kinds: readonly string[];
    readonly topology?: string | null;
    readonly source_names?: readonly string[];
    readonly coord_sources?: readonly string[];
    readonly fixture_batch_ids?: readonly string[];
  };
  readonly features: readonly Feature[];
};

type SceneState =
  | { readonly kind: "loading" }
  | { readonly kind: "ready"; readonly collection: LayerCollection }
  | { readonly kind: "unavailable"; readonly message: string };

type Fixture = {
  readonly fixtureHash: string;
  readonly execution: { readonly provenance: { readonly artifactId: string }; readonly limitations: readonly string[] };
  readonly network: { readonly buses: readonly { readonly id: string; readonly name: string }[] };
};

const fallback = fixture as unknown as Fixture;

function isPointFeature(value: unknown): value is Feature {
  if (typeof value !== "object" || value === null) return false;
  const feature = value as Partial<Feature>;
  const coordinates = feature.geometry?.coordinates;
  return typeof feature.id === "string" && feature.id.length > 0 &&
    feature.geometry?.type === "Point" && Array.isArray(coordinates) && coordinates.length === 2 &&
    coordinates.every((coordinate) => typeof coordinate === "number" && Number.isFinite(coordinate)) &&
    typeof feature.properties === "object" && feature.properties !== null;
}

/** Validate the bare GeoJSON contract before it becomes a drawable deck layer. */
function collectionFrom(value: unknown): LayerCollection | null {
  if (typeof value !== "object" || value === null) return null;
  const collection = value as Partial<LayerCollection>;
  if (collection.type !== "FeatureCollection" || collection.crs?.properties?.name !== "EPSG:4326") return null;
  if (!Array.isArray(collection.features) || collection.features.length === 0 || !collection.features.every(isPointFeature)) return null;
  const provenance = collection.provenance;
  if (!provenance || !Array.isArray(provenance.source_kinds) || provenance.source_kinds.length === 0 ||
    !provenance.source_kinds.every((kind) => typeof kind === "string")) return null;
  return collection as LayerCollection;
}

function sourceFailure(response: Response): string {
  return response.status === 404
    ? "The layer API is not mounted at this origin."
    : `The layer API returned ${response.status} ${response.statusText || "without a usable response"}.`;
}

function usePrimaryScene() {
  const [state, setState] = useState<SceneState>({ kind: "loading" });
  const load = useCallback(() => {
    const controller = new AbortController();
    setState({ kind: "loading" });
    void fetch("/layers/buses", { signal: controller.signal, headers: { Accept: "application/geo+json" } })
      .then(async (response) => {
        if (!response.ok) throw new Error(sourceFailure(response));
        const collection = collectionFrom(await response.json());
        if (!collection) throw new Error("The layer API response was not a usable EPSG:4326 bus collection.");
        // A fixture response never becomes the primary simulation merely because
        // it was served over HTTP. It belongs to the named fallback below.
        if (collection.provenance.source_kinds.includes("fixture")) {
          throw new Error("The layer API reported fixture provenance, so it cannot be used as the primary simulation.");
        }
        if (!collection.provenance.source_kinds.every((kind) => kind === "simulated")) {
          throw new Error("The layer API did not supply a recognized synthetic simulation provenance label.");
        }
        setState({ kind: "ready", collection });
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setState({ kind: "unavailable", message: error instanceof Error ? error.message : "The layer API could not be read." });
      });
    return () => controller.abort();
  }, []);

  useEffect(() => load(), [load]);
  return [state, load] as const;
}

function inspectorAsset(feature: Feature): InspectorAsset {
  const properties = feature.properties;
  return {
    status: "synthetic",
    artifactLabel: "synthetic",
    id: feature.id,
    name: properties.name ?? `Bus ${properties.bus_id ?? feature.id}`,
    kind: "ACTIVSg2000 synthetic bus",
    message: "This position comes from the server's synthetic ACTIVSg2000 topology. It is not a real transmission asset or operating-grid location.",
    fields: [
      { label: "Base voltage", value: properties.kv === undefined ? undefined : String(properties.kv), unit: "kV", status: properties.kv === undefined ? "unavailable" : "available", provenanceId: "buses.base_kv" },
      { label: "Coordinate source", value: properties.coord_source, status: properties.coord_source ? "available" : "unavailable", provenanceId: "buses.coord_source" },
      { label: "Balancing authority", value: properties.ba_code ?? undefined, status: properties.ba_code ? "available" : "unavailable", provenanceId: "buses.ba_code" },
    ],
    provenance: properties.source_name ? [{ sourceName: properties.source_name, transformation: "Layer API GeoJSON feature" }] : [],
    caveats: ["The server marks this topology as synthetic (ACTIVSg2000).", "No line-flow, outage, or interconnection conclusion follows from selecting a bus."],
  };
}

function Simulation({ collection }: { readonly collection: LayerCollection }) {
  const [visible, setVisible] = useState(true);
  const [selected, setSelected] = useState<Feature | null>(null);
  const [rendererFailure, setRendererFailure] = useState<string | null>(null);
  const rendered = visible ? collection.features : [];
  const layers = useMemo<LayersList>(() => [
    new ColumnLayer<Feature>({
      id: "synthetic-grid-buses",
      data: rendered,
      getPosition: (feature) => feature.geometry.coordinates,
      radius: 7000,
      getElevation: () => 1,
      elevationScale: 500,
      extruded: true,
      diskResolution: 12,
      getFillColor: [137, 151, 238, 210],
      getLineColor: [223, 231, 255, 255],
      stroked: true,
      lineWidthMinPixels: 1,
      pickable: true,
      onClick: (info: PickingInfo<Feature>) => setSelected(info.object ?? null),
      updateTriggers: { getPosition: [rendered] },
    }),
    new TextLayer<Feature>({
      id: "synthetic-grid-status-labels",
      data: rendered,
      getPosition: (feature) => feature.geometry.coordinates,
      getText: (feature) => `⋯ Synthetic · ${feature.properties.name ?? feature.id}`,
      getSize: 12,
      getColor: [223, 231, 255, 255],
      getPixelOffset: [14, -10],
      getTextAnchor: "start",
      background: true,
      getBackgroundColor: [7, 18, 33, 220],
      backgroundPadding: [5, 3],
      pickable: true,
      onClick: (info: PickingInfo<Feature>) => setSelected(info.object ?? null),
    }),
  ], [rendered]);

  return <>
    <section aria-label="Deck.gl grid simulation" style={{ border: "1px solid #315673", borderRadius: 12, overflow: "hidden", minHeight: "64vh", position: "relative" }}>
      <Map
        initialViewState={{ longitude: -99, latitude: 31, zoom: 5.2, pitch: 52, bearing: -18 }}
        mapStyle={OFFLINE_BASEMAP_STYLE}
        style={{ height: "64vh", minHeight: 460 }}
        onError={(event) => setRendererFailure(event.error.message)}
      >
        <DeckOverlay layers={layers} onFailed={setRendererFailure} />
      </Map>
      <div role="status" style={{ position: "absolute", inset: "auto 12px 12px 12px", maxWidth: 720, padding: 12, border: "1px solid #637b9b", borderRadius: 8, background: "rgb(7 18 33 / 94%)", color: "#edf5ff" }}>
        <strong>deck.gl simulation scene · Synthetic</strong>
        <div>{rendered.length} server-supplied ACTIVSg2000 buses. Every visible node carries a Synthetic label; column height is a scene marker, not a measured asset value. The basemap has no geographic tiles.</div>
        <label style={{ display: "block", marginTop: 8 }}><input type="checkbox" checked={visible} onChange={(event) => setVisible(event.currentTarget.checked)} /> Show synthetic bus layer</label>
        {rendererFailure && <FailureState state={{ kind: "failed", message: `Renderer unavailable: ${rendererFailure}` }} />}
      </div>
    </section>
    <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) minmax(280px, 420px)", gap: 14, marginTop: 14 }}>
      <section style={{ border: "1px solid #315673", borderRadius: 12, padding: 16 }} aria-label="Scene evidence">
        <p className="eyebrow">LIVE LAYER API</p>
        <h2 style={{ margin: "6px 0" }}>Synthetic topology, visibly labelled</h2>
        <p>The API reports <code>{collection.provenance.topology ?? "synthetic topology"}</code>. This browser renders the reported geometry for simulation inspection and does not promote it to a source-supported grid.</p>
        <p>Sources: {collection.provenance.source_names?.join(", ") || "not supplied"}. Coordinate inputs: {collection.provenance.coord_sources?.join(", ") || "not supplied"}.</p>
      </section>
      <Inspector asset={selected ? inspectorAsset(selected) : null} />
    </div>
  </>;
}

/** A deliberately small fallback; the detailed five-bus explorer is no longer the main route. */
function OfflineFallback({ message, retry }: { readonly message: string; readonly retry: () => void }) {
  return <section aria-label="Offline five-bus fallback" style={{ border: "1px solid #694f2f", borderRadius: 12, padding: 18, background: "#251d13" }}>
    <p className="eyebrow">OFFLINE FALLBACK · SYNTHETIC FIVE-BUS FIXTURE</p>
    <h2>The primary layer API is unavailable.</h2>
    <p>{message}</p>
    <p>This fallback is the checked-in fixture <code>{fallback.execution.provenance.artifactId}</code> ({fallback.fixtureHash}). It is not Texas, Minnesota, ERCOT, MISO, or an interconnection result.</p>
    <ul>{fallback.network.buses.map((bus) => <li key={bus.id}>{bus.name} · Synthetic fixture bus</li>)}</ul>
    <p>{fallback.execution.limitations[0] ?? "No runtime model result is available."}</p>
    <button type="button" className="ghost" onClick={retry}>Retry layer API</button>
  </section>;
}

/**
 * Kept as a pure compatibility export for the shell test and for callers that
 * surface the evidence-chat capability elsewhere. The simulation does not
 * render it until an actual `/ask` integration is connected.
 */
export type ChatAction = "toggle";
export function chatReducer(open: boolean, action: ChatAction): boolean {
  return action === "toggle" ? !open : open;
}

export function ChatDockView({ open, onToggle }: { readonly open: boolean; readonly onToggle: () => void }) {
  return <section className={`chat-dock ${open ? "expanded" : "collapsed"}`} aria-label="Evidence chat dock">
    <button className="chat-toggle" onClick={onToggle} aria-expanded={open} aria-controls="chat-dock-body">
      <span><span className="eyebrow">Evidence chat</span><strong>{open ? "Chat contract and limits" : "Ask about visible evidence"}</strong></span>
      <span className="chat-state">{open ? "Collapse" : "Not available in this offline build"}</span>
    </button>
    <div id="chat-dock-body" className="chat-body" hidden={!open}>
      <p>This offline synthetic preview has no Copilot endpoint, model result, or Minnesota artifact to query.</p>
      <p>When a server-backed evidence surface is available, this dock must show its tool trail, citations, status, and limitations instead of inventing an answer.</p>
    </div>
  </section>;
}

function ChatDock() {
  const [open, toggle] = useReducer(chatReducer, false);
  return <ChatDockView open={open} onToggle={() => toggle("toggle")} />;
}

export function App() {
  const [scene, retry] = usePrimaryScene();
  return <main data-source-status={scene.kind === "ready" ? "synthetic" : "unavailable"}>
    <header className="shell-intro">
      <p className="eyebrow">GRID DIGITAL TWIN / PRIMARY SIMULATION</p>
      <h1>Inspect the grid simulation scene.</h1>
      <p>The main route starts with the deck.gl scene fed by the server layer API. The current topology is explicitly synthetic; it supports simulation inspection, not a claim about a real grid.</p>
    </header>
    {scene.kind === "loading" && <FailureState state={{ kind: "loading", message: "Loading the primary simulation layer." }} />}
    {scene.kind === "ready" && <Simulation collection={scene.collection} />}
    {scene.kind === "unavailable" && <OfflineFallback message={scene.message} retry={retry} />}
    <ChatDock />
  </main>;
}
