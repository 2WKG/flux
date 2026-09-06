/**
 * The inspector's read path: `GET /scenarios/{scenario_id}`
 * (`copilot/routes/scenarios.py:248`, one unwrapped `ScenarioRow`).
 *
 * The row's persisted provenance is what the panel discloses. The status label
 * is *derived by rule* from that provenance by `src/source-truth.ts`, exactly
 * as the offline shell derives its own — never from the row's `kind`, and never
 * defaulted to something plausible. A route that refuses, a body that does not
 * match the contract, or a transport failure all produce an inspector asset in
 * the matching frozen token with the server's or the transport's own message.
 */

import { createReadApiClient, type ClientState, type ReadApiClient } from "./client-state";
import { deriveSourceTruth } from "../source-truth";
import type { InspectorAsset } from "../inspector/types";

export type ScenarioProvenance = Readonly<{
  source_name: string;
  source_ref: string;
  source_version: string | null;
  source_retrieved_at: string | null;
  fixture_batch_id: string;
  source_kind: "fixture" | "simulated" | null;
  topology: "synthetic (ACTIVSg2000)" | null;
}>;

export type ScenarioRow = Readonly<{
  scenario_id: string;
  name: string;
  kind: "historical" | "forecast" | "synthetic";
  ts_start: string;
  ts_end: string;
  hours: number;
  has_cascade: boolean;
  has_predictions: boolean;
  provenance: ScenarioProvenance;
}>;

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function isScenarioRow(value: unknown): value is ScenarioRow {
  if (!record(value) || !record(value.provenance)) return false;
  const row = value as Record<string, unknown>;
  const provenance = value.provenance as Record<string, unknown>;
  return typeof row.scenario_id === "string" && typeof row.name === "string"
    && (row.kind === "historical" || row.kind === "forecast" || row.kind === "synthetic")
    && typeof row.ts_start === "string" && typeof row.ts_end === "string"
    && typeof row.hours === "number" && typeof row.has_cascade === "boolean"
    && typeof row.has_predictions === "boolean"
    && typeof provenance.source_name === "string" && typeof provenance.source_ref === "string"
    && typeof provenance.fixture_batch_id === "string";
}

/** The scenario row as an inspector asset. Every field comes from the row. */
export function inspectorAssetFor(row: ScenarioRow): InspectorAsset {
  const truth = deriveSourceTruth({ sourceId: row.provenance.source_name, sourceRef: row.provenance.source_ref });
  return {
    id: row.scenario_id,
    name: row.name,
    kind: `${row.kind} scenario`,
    status: truth.status,
    artifactLabel: truth.status,
    scenario: row.scenario_id,
    topology: row.provenance.topology ?? undefined,
    fields: [
      { label: "Hours", value: String(row.hours), unit: "h" },
      { label: "Window start", value: row.ts_start },
      { label: "Window end", value: row.ts_end },
      { label: "Cascade run", value: row.has_cascade ? "Present" : "", status: row.has_cascade ? "available" : "unavailable" },
      { label: "Outage predictions", value: row.has_predictions ? "Present" : "", status: row.has_predictions ? "available" : "unavailable" },
    ],
    provenance: [{
      sourceName: row.provenance.source_name,
      sourceRef: row.provenance.source_ref,
      sourceVersion: row.provenance.source_version ?? undefined,
      retrievedAt: row.provenance.source_retrieved_at ?? undefined,
      coverage: row.provenance.fixture_batch_id,
    }],
  };
}

/** The asset a non-ready client state produces: the frozen token plus its message. */
export function inspectorAssetForFailure(state: Exclude<ClientState<ScenarioRow>, { kind: "ready" }>): InspectorAsset {
  if (state.kind === "loading") {
    return { status: "unavailable", artifactLabel: "unavailable", message: "The scenario request has not returned yet." };
  }
  if (state.kind === "empty") {
    return { status: "unavailable", artifactLabel: "unavailable", message: "The scenario route returned no row for this id." };
  }
  if (state.kind === "unavailable") {
    return { status: "unavailable", artifactLabel: "unavailable", message: state.message };
  }
  // `invalid` and `failed` are both failed requests, not missing artifacts.
  return { status: "request_failed", artifactLabel: "request_failed", message: state.message };
}

export async function loadScenarioAsset(
  scenarioId: string,
  client: ReadApiClient = createReadApiClient(),
  options: { signal?: AbortSignal } = {},
): Promise<InspectorAsset> {
  const state = await client.get<ScenarioRow>(
    `/scenarios/${encodeURIComponent(scenarioId)}`,
    isScenarioRow,
    () => false,
    options.signal ? { signal: options.signal } : {},
  );
  return state.kind === "ready" ? inspectorAssetFor(state.data) : inspectorAssetForFailure(state);
}
