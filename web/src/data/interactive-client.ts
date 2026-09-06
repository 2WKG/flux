/**
 * The browser boundary for the interactive service roots.
 *
 * The response shapes below are **captured, not invented**: they mirror the
 * payloads `scripts/ci/export_interactive_contracts.py` records by running the
 * real producers (`twin/balance.py`, `siting/redundancy.py`) into
 * `src/contracts/interactive-payloads.json`.  Python emits snake_case, so the
 * wire types are snake_case and every camelCase name a panel reads is produced
 * by an explicit adapter in this file — the seam is visible rather than assumed.
 *
 * Panels do not compose URLs, infer a fallback result, or reach into a fixture.
 * A caller receives the same explicit unavailable, malformed, and network states
 * as the existing read client.
 */
import { SYNTHETIC_TOPOLOGY_LABEL } from "../scene/minnesota-adapter";
import {
  type ClientState,
  toClientState,
  transportFailure,
} from "./client-state";
import { fetchWithPolicy, type TransportOptions } from "./transport";
import { type PayloadGuard, validateJsonResponse } from "./validation";

/**
 * The interactive router mounts under `/interactive`, and `siting/search` is a
 * POST.  Both facts were wrong in the first version of this file, so every call
 * 404'd before a guard could run.
 */
export const INTERACTIVE_ROOT_PREFIX = "/interactive";

export const INTERACTIVE_ROOTS = {
  scenarioEdit: `${INTERACTIVE_ROOT_PREFIX}/scenario/edit`,
  cascade: `${INTERACTIVE_ROOT_PREFIX}/cascade`,
  balance: `${INTERACTIVE_ROOT_PREFIX}/balance`,
  redundancy: `${INTERACTIVE_ROOT_PREFIX}/redundancy`,
  sitingSearch: `${INTERACTIVE_ROOT_PREFIX}/siting/search`,
} as const;

export type InteractiveRoot = (typeof INTERACTIVE_ROOTS)[keyof typeof INTERACTIVE_ROOTS];

type JsonPrimitive = string | number | boolean | null;
export type JsonValue = JsonPrimitive | readonly JsonValue[] | { readonly [key: string]: JsonValue };

export interface ScenarioEditRequest {
  readonly scenarioId: string;
  /** The server owns the edit schema; the client carries only JSON-safe input. */
  readonly edits: readonly JsonValue[];
}

export interface CascadeRequest {
  readonly scenarioId: string;
  readonly editHash: string;
}

export interface BalanceRequest {
  readonly scenarioId: string;
  readonly editHash?: string;
  readonly scope?: "state" | "ba" | "county" | "island";
  readonly scopeId?: string;
}

export interface RedundancyRequest {
  readonly busId: string;
}

export interface SitingSearchRequest {
  readonly scenarioId: string;
  readonly editHash?: string;
  readonly query: string;
}

/* -------------------------------------------------------------------------- */
/* Wire shapes — exactly what the Python producers emit.                       */
/* -------------------------------------------------------------------------- */

/** `twin.balance.balance_report` (twin/balance.py). */
export interface BalanceWirePayload {
  readonly edit_hash: string;
  readonly scope: string;
  readonly scope_id: string | number | readonly number[] | null;
  readonly bus_ids: readonly number[];
  readonly draw_mw: number;
  readonly capability_mw: number;
  readonly dispatch_mw: number;
  readonly headroom_mw: number;
  readonly reserve_margin: number | null;
  /** Free text, e.g. `"nameplate; not availability-derated"`. Never an enum. */
  readonly capability_basis: string;
  readonly wind_capability_mw: number;
  readonly solar_capability_mw: number;
  readonly firm_capability_mw: number;
  readonly unclassified_capability_mw: number;
  readonly limitations: readonly string[];
}

/** `siting.redundancy.score_redundancy` (siting/redundancy.py). */
export interface RedundancyWirePayload {
  readonly bus_id: string | number;
  readonly score: number;
  readonly components: {
    readonly n_minus_one_survivability: number;
    readonly edge_disjoint_paths: number;
    readonly edge_disjoint_path_score: number;
    readonly alternative_source_hops: number | null;
    readonly alternative_source_proximity: number;
  };
  readonly worst_contingency: {
    readonly branch_id: string;
    readonly source_reachable: boolean;
    readonly impact: number;
  } | null;
  readonly synthetic_topology: boolean;
  readonly evidence: {
    readonly status: string;
    readonly synthetic_topology: boolean;
    readonly scenario_id: string;
    readonly hour: number;
    readonly branch_selection: string;
    readonly persistence: string;
    readonly cascade: string;
    readonly source_buses: readonly (string | number)[];
    readonly active_branch_count?: number;
    readonly contingencies_evaluated?: number;
    readonly max_contingencies?: number;
    readonly reason?: string;
  };
}

