/** Adapt an already-bound Minnesota server result into scene inputs, or refuse it.
 *
 * Gate 0 (`docs/design/minnesota-gate-0-approval.md:45-46`) froze what may be
 * rendered: "Topology scenes stay disabled until the `10-minnesota-demo.md`
 * network decision gate accepts a solver-complete source. Aggregate mode is the
 * default and only mode." So this adapter never authorises a topology scene:
 * `allowsTopologyRendering` is false for everything it can currently return.
 *
 * Acceptance is not decided here. `pipelines/minnesota_asset_binding.py`
 * (PR #174) decides it from storage -- `mn_artifact_manifests.availability`
 * and `mn_score_results.regulatory_label` -- and that server binding is
 * authoritative. This file is a pure transform over its output: it preserves
 * the scene id, the coordinates, and the server's status label verbatim, and
 * refuses, by name, anything that does not carry a server binding.
 *
 * `/layers/{name}` is not such a binding. It serves the Texas `buses` table,
 * exposes neither acceptance field, and its `provenance.source_kinds` are only
 * `fixture`, `simulated`, or null (`copilot/routes/layers.py:115-124`). Every
 * `/layers` collection is therefore refused -- malformed ones by their specific
 * reason, well-formed ones as `aggregate_only_no_geometry`.
 *
 * The browser/server boundary in `docs/specs/00-overview.md` applies: this
 * transforms what the server sent and invents nothing.
 */

/** The CRS the layer contract declares; anything else is refused, not reprojected. */
export const REQUIRED_CRS = "EPSG:4326";

/** Server label for the synthetic Texas-shaped case. It is never Minnesota. */
export const SYNTHETIC_TOPOLOGY_LABEL = "synthetic (ACTIVSg2000)";

/**
 * Documented Minnesota extent, copied from `MINNESOTA_BBOX` in
 * `pipelines/minnesota_asset_binding.py` so the browser refuses the same points
 * the server refuses. It is a redundant check, never an acceptance: the server
 * checks against real `mn_geography_artifacts` boundaries first.
 */
export const MINNESOTA_BBOX = [-97.3, 43.4, -89.4, 49.5] as const;

/**
 * The shared `MAT_STATUS` slot vocabulary, verbatim from
 * `data/3d/asset-archetypes-v1.json` `statusMaterials.allowedLabels`. The
 * browser tints from a label the server asserted; it never invents one.
 */
export const STATUS_LABELS = [
  "source_supported",
  "source_screened",
  "hypothetical",
  "synthetic",
  "unavailable",
  "request_failed",
] as const;

export type StatusLabel = (typeof STATUS_LABELS)[number];

/**
 * `mn_score_results.regulatory_label` values the server binding admits as
 * position-worthy (`ACCEPTED_REGULATORY_LABELS` in
 * `pipelines/minnesota_asset_binding.py`). Kept in sync deliberately; a label
 * outside this set is refused here even if a payload claims `render_mode:
 * "placed"`.
 */
export const PLACEABLE_STATUS_LABELS: readonly StatusLabel[] = ["source_supported", "source_screened"];

/** Truth labels Gate 0 froze at artifact level. */
export type TruthLabel = "source_backed" | "synthetic" | "unavailable";

export type RejectionReason =
  | "malformed_collection"
  | "missing_crs"
  | "unsupported_crs"
  | "unlabeled_provenance"
  | "synthetic_topology_not_minnesota"
  | "aggregate_only_no_geometry"
  | "not_server_bound"
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

/** One `render_mode: "placed"` binding from `bind_asset`, carried verbatim. */
export interface BoundPlacement {
  /** `scene_id`, namespaced under its source artifact by the server. */
  readonly id: string;
  readonly sourceArtifactId: string;
  readonly archetypeId: string;
  readonly semanticType: string | null;
  /** [longitude, latitude] in EPSG:4326, exactly as the server bound them. */
  readonly position: readonly [number, number];
  /** The server's `material.status_label`; the browser never supplies one. */
  readonly statusLabel: StatusLabel;
}

