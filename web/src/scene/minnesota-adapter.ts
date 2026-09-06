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

export type RejectionReason =
  | "malformed_collection"
  | "missing_crs"
  | "unsupported_crs"
  | "unlabeled_provenance"
  | "synthetic_topology_not_minnesota"
  | "aggregate_only_no_geometry"
  | "not_server_bound"
  | "catalog_preview_no_geometry"
  | "no_features"
  | "coordinates_out_of_range";

/** One `render_mode: "placed"` binding from `bind_asset`, carried verbatim. */
export interface BoundPlacement {
  /** `scene_id`, namespaced under its source artifact by the server. */
  readonly id: string;
  readonly sourceArtifactId: string;
  readonly archetypeId: string;
  readonly semanticType: string;
  /** [longitude, latitude] in EPSG:4326, exactly as the server bound them. */
  readonly position: readonly [number, number];
  /** The server's `material.status_label`; the browser never supplies one. */
  readonly statusLabel: StatusLabel;
}

export type SceneAdaptation =
  | {
      /** Server-bound points. Placements only -- never lines, towers, or flows. */
      readonly kind: "bound_placement";
      readonly placement: BoundPlacement;
    }
  | {
      /** The real aggregate manifest. It names no geometry, so nothing is drawn. */
      readonly kind: "aggregate_coverage";
      readonly manifestFormat: "flux-minnesota-aggregate-v1";
      readonly allocationStatus: StatusLabel;
      readonly allocationLimit: string;
      readonly sourceIds: readonly string[];
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
function hasRecognizedLayerProvenance(provenance: Record<string, unknown>): boolean {
  const kinds = stringsOf(provenance.source_kinds);
  return kinds.length > 0 && kinds.every((kind) => kind === "fixture" || kind === "simulated");
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

  if (!hasRecognizedLayerProvenance(provenance)) {
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
 * a topology scene: placements are points, and Gate 0 keeps lines, towers,
 * and flows shut.
 *
 * `binding` is exactly one `bind_asset` result. `bind_from_files` returns one
 * result too; no server endpoint currently emits a batch envelope, so this
 * adapter deliberately does not invent one.
 */
export function adaptBoundPlacement(binding: unknown): SceneAdaptation {
  if (!isRecord(binding)) {
    return reject("malformed_collection", "Payload is not a binding result object.");
  }
  if (binding.render_mode === "catalog_preview") {
    return reject(
      "catalog_preview_no_geometry",
      "The server returned a catalogue preview, which has no Minnesota placement geometry.",
    );
  }
  if (binding.render_mode !== "placed") {
    return reject(
      "not_server_bound",
      `Binding has render_mode ${JSON.stringify(binding.render_mode)}; the server bound no geometry for it.`,
    );
  }

  const material = isRecord(binding.material) ? binding.material : null;
  const statusLabel = material === null ? null : material.status_label;
  if (material === null || material.slot !== "MAT_STATUS" || !isStatusLabel(statusLabel)) {
    return reject(
      "unlabeled_provenance",
      "Binding carries no MAT_STATUS material.status_label; the browser may not supply one.",
    );
  }
  if (!PLACEABLE_STATUS_LABELS.includes(statusLabel)) {
    return reject(
      "not_server_bound",
      `Binding is labelled ${statusLabel}, which is not in the accepted set ` +
        `${PLACEABLE_STATUS_LABELS.join(", ")} and may not position geometry.`,
    );
  }

  if (binding.crs === undefined || binding.crs === null || binding.coordinates === undefined) {
    return reject("missing_crs", "Binding declares no complete CRS contract for its coordinates.");
  }
  if (binding.crs !== REQUIRED_CRS) {
    return reject("unsupported_crs", `Binding declares ${JSON.stringify(binding.crs)}; ${REQUIRED_CRS} is required.`);
  }
  const coordinates = isRecord(binding.coordinates) ? binding.coordinates : null;
  if (coordinates === null) {
    return reject("malformed_collection", "Binding has no coordinates object.");
  }
  if (coordinates.crs === undefined || coordinates.crs === null) {
    return reject("missing_crs", "Binding coordinates declare no CRS.");
  }
  if (coordinates.crs !== REQUIRED_CRS) {
    return reject(
      "unsupported_crs",
      `Binding declares coordinates in ${JSON.stringify(coordinates.crs)}; ${REQUIRED_CRS} is required.`,
    );
  }
  const { longitude, latitude } = coordinates;
  if (typeof longitude !== "number" || typeof latitude !== "number") {
    return reject("malformed_collection", "Binding has non-numeric coordinates.");
  }
  if (!Number.isFinite(longitude) || !Number.isFinite(latitude)) {
    return reject("coordinates_out_of_range", "Binding has non-finite coordinates.");
  }
  const [west, south, east, north] = MINNESOTA_BBOX;
  if (longitude < west || longitude > east || latitude < south || latitude > north) {
    return reject(
      "coordinates_out_of_range",
      `Binding at (${longitude}, ${latitude}) falls outside the documented Minnesota extent.`,
    );
  }

  const sceneId = nonEmptyString(binding.scene_id);
  const sourceArtifactId = nonEmptyString(binding.source_artifact_id);
  const archetypeId = nonEmptyString(binding.archetype_id);
  const semanticType = nonEmptyString(binding.semantic_type);
  if (sceneId === null || sourceArtifactId === null || archetypeId === null || semanticType === null) {
    return reject(
      "malformed_collection",
      "Binding must carry non-empty scene_id, source_artifact_id, archetype_id, and semantic_type fields.",
    );
  }
  if (!sceneId.startsWith(`${sourceArtifactId}:`)) {
    return reject(
      "malformed_collection",
      `Binding scene_id ${sceneId} is not namespaced under its source artifact ${sourceArtifactId}.`,
    );
  }

  return {
    kind: "bound_placement",
    placement: {
      id: sceneId,
      sourceArtifactId,
      archetypeId,
      semanticType,
      position: [longitude, latitude] as const,
      statusLabel,
    },
  };
}

/**
 * Adapt aggregate-mode coverage into named zones.
 *
 * `coverage` is the real aggregate manifest produced by
 * `pipelines/minnesota_aggregate.py`. It has no layer or zones fields: its
 * `allocation_status` means the aggregate evidence may be disclosed, but no
 * geometry exists to draw. Nothing is relabelled and no boundary, centroid,
 * line, or tower is synthesised.
 */
export function adaptAggregateCoverage(coverage: unknown): SceneAdaptation {
  if (!isRecord(coverage)) {
    return reject("malformed_collection", "Aggregate coverage is not an object.");
  }
  if (coverage.format !== "flux-minnesota-aggregate-v1" || coverage.model_mode !== "aggregate") {
    return reject("malformed_collection", "Aggregate coverage does not declare the supported aggregate-manifest contract.");
  }
  const allocationStatus = coverage.allocation_status;
  if (!isStatusLabel(allocationStatus)) {
    return reject(
      "unlabeled_provenance",
      "Aggregate coverage carries no server allocation_status from the MAT_STATUS vocabulary.",
    );
  }
  const allocationLimit = nonEmptyString(coverage.allocation_limit);
  if (allocationLimit === null) {
    return reject("malformed_collection", "Aggregate coverage has no allocation limit.");
  }
  const sources = Array.isArray(coverage.sources) ? coverage.sources : null;
  if (sources === null || sources.length === 0) {
    return reject("malformed_collection", "Aggregate coverage has no source records.");
  }
  const sourceIds: string[] = [];
  for (const source of sources) {
    if (!isRecord(source)) return reject("malformed_collection", "Aggregate coverage has a non-object source record.");
    const sourceId = nonEmptyString(source.id);
    if (sourceId === null) return reject("malformed_collection", "Aggregate coverage has a source record without an id.");
    sourceIds.push(sourceId);
  }

  return {
    kind: "aggregate_coverage",
    manifestFormat: "flux-minnesota-aggregate-v1",
    allocationStatus,
    allocationLimit,
    sourceIds,
    renderableGeometry: false,
  };
}

/**
 * The adaptation kinds that may drive a topology scene: lines, towers, flows.
 *
 * Empty while Gate 0 holds (`docs/design/minnesota-gate-0-approval.md:45-46`),
 * and this list is the seam the `10-minnesota-demo.md` network decision gate
 * would open: a topology variant would join `SceneAdaptation` and its kind
 * would be listed here. Until then nothing this module can return is in the
 * set -- including `bound_placement`, which is one point and only one point,
 * and `aggregate_coverage`, which carries `renderableGeometry: false`.
 *
 * Keeping it a lookup over `kind` rather than a bare `return false` keeps the
 * predicate falsifiable: adding a reachable kind here turns the assertions in
 * `minnesota-adapter.test.mjs` red instead of passing silently.
 */
const TOPOLOGY_RENDERING_KINDS: readonly SceneAdaptation["kind"][] = [];

/** True when the adaptation may drive a topology scene: lines, towers, flows. */
export function allowsTopologyRendering(adaptation: SceneAdaptation): boolean {
  return TOPOLOGY_RENDERING_KINDS.includes(adaptation.kind);
}
