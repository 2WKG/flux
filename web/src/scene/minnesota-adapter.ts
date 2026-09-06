/** Adapt an accepted Minnesota server layer into scene inputs, or refuse it.
 *
 * Gate 0 (`docs/design/minnesota-gate-0-approval.md`) froze what may be
 * rendered: the four accepted artifacts are aggregate-mode metadata, so no
 * Minnesota geometry, topology, or facility coordinates are approved and
 * topology scenes stay disabled. The only `/layers/{name}` collection the
 * server currently builds is `buses`, and it is labelled
 * `synthetic (ACTIVSg2000)` -- Texas-shaped synthetic topology.
 *
 * This adapter therefore spends most of its life saying no, and says it in a
 * named, renderable way. It never repairs, infers, or relabels: a collection
 * without an explicit CRS, without a provenance label, or carrying synthetic
 * topology is rejected rather than drawn, and aggregate coverage yields named
 * zones with no geometry rather than inferred lines, towers, loading, trips,
 * or flows.
 *
 * The browser/server boundary in `docs/specs/00-overview.md` applies: this
 * transforms what the server sent and invents nothing.
 */

/** The CRS the layer contract declares; anything else is refused, not reprojected. */
export const REQUIRED_CRS = "EPSG:4326";

/** Server label for the synthetic Texas-shaped case. It is never Minnesota. */
export const SYNTHETIC_TOPOLOGY_LABEL = "synthetic (ACTIVSg2000)";

/** Truth labels Gate 0 froze at artifact level. */
export type TruthLabel = "source_backed" | "synthetic" | "unavailable";

export type RejectionReason =
  | "malformed_collection"
  | "missing_crs"
  | "unsupported_crs"
  | "unlabeled_provenance"
  | "synthetic_topology_not_minnesota"
  | "aggregate_only_no_geometry"
  | "no_features"
  | "coordinates_out_of_range";

export interface SceneNode {
  /** The server's own identifier, preserved verbatim. */
  readonly id: string;
  readonly name: string | null;
  /** [longitude, latitude] in EPSG:4326, exactly as sent. */
  readonly position: readonly [number, number];
  readonly truthLabel: TruthLabel;
}

export interface AggregateZone {
  readonly id: string;
  readonly name: string | null;
  readonly truthLabel: TruthLabel;
}

export interface SceneProvenance {
  readonly layer: string;
  readonly crs: typeof REQUIRED_CRS;
  readonly sourceNames: readonly string[];
  readonly fixtureBatchIds: readonly string[];
  readonly topology: string | null;
}

export type SceneAdaptation =
  | {
      readonly kind: "topology_scene";
      readonly nodes: readonly SceneNode[];
      readonly provenance: SceneProvenance;
    }
  | {
      /** Named zones only. Carries no geometry, so nothing may be drawn from it. */
      readonly kind: "aggregate_zones";
      readonly zones: readonly AggregateZone[];
      readonly provenance: SceneProvenance;
      readonly renderableGeometry: false;
    }
  | {
      readonly kind: "rejected";
      readonly reason: RejectionReason;
      /** Operator-facing detail. Never rendered as a value. */
      readonly detail: string;
    };

