/**
 * The read seam for the primary simulation scene (2WKG-479).
 *
 * The main route's primary surface is the deck.gl simulation. This module is
 * the only thing that decides what may appear in it, and it is deliberately in
 * `src/data/` rather than in a component: no screen issues a request of its
 * own, and the rules below are properties of a function a test can drive
 * against a real transport.
 *
 * **Why `/demo/model` and not the layer route.** The first cut of this seam
 * read `GET /api/v1/grid/layers/{layer}`. That route serves the *source-backed*
 * Texas physical inventory (`eia860_2025er`, `hifld-lines-2024-09-30`); not one
 * of its 11 949 assets derives `synthetic (ACTIVSg2000)`, so the topology rule
 * below dropped every record and the scene refused with
 * `no_synthetic_topology_nodes` against a real server — the label guarantee was
 * true only because nothing was ever drawn. The synthetic ACTIVSg2000 topology
 * is served by `GET /demo/model` (`copilot/routes/model_geometry.py`), whose
 * committed release carries 6 875 elements each with its own
 * `provenance.topology`. This seam reads that route, and
 * `test/primary-scene.test.mjs` drives it against the **committed release file**
 * so the non-vacuity of the label rule is itself asserted.
 *
 * Four rules:
 *
 * 1. **The request is the published read-only model route**, `/demo/model`,
 *    through the shared `ReadApiClient`. `web/server.mjs` forwards that exact
 *    path (`PROXIED`), and no component issues it.
 * 2. **A node's label is derived, never written.** `deriveSourceTruth` reads the
 *    element's own `source_id` and `provenance.topology`, and the words come
 *    from `sourceSummary` / `STATUS_COPY` (`src/source-truth.ts`). Nothing here
 *    spells a status or a topology.
 * 3. **Only the asserted synthetic topology is rendered.** An element whose own
 *    provenance does not derive `SYNTHETIC_TOPOLOGY_LABEL` is not drawn and is
 *    not relabelled to fit it -- it is counted and disclosed. That is what makes
 *    "every rendered node carries `synthetic (ACTIVSg2000)`" a property of the
 *    code rather than a sentence in a PR body.
 * 4. **The release's own declared topology must be the asserted one.** A payload
 *    that declares some other topology is refused by name
 *    (`foreign_topology_refused`) instead of being drawn, so another release
 *    cannot be promoted into this scene.
 *
 * Every failure is a named refusal carrying the server's own code and message.
 * There is no plausible default and no empty-success anywhere below.
 */

import { deriveSourceTruth, sourceSummary, type SourceTruth } from "../source-truth";
import { SYNTHETIC_TOPOLOGY_LABEL } from "../scene/minnesota-adapter";
import { createReadApiClient, type ClientState, type ReadApiClient } from "./client-state";

/** The one path the primary simulation reads. `web/server.mjs` forwards it. */
export const PRIMARY_SCENE_PATH = "/demo/model";

/** One node of the simulation: a position and the truth its own provenance derives. */
export type PrimarySceneNode = Readonly<{
  /** The server's own element identifier, verbatim. */
  id: string;
  /** The synthetic topology's own published coordinate pair. Not a map position. */
  position: readonly [number, number];
  /** Derived by `deriveSourceTruth`; its `topology` is always the synthetic label. */
  truth: SourceTruth;
  /** The rendered words, owned by `sourceSummary`/`STATUS_COPY`. */
  label: string;
}>;

/** What the release declares about itself, verbatim. Nothing here is inferred. */
export type PrimarySceneTopology = Readonly<{
  label: string;
  modelMode: string | null;
  solver: string | null;
  coordinateSource: string | null;
  declaredBuses: number | null;
  declaredBranches: number | null;
}>;