/* -------------------------------------------------------------------------- */
/* View shapes — what a panel renders. Produced only by the adapters below.     */
/* -------------------------------------------------------------------------- */

/**
 * The MW figures a panel shows.  `headroomMw` is the server's own field: a
 * consumer must never recompute it as `capabilityMw - drawMw`, because the
 * server owns the accounting rule, not the browser.
 */
export interface BalanceView {
  readonly editHash: string;
  readonly scope: string;
  readonly scopeId: string | number | readonly number[] | null;
  readonly busIds: readonly number[];
  readonly drawMw: number;
  readonly capabilityMw: number;
  readonly dispatchMw: number;
  readonly headroomMw: number;
  readonly reserveMargin: number | null;
  readonly capabilityBasis: string;
  readonly resourceCapabilityMw: {
    readonly wind: number;
    readonly solar: number;
    readonly firm: number;
    readonly unclassified: number;
  };
  readonly limitations: readonly string[];
}

export interface RedundancyView {
  readonly busId: string;
  readonly score: number;
  readonly components: {
    readonly nMinusOneSurvivability: number;
    readonly edgeDisjointPaths: number;
    readonly edgeDisjointPathScore: number;
    readonly alternativeSourceHops: number | null;
    readonly alternativeSourceProximity: number;
  };
  readonly worstContingency: {
    readonly branchId: string;
    readonly sourceReachable: boolean;
    readonly impact: number;
  } | null;
  /**
   * The rendered topology disclosure.  It is `SYNTHETIC_TOPOLOGY_LABEL` when
   * and only when the server said `synthetic_topology: true`; otherwise the
   * browser has nothing to assert and this is `null`.
   */
  readonly topology: typeof SYNTHETIC_TOPOLOGY_LABEL | null;
  readonly evidence: {
    readonly status: string;
    readonly scenarioId: string;
    readonly hour: number;
    readonly branchSelection: string;
    readonly persistence: string;
    readonly cascade: string;
    readonly sourceBuses: readonly string[];
    readonly activeBranchCount: number | null;
    readonly contingenciesEvaluated: number | null;
    readonly reason: string | null;
  };
}

export interface InteractiveClient {
  editScenario(request: ScenarioEditRequest, options?: TransportOptions): Promise<ClientState<JsonValue>>;
  runCascade(request: CascadeRequest, options?: TransportOptions): Promise<ClientState<JsonValue>>;
  getBalance(request: BalanceRequest, options?: TransportOptions): Promise<ClientState<BalanceView>>;
  getRedundancy(request: RedundancyRequest, options?: TransportOptions): Promise<ClientState<RedundancyView>>;
  searchSiting(request: SitingSearchRequest, options?: TransportOptions): Promise<ClientState<JsonValue>>;
}

export type InteractiveTransport = typeof fetchWithPolicy;

