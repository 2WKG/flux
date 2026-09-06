import { Suspense, lazy, useEffect, useMemo, useState } from "react";
import { STATUS_COPY } from "../source-truth";
import {
  coverageRows,
  geometryAccounting,
  renderableFeatures,
  type SpatialItem,
  type SpatialPage,
} from "../data/grid-inventory";
import { GRID_LAYERS, type GridState } from "../data/grid-client";
import { sceneFor } from "./grid-scene";
import { boundsOf } from "./grid-scene";

/**
 * The source-backed physical-inventory surface, composed inside the one App.
 *
 * Salvaged from PR #245's `LiveGridApp` — the coverage disclosure, the release
 * identity line, the geometry accounting sentence and the layer/search controls
 * are that PR's, and it is credited on the commit. Four things changed, each of
 * them a finding from its review:
 *
 * 1. **No second map, and no projection-free overlay.** #245 painted a
 *    `viewBox="0 0 1000 1000"` `preserveAspectRatio="none"` SVG of the same
 *    features over the MapLibre canvas and made *that* the clickable surface,
 *    so the page showed two differently-placed renderings of one asset set.
 *    Here the geometry is drawn once, by the merged #213 foundation, and
 *    selection is a list, not a mis-projected hit target.
 * 2. **The display words come from `STATUS_COPY`.** #245 hard-coded
 *    `"Unavailable"` in seven places.
 * 3. **The page walk is bounded and its truncation is disclosed** (see
 *    `src/data/grid-client.ts`).
 * 4. **Every failure envelope keeps its named reason**, including the
 *    `status: "error"` ones #245 discarded.
 *
 * The map itself is loaded lazily: MapLibre and deck.gl are half a megabyte
 * that the rest of the page does not need in order to paint, and keeping them
 * out of the synchronous entry graph is also what lets this panel be rendered
 * and asserted without a WebGL context.
 */
const LazyGridMap = lazy(() => import("./GridMap").then((module) => ({ default: module.GridMap })));

export type GridLoad =
  | { readonly kind: "loading" }
  | { readonly kind: "loaded"; readonly pages: readonly SpatialPage[]; readonly truncated: boolean; readonly nextCursor: string | null }
  | { readonly kind: "refused"; readonly status: "unavailable" | "request_failed"; readonly code: string; readonly message: string; readonly requestId?: string };

export interface GridInventoryPanelProps {
  readonly load: GridLoad;
  readonly state: GridState;
  readonly layers: readonly string[];
  readonly query: string;
  readonly selected: SpatialItem | null;
  readonly onStateChange: (state: GridState) => void;
  readonly onLayersChange: (layers: readonly string[]) => void;
  readonly onQueryChange: (query: string) => void;
  readonly onSelect: (item: SpatialItem | null) => void;
  readonly onRetry: () => void;
}

function SelectedItem({ item }: { item: SpatialItem | null }) {
  if (item === null) {
    return <p className="grid-release">No source feature selected. Choose one from the rendered inventory to read its exact identifier, source record, and geometry provenance.</p>;
  }
  const unavailable = STATUS_COPY.unavailable;
  return <dl className="layer-evidence" aria-label="Selected source feature">
    <div><dt>Asset</dt><dd>{item.asset_id}</dd></div>
    <div><dt>Class</dt><dd>{item.asset_class} · {item.asset_kind}</dd></div>
    <div><dt>Geometry status</dt><dd>{item.geometry_status}</dd></div>
    <div><dt>Display CRS</dt><dd>{item.display_crs ?? unavailable}</dd></div>
    <div><dt>Native CRS</dt><dd>{item.native_crs ?? unavailable}</dd></div>
    <div><dt>Accuracy basis</dt><dd>{item.geometry_accuracy_basis ?? unavailable}</dd></div>
    <div><dt>Precision</dt><dd>{item.geometry_precision_m === null ? unavailable : `${item.geometry_precision_m} m`}</dd></div>
    <div><dt>Source</dt><dd>{item.provenance.source_id} · {item.provenance.source_record_id}</dd></div>
    <div><dt>Authority</dt><dd>{item.provenance.authority}</dd></div>
    <div><dt>Version</dt><dd>{item.provenance.source_version}</dd></div>
    <div><dt>Transform</dt><dd>{item.transform_provenance
      ? `${item.transform_provenance.method}: ${item.transform_provenance.source_crs} to ${item.transform_provenance.display_crs}`
      : unavailable}</dd></div>
  </dl>;
}