export interface AggregateZone {
  readonly id: string;
  readonly name: string | null;
  /**
   * The manifest's own `allocation_status`, carried through. The accepted
   * aggregate manifest says `"unavailable"`, so an unallocated county renders
   * as unavailable, not as source-backed.
   */
  readonly statusLabel: StatusLabel;
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
      /**
       * Reserved for the day the `10-minnesota-demo.md` network decision gate
       * opens. Nothing in this module returns it while Gate 0 holds; it exists
       * so `allowsTopologyRendering` keeps a real, testable discriminant.
       */
      readonly kind: "topology_scene";
      readonly nodes: readonly SceneNode[];
      readonly provenance: SceneProvenance;
    }
  | {
      /** Server-bound points. Placements only -- never lines, towers, or flows. */
      readonly kind: "bound_placements";
      readonly placements: readonly BoundPlacement[];
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

function nonEmptyString(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function isStatusLabel(value: unknown): value is StatusLabel {
  return typeof value === "string" && (STATUS_LABELS as readonly string[]).includes(value);
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
 *
 * `_derive_labels` (`copilot/routes/layers.py:115-124`) can only produce
 * `"fixture"`, `"simulated"`, or `None`, so those are the only kinds recognised
 * here. There is no accept token: no `/layers` provenance asserts acceptance.
 */
function truthLabelOf(provenance: Record<string, unknown>): TruthLabel | null {
  const kinds = stringsOf(provenance.source_kinds);
  if (kinds.length === 0) return null;
  if (kinds.every((kind) => kind === "fixture" || kind === "simulated")) return "synthetic";
  return null;
}

/** Name why a feature cannot be placed, or null when its shape is sound. */
function featureRejection(feature: unknown): RejectionReason | null {
  if (!isRecord(feature)) return "malformed_collection";
  const geometry = feature.geometry;
  if (!isRecord(geometry) || geometry.type !== "Point") return "malformed_collection";
  const coordinates = geometry.coordinates;
  if (!Array.isArray(coordinates) || coordinates.length < 2) return "malformed_collection";
  const [longitude, latitude] = coordinates;
  if (typeof longitude !== "number" || typeof latitude !== "number") return "malformed_collection";
  if (!Number.isFinite(longitude) || !Number.isFinite(latitude)) return "coordinates_out_of_range";
  if (longitude < -180 || longitude > 180 || latitude < -90 || latitude > 90) {
    return "coordinates_out_of_range";
  }
  // A numeric GeoJSON id is legal per RFC 7946; this route emits str(bus_id) by
  // convention, so a non-string id means the payload is not the one documented.
  // Refusing it is deliberate, not an oversight.
  if (nonEmptyString(feature.id) === null) return "malformed_collection";
  return null;
}

/**
 * Refuse one `/layers/{name}` FeatureCollection, by name.
 *
 * `/layers` carries no acceptance field -- no `mn_artifact_manifests.availability`,
 * no `mn_score_results.regulatory_label` -- and serves the Texas `buses` table,
 * so no collection it can emit is drawable Minnesota evidence. Structural faults
 * still get their specific reason so an operator can tell "the server is
 * misbehaving" from "Gate 0 says no": a well-formed, labelled collection is
 * refused `aggregate_only_no_geometry`.
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

  if (truthLabelOf(provenance) === null) {
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

  for (const [index, feature] of features.entries()) {
    const reason = featureRejection(feature);
    if (reason !== null) {
      return reject(reason, `Feature ${index} cannot be placed.`);
    }
  }

  return reject(
    "aggregate_only_no_geometry",
    "A /layers collection asserts no acceptance (no mn_artifact_manifests.availability, " +
      "no mn_score_results.regulatory_label), and Gate 0 keeps topology scenes disabled. " +
      "Use a server binding from pipelines/minnesota_asset_binding.py instead.",
  );
}

/**
 * Adapt the output of `bind_asset` (`pipelines/minnesota_asset_binding.py`)
 * into placements.
 *
 * The server already decided acceptance from storage. This preserves what it
 * decided -- `scene_id`, `coordinates`, `material.status_label` -- and refuses
 * anything that does not carry that decision. It never returns a
 * `topology_scene`: placements are points, and Gate 0 keeps lines, towers, and
 * flows shut.
 *
 * `payload` is `{ layer?, placements: [...] }` where each entry is one
 * `bind_asset` result.
 */
export function adaptBoundPlacements(payload: unknown): SceneAdaptation {
  if (!isRecord(payload)) {
    return reject("malformed_collection", "Payload is not a binding result object.");
  }
  const entries = Array.isArray(payload.placements) ? payload.placements : null;
  if (entries === null) {
    return reject("malformed_collection", "Payload has no placements array.");
  }
  if (entries.length === 0) {
    return reject("no_features", "The binding result names no placements.");
  }

  const placements: BoundPlacement[] = [];
  for (const [index, entry] of entries.entries()) {
    const at = `Placement ${index}`;
    if (!isRecord(entry)) {
      return reject("malformed_collection", `${at} is not an object.`);
    }
    if (entry.render_mode !== "placed") {
      return reject(
        "not_server_bound",
        `${at} has render_mode ${JSON.stringify(entry.render_mode)}; the server bound no geometry for it.`,
      );
    }

    const material = isRecord(entry.material) ? entry.material : null;
    const statusLabel = material === null ? null : material.status_label;
    if (!isStatusLabel(statusLabel)) {
      return reject(
        "unlabeled_provenance",
        `${at} carries no MAT_STATUS material.status_label; the browser may not supply one.`,
      );
    }
    if (!PLACEABLE_STATUS_LABELS.includes(statusLabel)) {
      return reject(
        "not_server_bound",
        `${at} is labelled ${statusLabel}, which is not in the accepted set ` +
          `${PLACEABLE_STATUS_LABELS.join(", ")} and may not position geometry.`,
      );
    }

    const declaredCrs = entry.crs;
    if (declaredCrs === undefined || declaredCrs === null) {
      return reject("missing_crs", `${at} declares no CRS; coordinates cannot be placed.`);
    }
    if (declaredCrs !== REQUIRED_CRS) {
      return reject(
        "unsupported_crs",
        `${at} declares ${JSON.stringify(declaredCrs)}; ${REQUIRED_CRS} is required.`,
      );
    }

    const coordinates = isRecord(entry.coordinates) ? entry.coordinates : null;
    if (coordinates === null) {
      return reject("malformed_collection", `${at} has no coordinates object.`);
    }
    const coordinateCrs = coordinates.crs ?? declaredCrs;
    if (coordinateCrs !== REQUIRED_CRS) {
      return reject(
        "unsupported_crs",
        `${at} declares coordinates in ${JSON.stringify(coordinateCrs)}; ${REQUIRED_CRS} is required.`,
      );
    }
    const { longitude, latitude } = coordinates;
    if (typeof longitude !== "number" || typeof latitude !== "number") {
      return reject("malformed_collection", `${at} has non-numeric coordinates.`);
    }
    if (!Number.isFinite(longitude) || !Number.isFinite(latitude)) {
      return reject("coordinates_out_of_range", `${at} has non-finite coordinates.`);
    }
    const [west, south, east, north] = MINNESOTA_BBOX;
    if (longitude < west || longitude > east || latitude < south || latitude > north) {
      return reject(
        "coordinates_out_of_range",
        `${at} at (${longitude}, ${latitude}) falls outside the documented Minnesota extent.`,
      );
    }

    const sceneId = nonEmptyString(entry.scene_id);
    const sourceArtifactId = nonEmptyString(entry.source_artifact_id);
    const archetypeId = nonEmptyString(entry.archetype_id);
    if (sceneId === null || sourceArtifactId === null || archetypeId === null) {
      return reject(
        "malformed_collection",
        `${at} must carry a non-empty scene_id, source_artifact_id, and archetype_id.`,
      );
    }
    if (!sceneId.startsWith(sourceArtifactId)) {
      return reject(
        "malformed_collection",
        `${at} scene_id ${sceneId} is not namespaced under its source artifact ${sourceArtifactId}.`,
      );
    }

    placements.push({
      id: sceneId,
      sourceArtifactId,
      archetypeId,
      semanticType: typeof entry.semantic_type === "string" ? entry.semantic_type : null,
      position: [longitude, latitude] as const,
      statusLabel,
    });
  }

  return {
    kind: "bound_placements",
    placements,
    provenance: {
      layer: typeof payload.layer === "string" ? payload.layer : "unknown",
      crs: REQUIRED_CRS,
      sourceNames: stringsOf(payload.source_names),
      fixtureBatchIds: stringsOf(payload.fixture_batch_ids),
      topology: null,
    },
  };
}

/**
 * Adapt aggregate-mode coverage into named zones.
 *
 * `coverage` is the aggregate manifest shape
 * (`pipelines/fixtures/inputs/minnesota_aggregate_manifest_v1.json`): a `layer`,
 * a `zones` array, and the manifest's own `allocation_status`. That status is
 * carried through to every zone -- today the manifest says `"unavailable"`, so
 * the zones say `"unavailable"` too. Nothing is relabelled and no boundary,
 * centroid, line, or tower is synthesised: there is no accepted geometry to
 * infer one from.
 */
export function adaptAggregateCoverage(coverage: unknown): SceneAdaptation {
  if (!isRecord(coverage)) {
    return reject("malformed_collection", "Aggregate coverage is not an object.");
  }
  const layer = nonEmptyString(coverage.layer);
  if (layer === null) {
    return reject("malformed_collection", "Aggregate coverage declares no layer name.");
  }
  const rawZones = Array.isArray(coverage.zones) ? coverage.zones : null;
  if (rawZones === null) {
    return reject("malformed_collection", "Aggregate coverage has no zones array.");
  }
  if (rawZones.length === 0) {
    return reject("no_features", "Aggregate coverage names no zones.");
  }

  const zones: AggregateZone[] = [];
  for (const [index, rawZone] of rawZones.entries()) {
    const at = `Zone ${index}`;
    if (!isRecord(rawZone)) {
      return reject("malformed_collection", `${at} is not an object.`);
    }
    const id = nonEmptyString(rawZone.id);
    if (id === null) {
      return reject("malformed_collection", `${at} has no non-empty string id.`);
    }
    const status = rawZone.allocation_status ?? coverage.allocation_status;
    if (!isStatusLabel(status)) {
      return reject(
        "unlabeled_provenance",
        `${at} carries no server allocation_status from the MAT_STATUS vocabulary; ` +
          "the browser may not supply one.",
      );
    }
    zones.push({
      id,
      name: typeof rawZone.name === "string" ? rawZone.name : null,
      statusLabel: status,
    });
  }

  return {
    kind: "aggregate_zones",
    zones,
    provenance: {
      layer,
      crs: REQUIRED_CRS,
      sourceNames: stringsOf(coverage.source_names),
      fixtureBatchIds: stringsOf(coverage.fixture_batch_ids),
      topology: null,
    },
    renderableGeometry: false,
  };
}

/** True when the adaptation may drive a topology scene: lines, towers, flows. */
export function allowsTopologyRendering(adaptation: SceneAdaptation): boolean {
  return adaptation.kind === "topology_scene";
}
