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
