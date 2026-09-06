/**
 * The read seam for the primary simulation scene (2WKG-479).
 *
 * The main route's primary surface is the deck.gl simulation. This module is
 * the only thing that decides what may appear in it, and it is deliberately in
 * `src/data/` rather than in a component: no screen issues a request of its
 * own, and the rules below are properties of a function a test can drive
 * against a real transport.
 *
 * Four rules, each of which is a finding from the reviews of PR #292 / #304:
 *
 * 1. **The request is the merged, versioned route.** Every page comes from
 *    `GET /api/v1/grid/layers/{layer}` through `loadGridInventory`
 *    (`src/data/grid-client.ts`), so the bounded cursor walk, the `bbox`
 *    bounding, the page cap and the disclosed truncation are inherited rather
 *    than re-implemented. `web/server.mjs` already forwards that path.
 * 2. **A node's label is derived, never written.** `deriveSourceTruth` reads
 *    the item's own `provenance.source_id` / `source_ref`, and the words come
 *    from `sourceSummary` / `STATUS_COPY` (`src/source-truth.ts`). Nothing
 *    here spells a status or a topology.
 * 3. **Only the asserted synthetic topology is rendered.** A record whose
 *    provenance does not derive `SYNTHETIC_TOPOLOGY_LABEL` is not drawn in the
 *    simulation and is not relabelled to fit it -- it is counted and disclosed.
 *    That is what makes "every rendered node carries `synthetic (ACTIVSg2000)`"
 *    a property of the code rather than a sentence in a PR body.
 * 4. **No Minnesota topology.** The primary scene reads one state, `tx`, and a
 *    page that comes back carrying any other state is refused by name instead
 *    of being drawn. The five-bus fixture screen and the Minnesota inventory
 *    panel keep their own surfaces; neither is the primary simulation.
 *
 * Every failure is a named refusal carrying the server's own code and message.
 * There is no plausible default and no empty-success anywhere below.
 */

import { deriveSourceTruth, sourceSummary, type SourceTruth } from "../source-truth";
import { SYNTHETIC_TOPOLOGY_LABEL } from "../scene/minnesota-adapter";
import {
  GRID_LAYERS,
  GRID_STATE_BBOX,
  loadGridInventory,
  type GridBbox,
  type GridState,
} from "./grid-client";
import { renderableFeatures, type SpatialItem, type SpatialPage } from "./grid-inventory";
import type { ReadApiClient } from "./client-state";

/**
 * The one state the primary simulation reads. ACTIVSg2000 is a synthetic Texas
 * case (`docs/specs/00-overview.md`), so a Minnesota release can never supply a
 * node for this scene; asking for one would only produce records this module
 * then has to refuse.
 */
export const PRIMARY_SCENE_STATE: GridState = "tx";

/** The layers the primary scene asks for, from the route's own published set. */
export const PRIMARY_SCENE_LAYERS: readonly string[] = GRID_LAYERS[PRIMARY_SCENE_STATE];

/**
 * The extent the primary read is bounded by.
 *
 * It is `GRID_STATE_BBOX`'s Texas entry, imported rather than restated, and it
 * is `null` there **on purpose**: this repository documents no Texas extent, and
 * a plausible-looking rectangle invented in the browser is fabricated geography.
 * `null` sends no `bbox`, which the server reads as the whole release. A caller
 * that does know an extent passes it and every page request carries it.
 */
export const PRIMARY_SCENE_BBOX: GridBbox | null = GRID_STATE_BBOX[PRIMARY_SCENE_STATE];

/** One node of the simulation: a position and the truth its own provenance derives. */
export type PrimarySceneNode = Readonly<{
  /** The server's own asset identifier, verbatim. */
  id: string;
  /** The synthetic topology's own published coordinate pair. Not a map position. */
  position: readonly [number, number];
  /** Derived by `deriveSourceTruth`; its `topology` is always the synthetic label. */
  truth: SourceTruth;
  /** The rendered words, owned by `sourceSummary`/`STATUS_COPY`. */
  label: string;
}>;

export type PrimarySceneRelease = Readonly<{
  artifactId: string;
  artifactVersion: string;
  releaseSha256: string;
}>;

export type PrimarySceneState =
  | Readonly<{ kind: "loading" }>
  | Readonly<{
      kind: "ready";
      nodes: readonly PrimarySceneNode[];
      release: PrimarySceneRelease;
      /** Loaded records that are not synthetic-topology nodes and were not drawn. */
      excluded: number;
      truncated: boolean;
      nextCursor: string | null;
    }>
  | Readonly<{
      kind: "unavailable";
      status: "unavailable" | "request_failed";
      code: string;
      message: string;
      requestId?: string;
    }>;

