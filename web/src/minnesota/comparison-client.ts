import { toClientState, transportFailure, type ClientState, type Transport } from "../data/client-state";
import { fetchWithPolicy } from "../data/transport";
import { validateJsonResponse } from "../data/validation";

export interface MinnesotaComparisonProvenance {
  readonly source_id: string;
  readonly artifact_id: string;
  readonly version: string;
  readonly kind: string;
}

export interface MinnesotaComparisonMetric {
  readonly metric_id: string;
  readonly label: string;
  readonly baseline_value: number;
  readonly candidate_value: number;
  /** Server-computed candidate-minus-baseline value. This client never recomputes it. */
  readonly delta_signed: number;
  readonly unit: string;
  readonly provenance: readonly MinnesotaComparisonProvenance[];
}

export interface MinnesotaComparisonResponse {
  readonly status: "ready";
  readonly comparison_id: string;
  readonly baseline: { readonly context_id: string; readonly label: string };
  readonly candidate: { readonly context_id: string; readonly label: string };
  readonly metrics: readonly MinnesotaComparisonMetric[];
  readonly highlight_ids: readonly string[];
  readonly limitations: readonly string[];
}

export interface MinnesotaComparisonRequest {
  readonly baselineContextId: string;
  readonly candidateContextId: string;
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function nonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

function finiteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function isContext(value: unknown): value is MinnesotaComparisonResponse["baseline"] {
  return record(value) && nonEmptyString(value.context_id) && nonEmptyString(value.label);
}

function isProvenance(value: unknown): value is MinnesotaComparisonProvenance {
  return record(value)
    && nonEmptyString(value.source_id)
    && nonEmptyString(value.artifact_id)
    && nonEmptyString(value.version)
    && nonEmptyString(value.kind);
}

function isMetric(value: unknown): value is MinnesotaComparisonMetric {
  return record(value)
    && nonEmptyString(value.metric_id)
    && nonEmptyString(value.label)
    && finiteNumber(value.baseline_value)
    && finiteNumber(value.candidate_value)
    && finiteNumber(value.delta_signed)
    && nonEmptyString(value.unit)
    && Array.isArray(value.provenance)
    && value.provenance.length > 0
    && value.provenance.every(isProvenance);
}

/** Reject incomplete success bodies before any server values are rendered. */
export function isMinnesotaComparisonResponse(value: unknown): value is MinnesotaComparisonResponse {
  return record(value)
    && value.status === "ready"
    && nonEmptyString(value.comparison_id)
    && isContext(value.baseline)
    && isContext(value.candidate)
    && Array.isArray(value.metrics)
    && value.metrics.length > 0
    && value.metrics.every(isMetric)
    && Array.isArray(value.highlight_ids)
    && value.highlight_ids.length > 0
    && value.highlight_ids.every(nonEmptyString)
    && Array.isArray(value.limitations)
    && value.limitations.every(nonEmptyString);
}

/**
 * POST only once: comparison requests use the shared deadline/size policy but
 * are deliberately never retried because POST is not a safe replay operation.
 */
export async function requestMinnesotaComparison(
  request: MinnesotaComparisonRequest,
  transport: Transport = fetchWithPolicy,
): Promise<ClientState<MinnesotaComparisonResponse>> {
  try {
    const response = await transport("/mn/comparisons", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        baseline_context_id: request.baselineContextId,
        candidate_context_id: request.candidateContextId,
      }),
      retries: 0,
      maxResponseBytes: 256 * 1024,
    });
    return toClientState(
      await validateJsonResponse(response, isMinnesotaComparisonResponse),
      () => false,
    );
  } catch (error) {
    return transportFailure(error);
  }
}
