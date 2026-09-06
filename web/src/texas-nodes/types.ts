import type { SourceTruth } from "../source-truth";

export const TEXAS_NODE_ROLES = ["producer", "consumer", "both", "transmission"] as const;
export type TexasNodeRole = (typeof TEXAS_NODE_ROLES)[number];
export type TexasNodeFieldProvenance = Readonly<Record<string, string>>;
export type TexasNodeDraw =
  | Readonly<{ availability: "available"; mw: number; scenarioId: string; hour: number }>
  | Readonly<{ availability: "unavailable"; reason: "ba_hour_unavailable"; scenarioId: string; hour: number }>;
export type TexasNodeCriticalFacility = Readonly<{ id: string; name: string; kind: string }>;

/** Exact per-feature properties now served by 428's annotated buses layer. */
export type TexasAnnotatedBusProperties = Readonly<{
  bus_id: string; name: string | null; base_kv: number; role: TexasNodeRole; generation_capacity_mw: number;
  draw_mw: number | null; draw_status: "available" | "unavailable"; county_name: string | null; ba_code: string | null;
  critical_loads: readonly TexasNodeCriticalFacility[]; source_name: string; coord_source: string; field_provenance: TexasNodeFieldProvenance;
}>;
export type TexasAnnotatedBusFeature = Readonly<{ type: "Feature"; id: string; geometry: Readonly<{ type: "Point"; coordinates: readonly [number, number] }>; properties: TexasAnnotatedBusProperties }>;
/** Exact 428 `GET /layers/buses?scenario_id=&hour=` response subset consumed here. */
export type TexasAnnotatedBusesLayer = Readonly<{ type: "FeatureCollection"; layer: "buses"; scenario_id: string; hour: number; provenance: Readonly<{ source_kinds: readonly (string | null)[]; topology: string | null; topologies: readonly string[] }>; features: readonly TexasAnnotatedBusFeature[] }>;
export type NormalizedTexasNode = Readonly<{ id: string; name: string | null; longitude: number; latitude: number; baseKv: number; role: TexasNodeRole; hourDraw: TexasNodeDraw; generationCapacityMw: number; county: string | null; ba: string | null; criticalFacilities: readonly TexasNodeCriticalFacility[]; fieldProvenance: TexasNodeFieldProvenance; truth: SourceTruth }>;
export type TexasNodeAdaptation = Readonly<{ kind: "ready"; nodes: readonly NormalizedTexasNode[] }> | Readonly<{ kind: "failed"; status: "unavailable" | "request_failed"; message: string }>;