/** The first [lon, lat] pair inside a GeoJSON coordinate tree, or null. */
function firstPosition(coordinates: unknown): readonly [number, number] | null {
  if (!Array.isArray(coordinates)) return null;
  if (coordinates.length >= 2 && typeof coordinates[0] === "number" && typeof coordinates[1] === "number") {
    return Number.isFinite(coordinates[0]) && Number.isFinite(coordinates[1])
      ? [coordinates[0], coordinates[1]]
      : null;
  }
  for (const entry of coordinates) {
    const position = firstPosition(entry);
    if (position !== null) return position;
  }
  return null;
}

/**
 * The nodes a set of loaded records may contribute to the simulation.
 *
 * A record is a node only when its own provenance derives the synthetic
 * topology label. Everything else -- a source-backed inventory record, a record
 * with no usable geometry -- is left out and counted by `excludedFrom`, never
 * relabelled into the scene.
 */
export function primarySceneNodes(items: readonly SpatialItem[]): readonly PrimarySceneNode[] {
  return renderableFeatures(items).flatMap((feature) => {
    const truth = deriveSourceTruth({
      sourceId: feature.properties.provenance.source_id,
      sourceRef: feature.properties.provenance.source_ref,
    });
    if (truth.topology !== SYNTHETIC_TOPOLOGY_LABEL) return [];
    const position = firstPosition(feature.geometry.coordinates);
    if (position === null) return [];
    return [{ id: feature.id, position, truth, label: sourceSummary(truth) }];
  });
}

/** How many loaded records the scene did not draw. The disclosure's whole point. */
export function excludedFrom(items: readonly SpatialItem[]): number {
  return items.length - primarySceneNodes(items).length;
}

function releaseOf(page: SpatialPage): PrimarySceneRelease {
  return {
    artifactId: page.artifact_id,
    artifactVersion: page.artifact_version,
    releaseSha256: page.release_sha256,
  };
}

export type PrimarySceneRequest = Readonly<{
  state?: GridState;
  layers?: readonly string[];
  bbox?: GridBbox | null;
  signal?: AbortSignal;
}>;

/**
 * Read the primary simulation scene.
 *
 * The walk itself is `loadGridInventory`'s: one bounded, cursor-paged request
 * per layer, each carrying the extent this call supplies, with the first
 * refusal winning over a partial success. What this function adds is rule 3 and
 * rule 4 above, and the named refusals for the two states in which the route
 * answers but the answer contains no simulation.
 */
export async function loadPrimaryScene(
  request: PrimarySceneRequest = {},
  client?: ReadApiClient,
): Promise<PrimarySceneState> {
  const state = request.state ?? PRIMARY_SCENE_STATE;
  const layers = request.layers ?? PRIMARY_SCENE_LAYERS;
  const bbox = request.bbox === undefined ? PRIMARY_SCENE_BBOX : request.bbox;
  const load = await loadGridInventory(
    { state, layers, bbox, ...(request.signal ? { signal: request.signal } : {}) },
    client,
  );
  if (load.kind === "refused") {
    return {
      kind: "unavailable",
      status: load.status,
      code: load.code,
      message: load.message,
      ...(load.requestId === undefined ? {} : { requestId: load.requestId }),
    };
  }
  const foreign = load.pages.find((page) => page.state !== PRIMARY_SCENE_STATE);
  if (foreign !== undefined) {
    return {
      kind: "unavailable",
      status: "request_failed",
      code: "foreign_state_refused",
      message:
        `The layer route answered for state '${foreign.state}'. The primary simulation renders the ` +
        `synthetic topology only and never draws another state's release as the simulation.`,
    };
  }
  const items = load.pages.flatMap((page) => page.items);
  const nodes = primarySceneNodes(items);
  const first = load.pages[0];
  if (first === undefined || nodes.length === 0) {
    return {
      kind: "unavailable",
      status: "unavailable",
      code: "no_synthetic_topology_nodes",
      message:
        `The layer route answered with ${items.length} record${items.length === 1 ? "" : "s"}, none of whose ` +
        `provenance derives the asserted synthetic topology. No node is drawn, and no record is relabelled ` +
        `to fill the scene.`,
    };
  }
  return {
    kind: "ready",
    nodes,
    release: releaseOf(first),
    excluded: items.length - nodes.length,
    truncated: load.truncated,
    nextCursor: load.nextCursor,
  };
}
