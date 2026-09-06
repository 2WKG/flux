import { SYNTHETIC_TOPOLOGY_LABEL } from "../scene/minnesota-adapter";
import { deriveSourceTruth, type SourceTruth } from "../source-truth";
import {
  BINDING_RECEIPT_TOKENS,
  FIELD_PROVENANCE_TOKENS,
  TEXAS_NODE_ROLES,
  TEXAS_SYNTHETIC_TOPOLOGY_LABEL,
  type NormalizedTexasNode,
  type TexasAnnotatedBusesLayer,
  type TexasFieldProvenanceToken,
  type TexasNodeAdaptation,
  type TexasNodeCriticalFacility,
  type TexasNodeDraw,
  type TexasNodeFieldProvenance,
  type TexasNodeRole,
} from "./types";

const REQUIRED_PROVENANCE = ["lon", "lat", "base_kv", "role", "draw_mw", "generation_capacity_mw", "county_name", "ba_code", "critical_loads"] as const;
type Failure = Extract<TexasNodeAdaptation, { kind: "failed" }>;
function record(value: unknown): value is Record<string, unknown> { return typeof value === "object" && value !== null && !Array.isArray(value); }
function number(value: unknown): value is number { return typeof value === "number" && Number.isFinite(value); }
function fail(index: number | null, message: string): Failure { return { kind: "failed", status: "request_failed", message: index === null ? message : `Texas node ${index}: ${message}` }; }
function role(value: unknown): value is TexasNodeRole { return typeof value === "string" && (TEXAS_NODE_ROLES as readonly string[]).includes(value); }

/**
 * Narrow `field_provenance` before indexing it, and check the values against the
 * producer's own vocabulary rather than accepting any string. `props` arrives as
 * `Record<string, unknown>`, so `props.field_provenance[field]` indexed an
 * `unknown` and failed `tsc` (TS18046) — which took `npm run build`,
 * `test:static-demo` and three CI gates down with it.
 */
function fieldProvenance(value: unknown): TexasNodeFieldProvenance | null {
  if (!record(value)) return null;
  const tokens = FIELD_PROVENANCE_TOKENS as readonly string[];
  for (const field of REQUIRED_PROVENANCE) {
    const label = value[field];
    if (typeof label !== "string" || !tokens.includes(label)) return null;
  }
  return value as TexasNodeFieldProvenance;
}

/**
 * A facility record as `pipelines/node_annotations.py` emits it: the key is
 * `id`, a DuckDB `cl_id BIGINT`, so it is a number. `binding_method` must be one
 * of the producer's own tokens or one of `pipelines/joins.py`'s match methods --
 * an unrecognised value is refused rather than displayed as an attachment claim.
 */
function criticalFacility(value: unknown): TexasNodeCriticalFacility | null {
  if (!record(value)) return null;
  const { id, name, kind, binding_method: method, binding_distance_km: distance } = value;
  if (!number(id) || typeof name !== "string" || typeof kind !== "string") return null;
  if (typeof method !== "string" || method.length === 0) return null;
  if (!(distance === null || distance === undefined || number(distance))) return null;
  return { id, name, kind, bindingMethod: method, bindingDistanceKm: number(distance) ? distance : null };
}

/**
 * The topology token is the one label this repository can assert. An unchecked
 * cast let any server string through and be rendered as a topology claim; a
 * value that is not the asserted token now yields no topology at all.
 */
function assertedTopology(value: unknown): SourceTruth["topology"] {
  return value === SYNTHETIC_TOPOLOGY_LABEL ? SYNTHETIC_TOPOLOGY_LABEL : null;
}

function truthFor(layer: Record<string, unknown>, properties: Record<string, unknown>): SourceTruth {
  const provenance = record(layer.provenance) ? layer.provenance : {};
  const kinds = Array.isArray(provenance.source_kinds) ? provenance.source_kinds : [];
  if (kinds.every((kind) => kind === "fixture") && kinds.length) return { status: "synthetic", sourceKind: "fixture", topology: null };
  if (kinds.every((kind) => kind === "simulated") && kinds.length) {
    // Prefer the per-record topology the annotation carries; fall back to the
    // envelope's. Both are checked against the asserted token.
    return {
      status: "synthetic",
      sourceKind: "simulated",
      topology: assertedTopology(properties.topology) ?? assertedTopology(provenance.topology),
    };
  }
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
    const provenance = fieldProvenance(props.field_provenance);
    if (provenance === null) return fail(index, "per-field provenance is missing.");
    if (!Array.isArray(props.critical_loads)) return fail(index, "critical-facility binding is malformed.");
    const criticalFacilities: TexasNodeCriticalFacility[] = [];
    for (const item of props.critical_loads) {
      const facility = criticalFacility(item);
      if (facility === null) return fail(index, "critical-facility binding is malformed.");
      criticalFacilities.push(facility);
    }
    const draw: TexasNodeDraw = props.draw_status === "available" ? { availability: "available", mw: props.draw_mw as number, scenarioId, hour } : { availability: "unavailable", reason: "ba_hour_unavailable", scenarioId, hour };
    nodes.push({ id: feature.id, name: typeof props.name === "string" ? props.name : null, longitude: lon, latitude: lat, baseKv: props.base_kv, role: props.role, hourDraw: draw, generationCapacityMw: props.generation_capacity_mw, county: typeof props.county_name === "string" ? props.county_name : null, ba: typeof props.ba_code === "string" ? props.ba_code : null, criticalFacilities, fieldProvenance: provenance, truth: truthFor(response, props) });
  }
  return { kind: "ready", nodes };
}

/** The imported vocabulary and the repository's asserted label are one value. */
export function texasTopologyLabel(): string {
  if (TEXAS_SYNTHETIC_TOPOLOGY_LABEL !== SYNTHETIC_TOPOLOGY_LABEL) {
    throw new Error("the generated node-annotations contract and the browser topology label disagree");
  }
  return SYNTHETIC_TOPOLOGY_LABEL;
}

export function typedTexasAnnotatedBusesLayer(response: TexasAnnotatedBusesLayer): TexasAnnotatedBusesLayer { return response; }
export type { TexasFieldProvenanceToken };
