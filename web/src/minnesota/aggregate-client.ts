import { createReadApiClient, type ClientState, type Transport } from "../data/client-state";

export interface MinnesotaAggregateSource {
  readonly id: string;
  readonly url: string;
  readonly file_sha256: Readonly<Record<string, string>>;
}

export interface MinnesotaAggregateManifest {
  readonly format: string;
  readonly model_mode: "aggregate";
  readonly allocation_status: "unavailable";
  readonly allocation_limit: string;
  readonly sources: readonly MinnesotaAggregateSource[];
}

export interface MinnesotaAggregateStressMetric {
  readonly metric_name: string;
  readonly metric_value: number;
  readonly unit: string;
  readonly formula: string;
  readonly source_label: string;
  readonly time_basis: string;
  readonly window_start_utc: string;
  readonly window_end_utc: string;
  readonly window_peak_demand_mw: number;
  readonly window_peak_hour_utc: string;
  readonly scored_hours: number;
  readonly min_index: number;
  readonly mean_index: number;
  readonly p95_index: number;
}

export interface MinnesotaAggregateProvenance {
  readonly source_name: string;
  readonly source_ref: string;
  readonly source_version: string;
  readonly retrieved_at: string;
  readonly license_or_terms: string;
  readonly source_record_id: string | null;
  readonly content_sha256: string;
  readonly is_derived: boolean;
}

/** The only server result this aggregate-only screen is allowed to render. */
export interface MinnesotaAggregateResponse {
  readonly artifact_id: string;
  readonly model_mode: "aggregate";
  readonly availability: "available";
  readonly aggregate_manifest: MinnesotaAggregateManifest;
  readonly stress_metric: MinnesotaAggregateStressMetric;
  readonly provenance: readonly MinnesotaAggregateProvenance[];
  readonly limitations: readonly string[];
  readonly prohibited_claims: readonly string[];
  readonly base_mva: null;
  readonly solver_version: null;
  readonly converter_version: null;
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function string(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

function finite(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function strings(value: unknown): value is readonly string[] {
  return Array.isArray(value) && value.every(string);
}

function source(value: unknown): value is MinnesotaAggregateSource {
  return record(value)
    && string(value.id)
    && string(value.url)
    && record(value.file_sha256)
    && Object.keys(value.file_sha256).length > 0
    && Object.values(value.file_sha256).every(string);
}

function manifest(value: unknown): value is MinnesotaAggregateManifest {
  return record(value)
    && string(value.format)
    && value.model_mode === "aggregate"
    && value.allocation_status === "unavailable"
    && string(value.allocation_limit)
    && Array.isArray(value.sources)
    && value.sources.length > 0
    && value.sources.every(source);
}

function metric(value: unknown): value is MinnesotaAggregateStressMetric {
  if (!record(value)) return false;
  const stringsPresent = [
    value.metric_name, value.unit, value.formula, value.source_label, value.time_basis,
    value.window_start_utc, value.window_end_utc, value.window_peak_hour_utc,
  ].every(string);
  const numbersPresent = [
    value.metric_value, value.window_peak_demand_mw, value.scored_hours,
    value.min_index, value.mean_index, value.p95_index,
  ].every(finite);
  return stringsPresent && numbersPresent;
}

function provenance(value: unknown): value is MinnesotaAggregateProvenance {
  return record(value)
    && string(value.source_name)
    && string(value.source_ref)
    && string(value.source_version)
    && string(value.retrieved_at)
    && string(value.license_or_terms)
    && (value.source_record_id === null || string(value.source_record_id))
    && string(value.content_sha256)
    && typeof value.is_derived === "boolean";
}

/**
 * Validate the complete server projection before rendering it. The browser
 * accepts neither a topology-shaped response nor a partial aggregate result.
 */
export function isMinnesotaAggregateResponse(value: unknown): value is MinnesotaAggregateResponse {
  return record(value)
    && string(value.artifact_id)
    && value.model_mode === "aggregate"
    && value.availability === "available"
    && manifest(value.aggregate_manifest)
    && metric(value.stress_metric)
    && Array.isArray(value.provenance)
    && value.provenance.length > 0
    && value.provenance.every(provenance)
    && strings(value.limitations)
    && strings(value.prohibited_claims)
    && value.base_mva === null
    && value.solver_version === null
    && value.converter_version === null;
}

/** Read the same-origin persisted aggregate projection. No browser-side calculation occurs. */
export async function requestMinnesotaAggregate(
  transport: Transport | undefined = undefined,
): Promise<ClientState<MinnesotaAggregateResponse>> {
  const client = createReadApiClient(transport);
  return client.get(
    "/minnesota/aggregate",
    isMinnesotaAggregateResponse,
    () => false,
    { timeoutMs: 10_000, maxResponseBytes: 256 * 1024 },
  );
}