export interface InteractiveClientOptions {
  /** API origin, with no implicit fixture or local-data fallback. */
  readonly baseUrl?: string;
  readonly transport?: InteractiveTransport;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function isStringArray(value: unknown): value is readonly string[] {
  return Array.isArray(value) && value.every(isNonEmptyString);
}

function isNumberArray(value: unknown): value is readonly number[] {
  return Array.isArray(value) && value.every(isFiniteNumber);
}

function isOptionalCount(value: unknown): boolean {
  return value === undefined || isFiniteNumber(value);
}

function isScopeId(value: unknown): value is BalanceWirePayload["scope_id"] {
  return value === null || isNonEmptyString(value) || isFiniteNumber(value) || isNumberArray(value);
}

/**
 * Accept exactly the payload `twin/balance.py` emits.  There is no `evidence`
 * object, no provenance array and no `capability_basis` enum on this route, so
 * requiring any of them rejected every real response.
 */
export const isBalanceWirePayload: PayloadGuard<BalanceWirePayload> = (
  value: unknown,
): value is BalanceWirePayload => {
  if (!isRecord(value)) return false;
  const numbers = [
    "draw_mw", "capability_mw", "dispatch_mw", "headroom_mw",
    "wind_capability_mw", "solar_capability_mw", "firm_capability_mw", "unclassified_capability_mw",
  ] as const;
  return isNonEmptyString(value.edit_hash) && isNonEmptyString(value.scope) &&
    isScopeId(value.scope_id) && isNumberArray(value.bus_ids) &&
    numbers.every((field) => isFiniteNumber(value[field])) &&
    (value.reserve_margin === null || isFiniteNumber(value.reserve_margin)) &&
    isNonEmptyString(value.capability_basis) && isStringArray(value.limitations);
};

/** Accept exactly the payload `siting/redundancy.py` emits. */
export const isRedundancyWirePayload: PayloadGuard<RedundancyWirePayload> = (
  value: unknown,
): value is RedundancyWirePayload => {
  if (!isRecord(value) || !isRecord(value.components) || !isRecord(value.evidence)) return false;
  const { components, evidence } = value;
  const worst = value.worst_contingency;
  return (isNonEmptyString(value.bus_id) || isFiniteNumber(value.bus_id)) &&
    isFiniteNumber(value.score) &&
    isFiniteNumber(components.n_minus_one_survivability) &&
    isFiniteNumber(components.edge_disjoint_paths) &&
    isFiniteNumber(components.edge_disjoint_path_score) &&
    (components.alternative_source_hops === null || isFiniteNumber(components.alternative_source_hops)) &&
    isFiniteNumber(components.alternative_source_proximity) &&
    (worst === null || (isRecord(worst) && isNonEmptyString(worst.branch_id) &&
      typeof worst.source_reachable === "boolean" && isFiniteNumber(worst.impact))) &&
    typeof value.synthetic_topology === "boolean" &&
    typeof evidence.synthetic_topology === "boolean" &&
    isNonEmptyString(evidence.status) && isNonEmptyString(evidence.scenario_id) &&
    isFiniteNumber(evidence.hour) && isNonEmptyString(evidence.branch_selection) &&
    isNonEmptyString(evidence.persistence) && isNonEmptyString(evidence.cascade) &&
    Array.isArray(evidence.source_buses) &&
    evidence.source_buses.every((bus) => isNonEmptyString(bus) || isFiniteNumber(bus)) &&
    isOptionalCount(evidence.active_branch_count) &&
    isOptionalCount(evidence.contingencies_evaluated) &&
    isOptionalCount(evidence.max_contingencies) &&
    (evidence.reason === undefined || isNonEmptyString(evidence.reason));
};

/* -------------------------------------------------------------------------- */
/* Named adapters: snake_case wire -> camelCase view. No value is derived here. */
/* -------------------------------------------------------------------------- */

/** Rename only. Every MW figure below is the server's own field. */
export function toBalanceView(payload: BalanceWirePayload): BalanceView {
  return {
    editHash: payload.edit_hash,
    scope: payload.scope,
    scopeId: payload.scope_id,
    busIds: payload.bus_ids,
    drawMw: payload.draw_mw,
    capabilityMw: payload.capability_mw,
    dispatchMw: payload.dispatch_mw,
    headroomMw: payload.headroom_mw,
    reserveMargin: payload.reserve_margin,
    capabilityBasis: payload.capability_basis,
    resourceCapabilityMw: {
      wind: payload.wind_capability_mw,
      solar: payload.solar_capability_mw,
      firm: payload.firm_capability_mw,
      unclassified: payload.unclassified_capability_mw,
    },
    limitations: payload.limitations,
  };
}

/**
 * Rename, plus the one mapping this boundary owns: the server's
 * `synthetic_topology` boolean becomes the repository's single asserted
 * topology token.  A `false` produces `null`, never a source-supported claim.
 */
export function toRedundancyView(payload: RedundancyWirePayload): RedundancyView {
  const evidence = payload.evidence;
  return {
    busId: String(payload.bus_id),
    score: payload.score,
    components: {
      nMinusOneSurvivability: payload.components.n_minus_one_survivability,
      edgeDisjointPaths: payload.components.edge_disjoint_paths,
      edgeDisjointPathScore: payload.components.edge_disjoint_path_score,
      alternativeSourceHops: payload.components.alternative_source_hops,
      alternativeSourceProximity: payload.components.alternative_source_proximity,
    },
    worstContingency: payload.worst_contingency === null ? null : {
      branchId: payload.worst_contingency.branch_id,
      sourceReachable: payload.worst_contingency.source_reachable,
      impact: payload.worst_contingency.impact,
    },
    topology: evidence.synthetic_topology ? SYNTHETIC_TOPOLOGY_LABEL : null,
    evidence: {
      status: evidence.status,
      scenarioId: evidence.scenario_id,
      hour: evidence.hour,
      branchSelection: evidence.branch_selection,
      persistence: evidence.persistence,
      cascade: evidence.cascade,
      sourceBuses: evidence.source_buses.map(String),
      activeBranchCount: evidence.active_branch_count ?? null,
      contingenciesEvaluated: evidence.contingencies_evaluated ?? null,
      reason: evidence.reason ?? null,
    },
  };
}

function rootUrl(baseUrl: string, root: InteractiveRoot, query?: Readonly<Record<string, string | undefined>>): string {
  const prefix = baseUrl.endsWith("/") ? baseUrl.slice(0, -1) : baseUrl;
  if (!query) return `${prefix}${root}`;
  const entries = Object.entries(query).filter((entry): entry is [string, string] => entry[1] !== undefined);
  if (entries.length === 0) return `${prefix}${root}`;
  return `${prefix}${root}?${new URLSearchParams(entries).toString()}`;
}

async function request<TWire, TView>(
  transport: InteractiveTransport,
  url: string,
  method: "GET" | "POST",
  guard: PayloadGuard<TWire>,
  adapt: (payload: TWire) => TView,
  body: JsonValue | undefined,
  options: TransportOptions,
): Promise<ClientState<TView>> {
  try {
    const response = await transport(url, {
      ...options,
      method,
      headers: body === undefined ? options.headers : { "content-type": "application/json", ...options.headers },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const state = toClientState(await validateJsonResponse(response, guard), () => false);
    return state.kind === "ready" ? { ...state, data: adapt(state.data) } : state;
  } catch (error) {
    return transportFailure(error);
  }
}

/** Later panel payloads remain JSON-only until each route gets its own captured contract. */
const isJsonValue: PayloadGuard<JsonValue> = (value: unknown): value is JsonValue => {
  if (value === null || typeof value === "string" || typeof value === "boolean") return true;
  if (typeof value === "number") return Number.isFinite(value);
  if (Array.isArray(value)) return value.every(isJsonValue);
  return isRecord(value) && Object.values(value).every(isJsonValue);
};

const identity = <T,>(value: T): T => value;

/** Create the only browser HTTP boundary for the interactive panels. */
export function createInteractiveClient({ baseUrl = "", transport = fetchWithPolicy }: InteractiveClientOptions = {}): InteractiveClient {
  return {
    editScenario: (input, options = {}) => request(
      transport, rootUrl(baseUrl, INTERACTIVE_ROOTS.scenarioEdit), "POST", isJsonValue, identity,
      { scenario_id: input.scenarioId, edits: input.edits }, options,
    ),
    runCascade: (input, options = {}) => request(
      transport, rootUrl(baseUrl, INTERACTIVE_ROOTS.cascade), "POST", isJsonValue, identity,
      { scenario_id: input.scenarioId, edit_hash: input.editHash }, options,
    ),
    getBalance: (input, options = {}) => request(
      transport, rootUrl(baseUrl, INTERACTIVE_ROOTS.balance, {
        scenario_id: input.scenarioId,
        edit_hash: input.editHash,
        scope: input.scope,
        scope_id: input.scopeId,
      }), "GET", isBalanceWirePayload, toBalanceView, undefined, options,
    ),
    getRedundancy: (input, options = {}) => request(
      transport, rootUrl(baseUrl, INTERACTIVE_ROOTS.redundancy, {
        bus_id: input.busId,
      }), "GET", isRedundancyWirePayload, toRedundancyView, undefined, options,
    ),
    // The route is a POST; issuing it as a GET 404'd before any guard ran.
    searchSiting: (input, options = {}) => request(
      transport, rootUrl(baseUrl, INTERACTIVE_ROOTS.sitingSearch), "POST", isJsonValue, identity,
      { scenario_id: input.scenarioId, edit_hash: input.editHash ?? null, query: input.query }, options,
    ),
  };
}