export type PrimarySceneState =
  | Readonly<{ kind: "loading" }>
  | Readonly<{
      kind: "ready";
      nodes: readonly PrimarySceneNode[];
      topology: PrimarySceneTopology;
      /** Loaded elements the scene did not draw as nodes. */
      excluded: number;
      /** Of those, the ones whose provenance does not derive the synthetic topology. */
      refusedTopology: number;
    }>
  | Readonly<{
      kind: "unavailable";
      status: "unavailable" | "request_failed";
      code: string;
      message: string;
      requestId?: string;
    }>;

/** One element of the `/demo/model` payload, as the route publishes it. */
export type ModelElement = Readonly<{
  element_id?: unknown;
  resolved?: unknown;
  role?: unknown;
  source_id?: unknown;
  geometry?: Readonly<{ type?: unknown; coordinates?: unknown }>;
  provenance?: Readonly<{ topology?: unknown; coordinate_source?: unknown }>;
}>;

export type ModelPayload = Readonly<{
  status: string;
  reason?: unknown;
  data?: Readonly<{
    topology?: Readonly<{ label?: unknown; model_mode?: unknown; solver?: unknown }>;
    counts?: Readonly<{ buses?: unknown; branches?: unknown }>;
    provenance?: Readonly<{ coordinate_source?: unknown }>;
    elements?: unknown;
  }>;
}>;

/** The route's envelope, and nothing else. Shape only; content is judged below. */
export function isModelPayload(value: unknown): value is ModelPayload {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as { status?: unknown }).status === "string"
  );
}

const text = (value: unknown): string | null => (typeof value === "string" ? value : null);
const count = (value: unknown): number | null =>
  typeof value === "number" && Number.isInteger(value) && value >= 0 ? value : null;

/** The [lon, lat] pair of a Point element, or null for anything that is not one. */
function pointPosition(geometry: ModelElement["geometry"]): readonly [number, number] | null {
  if (geometry?.type !== "Point" || !Array.isArray(geometry.coordinates)) return null;
  const [lon, lat] = geometry.coordinates;
  return typeof lon === "number" && typeof lat === "number" && Number.isFinite(lon) && Number.isFinite(lat)
    ? [lon, lat]
    : null;
}

export function modelElements(payload: ModelPayload): readonly ModelElement[] {
  const elements = payload.data?.elements;
  return Array.isArray(elements) ? (elements as readonly ModelElement[]) : [];
}

/**
 * The nodes a set of loaded elements may contribute to the simulation.
 *
 * An element is a node only when its own provenance derives the synthetic
 * topology label. Everything else -- an unresolved element, an element whose
 * provenance asserts some other topology -- is left out and counted, never
 * relabelled into the scene. Branches carry a LineString rather than a node
 * position and are not nodes either; `excludedFrom` counts them too, and the
 * panel discloses both numbers separately.
 */
export function primarySceneNodes(elements: readonly ModelElement[]): readonly PrimarySceneNode[] {
  return elements.flatMap((element) => {
    const id = text(element.element_id);
    if (id === null || element.resolved !== true) return [];
    const truth = deriveSourceTruth({
      sourceId: text(element.source_id) ?? id,
      sourceRef: text(element.provenance?.topology) ?? "",
    });
    if (truth.topology !== SYNTHETIC_TOPOLOGY_LABEL) return [];
    const position = pointPosition(element.geometry);
    if (position === null) return [];
    return [{ id, position, truth, label: sourceSummary(truth) }];
  });
}

/** How many loaded elements the scene did not draw. The disclosure's whole point. */
export function excludedFrom(elements: readonly ModelElement[]): number {
  return elements.length - primarySceneNodes(elements).length;
}

/** How many loaded elements do not derive the asserted synthetic topology at all. */
export function refusedTopologyIn(elements: readonly ModelElement[]): number {
  return elements.filter((element) => {
    const id = text(element.element_id);
    if (id === null || element.resolved !== true) return false;
    const truth = deriveSourceTruth({
      sourceId: text(element.source_id) ?? id,
      sourceRef: text(element.provenance?.topology) ?? "",
    });
    return truth.topology !== SYNTHETIC_TOPOLOGY_LABEL;
  }).length;
}

