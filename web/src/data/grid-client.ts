/**
 * The read path for the physical-inventory layers, on the shared transport.
 *
 * Three rules, all of them findings from PR #245's review:
 *
 * 1. **The page walk is bounded.** #245 looped `do … while (cursor)` with no
 *    cap and re-ran it on every `onMoveEnd`; with the measured page timings
 *    that is a minute or more to first paint, repeated on every pan. Here the
 *    walk stops at `MAX_PAGES` and the truncation is *disclosed* rather than
 *    hidden: `truncated: true` with the cursor the walk stopped on.
 * 2. **The viewport bounds the request.** `bbox` is sent to the server; the
 *    browser never downloads a state and filters locally.
 * 3. **The server's own refusal survives.** Anything that is not a valid page
 *    becomes an `unavailable`/`request_failed` outcome carrying the server's
 *    code and message, or the transport's own named reason. No sentence is
 *    invented here.
 */

import { createReadApiClient, type ClientState, type ReadApiClient } from "./client-state";
import { isSpatialFailure, pageFrom, type SpatialFailure, type SpatialPage } from "./grid-inventory";
import { MINNESOTA_BBOX } from "../scene/minnesota-adapter";

/** The layers each state's release publishes. */
export const GRID_LAYERS = {
  tx: ["line", "generation", "storage"],
  mn: ["line", "substation", "generation", "storage"],
} as const;

export type GridState = keyof typeof GRID_LAYERS;

/** The release the browser asks for. A server that has no such release refuses by name. */
export const GRID_ARTIFACT_VERSION = "1.1.0";
export const GRID_PAGE_LIMIT = 100;
/** At most this many pages per layer per view. A truncated walk is disclosed, not hidden. */
export const MAX_PAGES = 8;

export type GridBbox = readonly [number, number, number, number];

export type GridLayerRequest = {
  readonly state: GridState;
  readonly layer: string;
  readonly bbox?: GridBbox | null;
  readonly maxPages?: number;
  readonly signal?: AbortSignal;
};

/**
 * The bounding box each state's reads are bounded by, so rule 2 above is a
 * property of the shipped call site and not only of `gridLayerUrl`.
 *
 * Minnesota's is the documented extent already carried by
 * `../scene/minnesota-adapter.ts` (itself copied from `MINNESOTA_BBOX` in
 * `pipelines/minnesota_asset_binding.py`) -- imported, never restated. Texas is
 * `null` **on purpose**: this repository documents no Texas extent anywhere, and
 * a plausible-looking rectangle invented in the browser is exactly the kind of
 * fabricated geography the layer contract forbids. `null` sends no `bbox`, which
 * the server reads as the whole release, and that is the truth of the request.
 */
export const GRID_STATE_BBOX: Readonly<Record<GridState, GridBbox | null>> = {
  mn: MINNESOTA_BBOX,
  tx: null,
};

/**
 * The requests one view issues: one per layer, each bounded by an extent.
 *
 * The extent defaults to the state's documented one (`GRID_STATE_BBOX`). A
 * caller that knows a narrower extent -- a viewport, say -- passes it as
 * `bbox` and every page request in the walk carries it, so rule 2 above holds
 * for that call site too. Passing `null` explicitly means "no extent", which is
 * the truth of the request rather than an invented rectangle.
 */
export function gridLayerRequestsFor(
  state: GridState,
  layers: readonly string[],
  signal?: AbortSignal,
  bbox: GridBbox | null = GRID_STATE_BBOX[state],
): readonly GridLayerRequest[] {
  return layers.map((layer) => ({ state, layer, bbox, signal }));
}

export type GridLayerOutcome =
  | { readonly kind: "loaded"; readonly pages: readonly SpatialPage[]; readonly truncated: boolean; readonly nextCursor: string | null }
  | { readonly kind: "refused"; readonly status: "unavailable" | "request_failed"; readonly code: string; readonly message: string; readonly requestId?: string };

export function gridLayerUrl(request: GridLayerRequest, cursor: string | null): string {
  const query = new URLSearchParams({
    state: request.state,
    version: GRID_ARTIFACT_VERSION,
    limit: String(GRID_PAGE_LIMIT),
  });
  if (cursor !== null) query.set("cursor", cursor);
  if (request.bbox) query.set("bbox", request.bbox.join(","));
  return `/api/v1/grid/layers/${encodeURIComponent(request.layer)}?${query.toString()}`;
}

/** A parsed page or failure envelope; anything else is not this contract. */
const isGridBody = (value: unknown): value is SpatialPage | SpatialFailure => pageFrom(value) !== null;

