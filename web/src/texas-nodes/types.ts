import type { SourceTruth } from "../source-truth";
import annotations from "../contracts/node-annotations.json";

/**
 * The role vocabulary, the per-field provenance vocabulary, the binding-receipt
 * tokens and the synthetic topology label are all read from the contract JSON
 * `scripts/ci/export_tool_contracts.py` generates from `pipelines/labels.py`
 * (2WKG-427 / PR #334). They are imported, never restated here, so a vocabulary
 * change on the producer is a typecheck or test failure rather than silent drift.
 */
export const TEXAS_NODE_ROLES = annotations.node_roles;
export type TexasNodeRole = (typeof TEXAS_NODE_ROLES)[number];

export const FIELD_PROVENANCE_TOKENS = annotations.field_provenance_tokens;
export type TexasFieldProvenanceToken = (typeof FIELD_PROVENANCE_TOKENS)[number];

export const TEXAS_SYNTHETIC_TOPOLOGY_LABEL = annotations.synthetic_topology_label;

/** The two receipt states `pipelines/node_annotations.py` can report by name. */
export const BINDING_RECEIPT_TOKENS = [
  annotations.binding_receipt_missing,
  annotations.binding_receipt_absent,
] as const;

export type TexasNodeFieldProvenance = Readonly<Record<string, TexasFieldProvenanceToken>>;
export type TexasNodeDraw =
  | Readonly<{ availability: "available"; mw: number; scenarioId: string; hour: number }>
  | Readonly<{ availability: "unavailable"; reason: "ba_hour_unavailable"; scenarioId: string; hour: number }>;

/**
 * `critical_loads` entries are `{id, name, kind, bus_id, binding_method,
 * binding_distance_km}` and the facility key `id` is the DuckDB `cl_id BIGINT`
 * (`docs/specs/05-copilot.md`, "Each entry of `critical_loads` is ..."), so it
 * arrives as a JSON **number**. The adapter's earlier `cl_id`-or-string guard
 * rejected exactly the record the route emits.
 */
export type TexasNodeCriticalFacility = Readonly<{
  id: number;
  name: string;
  kind: string;
  /** How the facility came to be attached to this bus; never inferred here. */
  bindingMethod: string;
  /** `null` whenever no receipt row describes this exact (cl_id, bus_id) pair. */
  bindingDistanceKm: number | null;
}>;

/** Exact per-feature properties served by 428's annotated buses layer. */
export type TexasAnnotatedBusProperties = Readonly<{
  bus_id: string; name: string | null; base_kv: number; role: TexasNodeRole; generation_capacity_mw: number;
  draw_mw: number | null; draw_status: "available" | "unavailable"; county_name: string | null; ba_code: string | null;
  critical_loads: readonly Readonly<{
    id: number; name: string; kind: string; bus_id: number;
    binding_method: string; binding_distance_km: number | null;
  }>[];
  source_name: string; coord_source: string; topology: string; field_provenance: TexasNodeFieldProvenance;
}>;
export type TexasAnnotatedBusFeature = Readonly<{ type: "Feature"; id: string; geometry: Readonly<{ type: "Point"; coordinates: readonly [number, number] }>; properties: TexasAnnotatedBusProperties }>;
/** Exact 428 `GET /layers/buses?scenario_id=&hour=` response subset consumed here. */
export type TexasAnnotatedBusesLayer = Readonly<{ type: "FeatureCollection"; layer: "buses"; scenario_id: string; hour: number; provenance: Readonly<{ source_kinds: readonly (string | null)[]; topology: string | null; topologies: readonly string[] }>; features: readonly TexasAnnotatedBusFeature[] }>;
export type NormalizedTexasNode = Readonly<{ id: string; name: string | null; longitude: number; latitude: number; baseKv: number; role: TexasNodeRole; hourDraw: TexasNodeDraw; generationCapacityMw: number; county: string | null; ba: string | null; criticalFacilities: readonly TexasNodeCriticalFacility[]; fieldProvenance: TexasNodeFieldProvenance; truth: SourceTruth }>;
export type TexasNodeAdaptation = Readonly<{ kind: "ready"; nodes: readonly NormalizedTexasNode[] }> | Readonly<{ kind: "failed"; status: "unavailable" | "request_failed"; message: string }>;