function reject(reason: RejectionReason, detail: string): SceneAdaptation {
  return { kind: "rejected", reason, detail };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function stringsOf(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function crsNameOf(collection: Record<string, unknown>): string | null {
  const crs = collection.crs;
  if (!isRecord(crs)) return null;
  const properties = crs.properties;
  if (!isRecord(properties)) return null;
  return typeof properties.name === "string" ? properties.name : null;
}

/**
 * A label must come from the server. An unlabeled collection is refused rather
 * than defaulted, because the browser inventing a label is exactly what the
 * 00-overview boundary forbids.
 */
function truthLabelOf(provenance: Record<string, unknown>): TruthLabel | null {
  const kinds = stringsOf(provenance.source_kinds);
  if (kinds.length === 0) return null;
  if (kinds.includes("observed") || kinds.includes("source_backed")) return "source_backed";
  if (kinds.every((kind) => kind === "fixture" || kind === "simulated")) return "synthetic";
  return null;
}

function nodeOf(feature: unknown, label: TruthLabel): SceneNode | RejectionReason {
  if (!isRecord(feature)) return "malformed_collection";
  const geometry = feature.geometry;
  const properties = isRecord(feature.properties) ? feature.properties : {};
  if (!isRecord(geometry) || geometry.type !== "Point") return "malformed_collection";
  const coordinates = geometry.coordinates;
  if (!Array.isArray(coordinates) || coordinates.length < 2) return "malformed_collection";
  const [longitude, latitude] = coordinates;
  if (typeof longitude !== "number" || typeof latitude !== "number") return "malformed_collection";
  if (!Number.isFinite(longitude) || !Number.isFinite(latitude)) return "coordinates_out_of_range";
  if (longitude < -180 || longitude > 180 || latitude < -90 || latitude > 90) {
    return "coordinates_out_of_range";
  }
  const id = typeof feature.id === "string" ? feature.id : null;
  if (id === null) return "malformed_collection";
  return {
    id,
    name: typeof properties.name === "string" ? properties.name : null,
    position: [longitude, latitude] as const,
    truthLabel: label,
  };
}

/**
 * Transform one `/layers/{name}` FeatureCollection into scene inputs.
 *
 * Accepts only a collection that declares EPSG:4326, carries a server
 * provenance label, and is not synthetic topology. Everything else is a named
 * rejection the UI can render as an explicit unavailable state.
 */
export function adaptLayerToScene(collection: unknown): SceneAdaptation {
  if (!isRecord(collection) || collection.type !== "FeatureCollection") {
    return reject("malformed_collection", "Payload is not a GeoJSON FeatureCollection.");
  }

  const crsName = crsNameOf(collection);
  if (crsName === null) {
    return reject("missing_crs", "The collection declares no CRS; coordinates cannot be placed.");
  }
  if (crsName !== REQUIRED_CRS) {
    return reject("unsupported_crs", `The collection declares ${crsName}; ${REQUIRED_CRS} is required.`);
  }

  const provenance = isRecord(collection.provenance) ? collection.provenance : null;
  if (provenance === null) {
    return reject("unlabeled_provenance", "The collection carries no provenance block.");
  }

  const topologies = stringsOf(provenance.topologies);
  const topology = typeof provenance.topology === "string" ? provenance.topology : null;
  if (topology === SYNTHETIC_TOPOLOGY_LABEL || topologies.includes(SYNTHETIC_TOPOLOGY_LABEL)) {
    return reject(
      "synthetic_topology_not_minnesota",
      `${SYNTHETIC_TOPOLOGY_LABEL} is Texas-shaped synthetic topology and must not be rendered as Minnesota.`,
    );
  }

  const label = truthLabelOf(provenance);
  if (label === null) {
    return reject(
      "unlabeled_provenance",
      "The collection has no server-asserted source label; the browser may not supply one.",
    );
  }

  const features = Array.isArray(collection.features) ? collection.features : null;
  if (features === null) {
    return reject("malformed_collection", "The collection has no features array.");
  }
  if (features.length === 0) {
    return reject("no_features", "The collection is empty; an empty layer is not a drawable scene.");
  }

  const sceneProvenance: SceneProvenance = {
    layer: typeof collection.layer === "string" ? collection.layer : "unknown",
    crs: REQUIRED_CRS,
    sourceNames: stringsOf(provenance.source_names),
    fixtureBatchIds: stringsOf(provenance.fixture_batch_ids),
    topology,
  };

  const nodes: SceneNode[] = [];
  for (const feature of features) {
    const node = nodeOf(feature, label);
    if (typeof node === "string") {
      return reject(node, `Feature ${nodes.length} cannot be placed.`);
    }
    nodes.push(node);
  }
  return { kind: "topology_scene", nodes, provenance: sceneProvenance };
}

export interface AggregateCoverage {
  readonly layer: string;
  readonly zones: readonly { readonly id: string; readonly name?: string | null }[];
  readonly sourceNames?: readonly string[];
  readonly fixtureBatchIds?: readonly string[];
}

/**
 * Adapt aggregate-mode coverage into named zones.
 *
 * Aggregate coverage has no accepted geometry today, so this returns zones with
 * `renderableGeometry: false` and never synthesises a boundary, centroid, line,
 * or tower for them. A caller that wants to draw must first obtain accepted
 * geometry; there is none to infer from.
 */
export function adaptAggregateCoverage(coverage: AggregateCoverage): SceneAdaptation {
  if (coverage.zones.length === 0) {
    return reject("no_features", "Aggregate coverage names no zones.");
  }
  return {
    kind: "aggregate_zones",
    zones: coverage.zones.map((zone) => ({
      id: zone.id,
      name: zone.name ?? null,
      truthLabel: "source_backed" as const,
    })),
    provenance: {
      layer: coverage.layer,
      crs: REQUIRED_CRS,
      sourceNames: coverage.sourceNames ?? [],
      fixtureBatchIds: coverage.fixtureBatchIds ?? [],
      topology: null,
    },
    renderableGeometry: false,
  };
}

/** True when the adaptation may drive a topology scene: lines, towers, flows. */
export function allowsTopologyRendering(adaptation: SceneAdaptation): boolean {
  return adaptation.kind === "topology_scene";
}