function refusalFrom(failure: SpatialFailure): GridLayerOutcome {
  return {
    kind: "refused",
    // `unavailable` is a missing artifact; every other envelope status is a failed request.
    status: failure.status === "unavailable" ? "unavailable" : "request_failed",
    code: failure.error.code,
    message: failure.error.message,
    ...(failure.error.requestId === undefined ? {} : { requestId: failure.error.requestId }),
  };
}

function refusalFromClientState(state: Exclude<ClientState<unknown>, { kind: "ready" }>): GridLayerOutcome {
  switch (state.kind) {
    case "unavailable":
      return { kind: "refused", status: "unavailable", code: "unavailable", message: state.message, requestId: state.requestId };
    case "invalid":
      return { kind: "refused", status: "request_failed", code: state.reason, message: state.message };
    case "failed":
      return {
        kind: "refused",
        status: "request_failed",
        code: state.reason ?? "unreachable",
        message: state.message,
        ...(state.requestId === undefined ? {} : { requestId: state.requestId }),
      };
    case "empty":
      return { kind: "refused", status: "unavailable", code: "empty_response", message: "The inventory service returned no body for this layer." };
    case "loading":
      return { kind: "refused", status: "unavailable", code: "loading", message: "The inventory request has not returned yet." };
  }
}

/**
 * Walk one layer's pages, bounded. Stops at the first refusal and returns it;
 * a partial walk that hit the page cap is returned as `truncated`.
 */
export async function loadGridLayer(
  request: GridLayerRequest,
  client: ReadApiClient = createReadApiClient(),
): Promise<GridLayerOutcome> {
  const maxPages = Math.max(1, request.maxPages ?? MAX_PAGES);
  const pages: SpatialPage[] = [];
  let cursor: string | null = null;
  for (let index = 0; index < maxPages; index += 1) {
    const state: ClientState<SpatialPage | SpatialFailure> = await client.get(
      gridLayerUrl(request, cursor),
      isGridBody,
      () => false,
      request.signal ? { signal: request.signal } : {},
    );
    if (state.kind !== "ready") return refusalFromClientState(state);
    if (isSpatialFailure(state.data)) return refusalFrom(state.data);
    pages.push(state.data);
    cursor = state.data.page.next_cursor;
    if (cursor === null) return { kind: "loaded", pages, truncated: false, nextCursor: null };
  }
  return { kind: "loaded", pages, truncated: true, nextCursor: cursor };
}

/** What one view's read resolves to: still loading is the caller's own state, not an outcome. */
export type GridInventoryLoad =
  | { readonly kind: "loaded"; readonly pages: readonly SpatialPage[]; readonly truncated: boolean; readonly nextCursor: string | null }
  | { readonly kind: "refused"; readonly status: "unavailable" | "request_failed"; readonly code: string; readonly message: string; readonly requestId?: string };

/**
 * One view's whole read: every requested layer, each bounded by its state's
 * extent (`gridLayerRequestsFor`), combined into the single load the panel
 * renders. The first refusal wins -- a partial success is not reported as a
 * success -- and truncation from any layer is carried through, never dropped.
 *
 * This exists so the page's grid effect is one call rather than a hand-rolled
 * `Promise.all` in the component: the bbox-bounding and the refusal-wins rule
 * are then properties of a function a test can drive against a real transport.
 */
export async function loadGridInventory(
  request: {
    readonly state: GridState;
    readonly layers: readonly string[];
    readonly signal?: AbortSignal;
    /** An explicit extent for this read; omitted means the state's documented one. */
    readonly bbox?: GridBbox | null;
  },
  client: ReadApiClient = createReadApiClient(),
): Promise<GridInventoryLoad> {
  const bbox = request.bbox === undefined ? GRID_STATE_BBOX[request.state] : request.bbox;
  const outcomes = await Promise.all(
    gridLayerRequestsFor(request.state, request.layers, request.signal, bbox).map((each) => loadGridLayer(each, client)),
  );
  const refused = outcomes.find((outcome) => outcome.kind === "refused");
  if (refused && refused.kind === "refused") return refused;
  const pages = outcomes.flatMap((outcome) => (outcome.kind === "loaded" ? outcome.pages : []));
  return {
    kind: "loaded",
    pages,
    truncated: outcomes.some((outcome) => outcome.kind === "loaded" && outcome.truncated),
    nextCursor: outcomes.flatMap((outcome) => (outcome.kind === "loaded" && outcome.nextCursor ? [outcome.nextCursor] : []))[0] ?? null,
  };
}
