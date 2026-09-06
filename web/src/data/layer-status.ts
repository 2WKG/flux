/**
 * The registry's read path: what each of the six layer classes' data status
 * actually is, asked of the server rather than assumed.
 *
 * The binding rule is `src/scene/minnesota-adapter.ts`: `GET /layers/{name}`
 * serves the Texas `buses` table and is not a Minnesota binding, so every
 * collection it returns is refused by the adapter and the layer stays
 * `unavailable` with the adapter's own named detail. That refusal is a real
 * result of a real request, not a hard-coded shrug: point this at a server
 * that does bind a layer and `adaptLayerToScene` accepts it, at which point
 * the layer reports the status the server asserted.
 *
 * A registry id with no server layer bound to it is `unavailable` with a named
 * reason too. Nothing here reports `available` on the browser's own authority.
 */

import { createReadApiClient, type ClientState, type ReadApiClient } from "./client-state";
import { loadGridLayer, type GridState } from "./grid-client";
import { LAYER_REGISTRY, unreportedLayerReason, type DataStatus, type LayerDefinition } from "../layers/registry";

/**
 * The server layer name each registry class would read, where one exists.
 * `BUILT_LAYERS = frozenset({"buses"})` (`copilot/routes/layers.py:44`) is the
 * only built layer today, so five of the six have no binding at all and say so.
 */
export const SERVER_LAYER_NAMES: Readonly<Record<string, string | undefined>> = {
  topology: "line",
  facilities: "generation",
  provenance: "line",
};

function unboundReason(definition: LayerDefinition): string {
  return `No published physical-inventory artifact is available for the ${definition.label} layer in this release.`;
}

/** Turn one non-ready client state into the layer's data status. */
export function dataStatusForFailure(state: Exclude<ClientState<unknown>, { kind: "ready" }>): DataStatus {
  switch (state.kind) {
    case "unavailable":
      return { kind: "unavailable", reason: state.message };
    case "empty":
      return { kind: "unavailable", reason: "The layer route returned an empty collection." };
    case "loading":
      return { kind: "unavailable", reason: "The layer request has not returned yet." };
    case "invalid":
      return { kind: "request_failed", reason: state.message };
    case "failed":
      return state.requestId === undefined
        ? { kind: "request_failed", reason: state.message }
        : { kind: "request_failed", reason: state.message, requestId: state.requestId };
  }
}

/** Ask the server for one layer and report what came back, or why nothing did. */
export async function loadLayerDataStatus(
  definition: LayerDefinition,
  client: ReadApiClient = createReadApiClient(),
  options: { signal?: AbortSignal; state?: GridState } = {},
): Promise<DataStatus> {
  const name = SERVER_LAYER_NAMES[definition.id];
  if (name === undefined) return { kind: "unavailable", reason: unboundReason(definition) };
  const outcome = await loadGridLayer(
    { state: options.state ?? "mn", layer: name, maxPages: 1, signal: options.signal },
    client,
  );
  if (outcome.kind === "refused") {
    return outcome.status === "unavailable"
      ? { kind: "unavailable", reason: outcome.message }
      : { kind: "request_failed", reason: outcome.message, ...(outcome.requestId === undefined ? {} : { requestId: outcome.requestId }) };
  }
  const items = outcome.pages.flatMap((page) => page.items);
  if (items.length === 0) return { kind: "unavailable", reason: `The ${definition.label} read route returned no published records.` };
  const status = items.every((item) => item.geometry_status === "source") ? "source_supported" : "source_screened";
  return { kind: "available", status };
}

/**
 * Every registry layer's data status, asked in parallel. A layer the walk did
 * not reach at all keeps `unreportedLayerReason`, which is what
 * `buildRegistrySnapshots` would give it.
 */
export async function loadRegistryDataStatuses(
  client: ReadApiClient = createReadApiClient(),
  options: { signal?: AbortSignal; state?: GridState; definitions?: readonly LayerDefinition[] } = {},
): Promise<Record<string, DataStatus>> {
  const definitions = options.definitions ?? LAYER_REGISTRY;
  const entries = await Promise.all(definitions.map(async (definition) => {
    try {
      return [definition.id, await loadLayerDataStatus(definition, client, options)] as const;
    } catch {
      return [definition.id, { kind: "unavailable", reason: unreportedLayerReason(definition) } as DataStatus] as const;
    }
  }));
  return Object.fromEntries(entries);
}
