import { deriveSourceTruth, type SourceTruth } from "../source-truth";
import { TEXAS_NODE_ROLES, type NormalizedTexasNode, type TexasAnnotatedBusesLayer, type TexasNodeAdaptation, type TexasNodeCriticalFacility, type TexasNodeDraw, type TexasNodeRole } from "./types";

const REQUIRED_PROVENANCE = ["lon", "lat", "base_kv", "role", "draw_mw", "generation_capacity_mw", "county_name", "ba_code", "critical_loads"] as const;
type Failure = Extract<TexasNodeAdaptation, { kind: "failed" }>;
function record(value: unknown): value is Record<string, unknown> { return typeof value === "object" && value !== null && !Array.isArray(value); }
function number(value: unknown): value is number { return typeof value === "number" && Number.isFinite(value); }
function fail(index: number | null, message: string): Failure { return { kind: "failed", status: "request_failed", message: index === null ? message : `Texas node ${index}: ${message}` }; }
function role(value: unknown): value is TexasNodeRole { return typeof value === "string" && (TEXAS_NODE_ROLES as readonly string[]).includes(value); }
function truthFor(layer: Record<string, unknown>, properties: Record<string, unknown>): SourceTruth {
  const provenance = record(layer.provenance) ? layer.provenance : {};
  const kinds = Array.isArray(provenance.source_kinds) ? provenance.source_kinds : [];
  if (kinds.every((kind) => kind === "fixture") && kinds.length) return { status: "synthetic", sourceKind: "fixture", topology: null };
  if (kinds.every((kind) => kind === "simulated") && kinds.length) return { status: "synthetic", sourceKind: "simulated", topology: typeof provenance.topology === "string" ? provenance.topology as SourceTruth["topology"] : null };
  return deriveSourceTruth({ sourceId: String(properties.source_name ?? ""), sourceRef: String(properties.coord_source ?? "") });
}

/** Validates 428 GeoJSON and copies its annotated values without client-side MW calculation. */
export function adaptTexasNodes(response: unknown): TexasNodeAdaptation {
  if (!record(response) || response.type !== "FeatureCollection" || response.layer !== "buses" || !Array.isArray(response.features)) return fail(null, "Texas node response is not the annotated buses GeoJSON layer.");
  if (typeof response.scenario_id !== "string" || !number(response.hour) || !Number.isInteger(response.hour) || response.hour < 0) return fail(null, "Texas node response has no scenario/hour context.");
  const scenarioId = response.scenario_id;
  const hour = response.hour;
  const nodes: NormalizedTexasNode[] = [];
  for (const [index, feature] of response.features.entries()) {
    if (!record(feature) || typeof feature.id !== "string" || !record(feature.geometry) || feature.geometry.type !== "Point" || !Array.isArray(feature.geometry.coordinates)) return fail(index, "feature geometry is malformed.");
    const [lon, lat] = feature.geometry.coordinates;
    if (!number(lon) || !number(lat) || lon < -180 || lon > 180 || lat < -90 || lat > 90) return fail(index, "coordinates are malformed.");
    if (!record(feature.properties)) return fail(index, "properties are missing.");
    const props = feature.properties;
    if (!role(props.role) || !number(props.base_kv) || props.base_kv <= 0 || !number(props.generation_capacity_mw) || props.generation_capacity_mw < 0) return fail(index, "role, voltage, or capability is malformed.");
    if (props.draw_status !== "available" && props.draw_status !== "unavailable") return fail(index, "draw status is malformed.");
    if ((props.draw_status === "available" && (!number(props.draw_mw) || props.draw_mw < 0)) || (props.draw_status === "unavailable" && props.draw_mw !== null)) return fail(index, "draw value does not match its server status.");
    const fieldProvenance = props.field_provenance;
    if (!record(fieldProvenance) || REQUIRED_PROVENANCE.some((field) => typeof fieldProvenance[field] !== "string")) return fail(index, "per-field provenance is missing.");
    if (!Array.isArray(props.critical_loads) || !props.critical_loads.every((item) => record(item) && (typeof item.id === "string" || typeof item.cl_id === "number") && typeof item.name === "string" && typeof item.kind === "string")) return fail(index, "critical-facility binding is malformed.");
    const criticalFacilities: TexasNodeCriticalFacility[] = props.critical_loads.map((item) => { const bound = item as Record<string, unknown>; return { id: String(bound.id ?? bound.cl_id), name: bound.name as string, kind: bound.kind as string }; });
    const typedFieldProvenance = fieldProvenance as Record<string, string>;
    const draw: TexasNodeDraw = props.draw_status === "available" ? { availability: "available", mw: props.draw_mw as number, scenarioId, hour } : { availability: "unavailable", reason: "ba_hour_unavailable", scenarioId, hour };
    nodes.push({ id: feature.id, name: typeof props.name === "string" ? props.name : null, longitude: lon, latitude: lat, baseKv: props.base_kv, role: props.role, hourDraw: draw, generationCapacityMw: props.generation_capacity_mw, county: typeof props.county_name === "string" ? props.county_name : null, ba: typeof props.ba_code === "string" ? props.ba_code : null, criticalFacilities, fieldProvenance: typedFieldProvenance, truth: truthFor(response, props) });
  }
  return { kind: "ready", nodes };
}
export function typedTexasAnnotatedBusesLayer(response: TexasAnnotatedBusesLayer): TexasAnnotatedBusesLayer { return response; }