export function GridInventoryPanel({
  load, state, layers, query, selected,
  onStateChange, onLayersChange, onQueryChange, onSelect, onRetry,
}: GridInventoryPanelProps) {
  const pages = load.kind === "loaded" ? load.pages : [];
  const items = useMemo(() => pages.flatMap((page) => page.items), [pages]);
  const trimmed = query.trim().toLowerCase();
  const filtered = useMemo(
    () => trimmed === "" ? items : items.filter((item) =>
      item.asset_id.toLowerCase().includes(trimmed) || item.asset_kind.toLowerCase().includes(trimmed)),
    [items, trimmed],
  );
  const features = useMemo(() => renderableFeatures(filtered), [filtered]);
  // Accounting is over everything loaded, never over the filtered or available
  // subset: the count of records with no geometry is the disclosure's point.
  const accounting = geometryAccounting(items);
  const coverage = useMemo(() => coverageRows(pages), [pages]);
  const scene = useMemo(() => sceneFor(filtered), [filtered]);
  const bounds = useMemo(() => boundsOf(scene.paths, scene.view), [scene]);
  const release = pages[0] ?? null;
  // The renderer needs a document, so it is mounted after the first client
  // render rather than during server rendering.
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  const toggleLayer = (layer: string, checked: boolean) =>
    onLayersChange(checked ? [...layers, layer] : layers.filter((id) => id !== layer));

  return <section className="grid-inventory" aria-label="Source-backed physical inventory">
    <div className="map-head">
      <div>
        <p className="eyebrow">PHYSICAL INVENTORY · {state.toUpperCase()}</p>
        <p className="hint">Read-only spatial API. Physical inventory only; electrical model: none.</p>
      </div>
    </div>

    <section className="grid-controls" aria-label="Inventory map controls">
      <label>State
        <select value={state} onChange={(event) => onStateChange(event.target.value as GridState)}>
          <option value="tx">Texas</option>
          <option value="mn">Minnesota</option>
        </select>
      </label>
      <fieldset>
        <legend>Layers</legend>
        {GRID_LAYERS[state].map((layer) => (
          <label key={layer}>
            <input type="checkbox" checked={layers.includes(layer)} onChange={(event) => toggleLayer(layer, event.target.checked)} />
            {layer}
          </label>
        ))}
      </fieldset>
      <label>Search rendered inventory
        <input value={query} onChange={(event) => onQueryChange(event.target.value)} placeholder="Asset ID or kind" />
      </label>
    </section>

    <div className="grid-map">
      {mounted
        ? <Suspense fallback={<p className="grid-release">Loading the map renderer.</p>}>
            <LazyGridMap view={scene.view} paths={scene.paths} fitBounds={bounds} assetItems={filtered} onAssetSelect={onSelect} />
          </Suspense>
        : <p className="grid-release">The map renderer loads in the browser. {scene.view.detail}</p>}
    </div>

    <div className="grid-map-note" role="status">
      {load.kind === "loading" ? <span>Requesting the source-backed inventory release.</span> : load.kind === "refused" ? <>
        <strong>{STATUS_COPY[load.status]}</strong>
        <span>{load.message}</span>
        <span>Code <code>{load.code}</code>{load.requestId ? <> · request <code>{load.requestId}</code></> : null}</span>
        <button type="button" onClick={onRetry}>Retry the inventory request</button>
      </> : <>
        <strong className="grid-release">{release ? `${release.artifact_id} · ${release.artifact_version}` : STATUS_COPY.unavailable}</strong>
        <span>{accounting.renderable} rendered from {accounting.totalLoaded} loaded records; {accounting.unavailableGeometry} loaded records have unavailable geometry and no marker was created for them.</span>
        <span className="grid-release">Release SHA-256: {release ? release.release_sha256 : STATUS_COPY.unavailable}</span>
        {load.truncated ? <span>The page walk stopped at its cap; more records exist after cursor <code>{load.nextCursor}</code> and are not shown or counted.</span> : null}
      </>}
    </div>

    <section className="grid-coverage" aria-label="Coverage and geometry availability">
      <h2>Coverage and geometry availability</h2>
      {coverage.length === 0
        ? <p>No coverage disclosure was returned with this release.</p>
        : coverage.map((row) => <article key={`${row.assetClass} ${row.scopeId}`}>
          <strong>{row.assetClass} · {row.status}</strong>
          <p>{row.scope}</p>
          <p>Observed {row.observed ?? STATUS_COPY.unavailable} of {row.denominator ?? STATUS_COPY.unavailable}; unknown {row.unknown ?? STATUS_COPY.unavailable}; unavailable {row.unavailable ?? STATUS_COPY.unavailable}.</p>
          <p>{row.reason}</p>
        </article>)}
    </section>

    <section className="grid-results" aria-label="Rendered inventory">
      <h2>Rendered inventory</h2>
      {features.slice(0, 25).map((feature) => (
        <button key={feature.id} type="button" onClick={() => onSelect(feature.properties)}>
          {feature.id} · {feature.properties.asset_kind}
        </button>
      ))}
      {features.length > 25 ? <p>Showing the first 25 of {features.length} rendered features. Narrow the search to see the rest.</p> : null}
      <SelectedItem item={selected} />
    </section>
  </section>;
}
