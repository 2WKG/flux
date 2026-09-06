/**
 * The browser boundary for the planned interactive service roots.
 *
 * Each root is intentionally named here before a panel consumes it.  Panels do
 * not compose URLs, infer a fallback result, or reach into a fixture.  Until
 * the service ships, a caller receives the same explicit unavailable, malformed,
 * and network states as the existing read client.
 */
import {
  type ClientState,
  toClientState,
  transportFailure,
} from "./client-state";
import { fetchWithPolicy, type TransportOptions } from "./transport";
import { type PayloadGuard, validateJsonResponse } from "./validation";

export const INTERACTIVE_ROOTS = {
  scenarioEdit: "/scenario/edit",
  cascade: "/cascade",
  balance: "/balance",
  redundancy: "/redundancy",
  sitingSearch: "/siting/search",
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

export interface ProvenanceRecord {
  readonly sourceId: string;
  readonly sourceRef: string;
  readonly version?: string;
}

/** This planned endpoint accepts only synthetic evidence or an explicit unavailable result. */
export type BalanceArtifactTruth = "synthetic" | "unavailable";

export interface BalanceEvidence {
  readonly artifactTruth: BalanceArtifactTruth;
  readonly topology: string | null;
  readonly capabilityBasis: "nameplate" | "availability_adjusted" | "operating";
  readonly provenance: readonly ProvenanceRecord[];
}

export interface BalanceMetricDelta {
  readonly metric: "served_load_mw" | "generation_mw" | "slack_mw" | "residual_mw";
  readonly valueMw: number;
}

/** Strict `/redundancy` payload for a bus-level topology screen. */
export interface RedundancyResponse {
  readonly busId: string;
  readonly score: number;
  readonly components: {
    readonly nMinusOneSurvivability: number;
    readonly edgeDisjointPaths: number;
    readonly alternativeSourceHops: number | null;
  };
  readonly worstContingency: {
    readonly branchId: string;
    readonly sourceReachable: boolean;
  } | null;
  readonly evidence: {
    readonly artifactTruth: BalanceArtifactTruth;
    readonly topology: string | null;
    readonly provenance: readonly ProvenanceRecord[];
  };
  readonly assumptions: readonly string[];
  readonly limitations: readonly string[];
}

/**
 * The future `/balance` success payload.  All displayed MW values are supplied
 * by the service.  In particular, the client must not derive residual from the
 * other fields or use nameplate capability as generation or slack.
 */
export interface BalanceResponse {
  readonly scenarioId: string;
  readonly editHash: string;
  readonly scope: string;
  readonly servedLoadMw: number;
  readonly generationMw: number;
  readonly slackMw: number;
  readonly residualMw: number;
  readonly fuelSplitMw?: Readonly<Record<string, number>>;
  readonly editDelta?: readonly BalanceMetricDelta[];
  readonly evidence: BalanceEvidence;
  readonly assumptions: readonly string[];
  readonly limitations: readonly string[];
}

export interface InteractiveClient {
  editScenario(request: ScenarioEditRequest, options?: TransportOptions): Promise<ClientState<JsonValue>>;
  runCascade(request: CascadeRequest, options?: TransportOptions): Promise<ClientState<JsonValue>>;
  getBalance(request: BalanceRequest, options?: TransportOptions): Promise<ClientState<BalanceResponse>>;
  getRedundancy(request: RedundancyRequest, options?: TransportOptions): Promise<ClientState<RedundancyResponse>>;
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

function isProvenance(value: unknown): value is readonly ProvenanceRecord[] {
  return Array.isArray(value) && value.length > 0 && value.every((item) =>
    isRecord(item) && isNonEmptyString(item.sourceId) && isNonEmptyString(item.sourceRef) &&
      (item.version === undefined || isNonEmptyString(item.version)),
  );
}

function isFuelSplit(value: unknown): value is Readonly<Record<string, number>> {
  return isRecord(value) && Object.keys(value).length > 0 && Object.entries(value).every(
    ([fuel, mw]) => isNonEmptyString(fuel) && isFiniteNumber(mw),
  );
}

function isMetricDelta(value: unknown): value is readonly BalanceMetricDelta[] {
  const metrics = new Set<BalanceMetricDelta["metric"]>([
    "served_load_mw", "generation_mw", "slack_mw", "residual_mw",
  ]);
  return Array.isArray(value) && value.every((item) =>
    isRecord(item) && metrics.has(item.metric as BalanceMetricDelta["metric"]) && isFiniteNumber(item.valueMw),
  );
}

/** Reject missing evidence and ambiguous supply labels before any panel sees data. */
export const isBalanceResponse: PayloadGuard<BalanceResponse> = (value: unknown): value is BalanceResponse => {
  if (!isRecord(value) || !isRecord(value.evidence)) return false;
  const evidence = value.evidence;
  const truth = evidence.artifactTruth;
  const basis = evidence.capabilityBasis;
  if (
    !isNonEmptyString(value.scenarioId) || !isNonEmptyString(value.editHash) || !isNonEmptyString(value.scope) ||
    !isFiniteNumber(value.servedLoadMw) || !isFiniteNumber(value.generationMw) ||
    !isFiniteNumber(value.slackMw) || !isFiniteNumber(value.residualMw) ||
    (value.fuelSplitMw !== undefined && !isFuelSplit(value.fuelSplitMw)) ||
    (value.editDelta !== undefined && !isMetricDelta(value.editDelta)) ||
    !(truth === "synthetic" || truth === "unavailable") ||
    !(evidence.topology === null || isNonEmptyString(evidence.topology)) ||
    !["nameplate", "availability_adjusted", "operating"].includes(String(basis)) ||
    !isProvenance(evidence.provenance) || !isStringArray(value.assumptions) || !isStringArray(value.limitations)
  ) return false;
  return !(truth === "unavailable");
};

/** A numeric redundancy score is usable only when its bus, topology truth, and provenance are explicit. */
export const isRedundancyResponse: PayloadGuard<RedundancyResponse> = (value: unknown): value is RedundancyResponse => {
  if (!isRecord(value) || !isRecord(value.components) || !isRecord(value.evidence)) return false;
  const { components, evidence } = value;
  const worst = value.worstContingency;
  return isNonEmptyString(value.busId) && isFiniteNumber(value.score) &&
    isFiniteNumber(components.nMinusOneSurvivability) && isFiniteNumber(components.edgeDisjointPaths) &&
    (components.alternativeSourceHops === null || isFiniteNumber(components.alternativeSourceHops)) &&
    (worst === null || (isRecord(worst) && isNonEmptyString(worst.branchId) && typeof worst.sourceReachable === "boolean")) &&
    evidence.artifactTruth === "synthetic" &&
    (evidence.topology === null || isNonEmptyString(evidence.topology)) && isProvenance(evidence.provenance) &&
    isStringArray(value.assumptions) && isStringArray(value.limitations);
};

function rootUrl(baseUrl: string, root: InteractiveRoot, query?: Readonly<Record<string, string | undefined>>): string {
  const prefix = baseUrl.endsWith("/") ? baseUrl.slice(0, -1) : baseUrl;
  if (!query) return `${prefix}${root}`;
  const entries = Object.entries(query).filter((entry): entry is [string, string] => entry[1] !== undefined);
  if (entries.length === 0) return `${prefix}${root}`;
  return `${prefix}${root}?${new URLSearchParams(entries).toString()}`;
}

async function request<T>(
  transport: InteractiveTransport,
  url: string,
  method: "GET" | "POST",
  guard: PayloadGuard<T>,
  body: JsonValue | undefined,
  options: TransportOptions,
): Promise<ClientState<T>> {
  try {
    const response = await transport(url, {
      ...options,
      method,
      headers: body === undefined ? options.headers : { "content-type": "application/json", ...options.headers },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    return toClientState(await validateJsonResponse(response, guard), () => false);
  } catch (error) {
    return transportFailure(error);
  }
}

/** Later panel payloads remain JSON-only until each route gets its own strict response contract. */
const isJsonValue: PayloadGuard<JsonValue> = (value: unknown): value is JsonValue => {
  if (value === null || typeof value === "string" || typeof value === "boolean") return true;
  if (typeof value === "number") return Number.isFinite(value);
  if (Array.isArray(value)) return value.every(isJsonValue);
  return isRecord(value) && Object.values(value).every(isJsonValue);
};

/** Create the only browser HTTP boundary for planned interactive panels. */
export function createInteractiveClient({ baseUrl = "", transport = fetchWithPolicy }: InteractiveClientOptions = {}): InteractiveClient {
  return {
    editScenario: (input, options = {}) => request(
      transport, rootUrl(baseUrl, INTERACTIVE_ROOTS.scenarioEdit), "POST", isJsonValue,
      { scenario_id: input.scenarioId, edits: input.edits }, options,
    ),
    runCascade: (input, options = {}) => request(
      transport, rootUrl(baseUrl, INTERACTIVE_ROOTS.cascade), "POST", isJsonValue,
      { scenario_id: input.scenarioId, edit_hash: input.editHash }, options,
    ),
    getBalance: (input, options = {}) => request(
      transport, rootUrl(baseUrl, INTERACTIVE_ROOTS.balance, {
        scenario_id: input.scenarioId,
        edit_hash: input.editHash,
        scope: input.scope,
        scope_id: input.scopeId,
      }), "GET", isBalanceResponse, undefined, options,
    ),
    getRedundancy: (input, options = {}) => request(
      transport, rootUrl(baseUrl, INTERACTIVE_ROOTS.redundancy, {
        bus_id: input.busId,
      }), "GET", isRedundancyResponse, undefined, options,
    ),
    searchSiting: (input, options = {}) => request(
      transport, rootUrl(baseUrl, INTERACTIVE_ROOTS.sitingSearch, {
        scenario_id: input.scenarioId,
        edit_hash: input.editHash,
        query: input.query,
      }), "GET", isJsonValue, undefined, options,
    ),
  };
}