function topologyOf(payload: ModelPayload): PrimarySceneTopology | null {
  const label = text(payload.data?.topology?.label);
  if (label === null) return null;
  return {
    label,
    modelMode: text(payload.data?.topology?.model_mode),
    solver: text(payload.data?.topology?.solver),
    coordinateSource: text(payload.data?.provenance?.coordinate_source),
    declaredBuses: count(payload.data?.counts?.buses),
    declaredBranches: count(payload.data?.counts?.branches),
  };
}

function refusalFromClientState(
  state: Exclude<ClientState<unknown>, { kind: "ready" }>,
): PrimarySceneState {
  switch (state.kind) {
    case "unavailable":
      return { kind: "unavailable", status: "unavailable", code: "unavailable", message: state.message, requestId: state.requestId };
    case "invalid":
      return { kind: "unavailable", status: "request_failed", code: state.reason, message: state.message };
    case "failed":
      return {
        kind: "unavailable",
        status: "request_failed",
        code: state.reason ?? "unreachable",
        message: state.message,
        ...(state.requestId === undefined ? {} : { requestId: state.requestId }),
      };
    case "empty":
      return { kind: "unavailable", status: "unavailable", code: "empty_response", message: "The model route returned no body." };
    case "loading":
      return { kind: "unavailable", status: "unavailable", code: "loading", message: "The model request has not returned yet." };
  }
}

export type PrimarySceneRequest = Readonly<{ signal?: AbortSignal }>;

const DEFAULT_CLIENT: ReadApiClient = createReadApiClient();

/**
 * Read the primary simulation scene from `/demo/model`.
 *
 * The transport, the response validation and the failure vocabulary are the
 * shared `ReadApiClient`'s. What this function adds is rules 3 and 4 above, and
 * the named refusals for the states in which the route answers but the answer
 * contains no simulation.
 */
export async function loadPrimaryScene(
  request: PrimarySceneRequest = {},
  client: ReadApiClient = DEFAULT_CLIENT,
): Promise<PrimarySceneState> {
  const state: ClientState<ModelPayload> = await client.get<ModelPayload>(
    PRIMARY_SCENE_PATH,
    isModelPayload,
    () => false,
    { retries: 0, ...(request.signal ? { signal: request.signal } : {}) },
  );
  if (state.kind !== "ready") return refusalFromClientState(state);
  const payload = state.data;
  if (payload.status !== "available" && payload.status !== "partial") {
    return {
      kind: "unavailable",
      status: "unavailable",
      code: "model_route_unavailable",
      message:
        text(payload.reason) ??
        `The model route answered '${payload.status}' and supplied no resolved topology. No node is drawn.`,
    };
  }
  const topology = topologyOf(payload);
  if (topology === null || topology.label !== SYNTHETIC_TOPOLOGY_LABEL) {
    return {
      kind: "unavailable",
      status: "request_failed",
      code: "foreign_topology_refused",
      message:
        `The model route answered with topology '${topology?.label ?? "none declared"}'. The primary ` +
        `simulation renders the asserted synthetic topology only and never draws another release as ` +
        `the simulation.`,
    };
  }
  const elements = modelElements(payload);
  const nodes = primarySceneNodes(elements);
  if (nodes.length === 0) {
    return {
      kind: "unavailable",
      status: "unavailable",
      code: "no_synthetic_topology_nodes",
      message:
        `The model route answered with ${elements.length} element${elements.length === 1 ? "" : "s"}, none of ` +
        `which is a resolved node whose own provenance derives the asserted synthetic topology. No node is ` +
        `drawn, and no element is relabelled to fill the scene.`,
    };
  }
  return {
    kind: "ready",
    nodes,
    topology,
    excluded: elements.length - nodes.length,
    refusedTopology: refusedTopologyIn(elements),
  };
}
