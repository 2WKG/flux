/**
 * The browser boundary for the versioned physical-inventory read route
 * (`GET /api/v1/grid/layers/{layer}`, 2WKG-89 / PR #244).
 *
 * Salvaged from PR #245's `web/src/renderer/spatial-scene.ts` and moved under
 * `src/data/` because it is a response contract, not a renderer concern. Two
 * things changed in the move, both from #245's review:
 *
 * 1. A failure is recognised on **either** envelope status. `copilot/api/envelope.py`
 *    declares `ResponseStatus = Literal["unavailable", "error"]` and
 *    `copilot/api/errors.py` sends `status: "error"` for `invalid_input` (422),
 *    `not_found` (404) and `internal_error` (500). Recognising only
 *    `"unavailable"` discarded those three and replaced the server's named
 *    reason with a client-invented sentence.
 * 2. `coverage` rows are validated here instead of in the component, so a
 *    malformed disclosure is a rejected page rather than a silently short list.
 *
 * `display_geometry` is the only geometry consumed. It is server-produced
 * WGS84; native geometry stays source evidence and is never projected here.
 */

export type GeoJsonGeometry = Readonly<{ type: string; coordinates: unknown }>;

export type SpatialItem = Readonly<{
  asset_id: string;
  asset_class: string;
  asset_kind: string;
  availability: "available" | "unavailable";
  display_geometry: GeoJsonGeometry | null;
  display_crs: "EPSG:4326" | null;
  native_geometry: GeoJsonGeometry | null;
  native_crs: string | null;
  geometry_status: "source" | "derived" | "unavailable";
  geometry_accuracy_basis: string | null;
  geometry_precision_m: number | null;
  transform_provenance: Readonly<{ method: string; source_crs: string; display_crs: "EPSG:4326" }> | null;
  provenance: Readonly<{
    source_id: string; source_record_id: string; authority: string; source_ref: string; source_version: string; retrieved_at: string;
  }>;
}>;

/** One `coverage` row, kept only when every field the disclosure renders is present. */
export type CoverageRow = Readonly<{
  assetClass: string;
  status: string;
  scopeId: string;
  scope: string;
  reason: string;
  observed: number | null;
  denominator: number | null;
  unknown: number | null;
  unavailable: number | null;
}>;

export type SpatialPage = Readonly<{
  api_version: "v1";
  state: "tx" | "mn";
  artifact_version: string;
  artifact_id: string;
  release_sha256: string;
  layer: string;
  inventory_mode: "physical_observed";
  electrical_model_mode: "none";
  items: readonly SpatialItem[];
  page: Readonly<{ limit: number; cursor: string | null; next_cursor: string | null; total: number }>;
  coverage: readonly CoverageRow[];
}>;

/**
 * A failure envelope from either status the API declares, with the server's own
 * code and message preserved verbatim. Nothing here writes a message of its own.
 */
export type SpatialFailure = Readonly<{
  status: "unavailable" | "error";
  error: Readonly<{ code: string; message: string; requestId?: string }>;
}>;

export type RenderableFeature = Readonly<{ type: "Feature"; id: string; geometry: GeoJsonGeometry; properties: SpatialItem }>;

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function geometry(value: unknown): GeoJsonGeometry | null {
  if (!record(value) || typeof value.type !== "string" || value.coordinates === undefined) return null;
  return { type: value.type, coordinates: value.coordinates };
}

function count(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/** Reject malformed payloads before they enter the scene; do not repair them. */
export function spatialItem(value: unknown): SpatialItem | null {
  if (!record(value) || typeof value.asset_id !== "string" || value.asset_id === "" ||
    typeof value.asset_class !== "string" || typeof value.asset_kind !== "string" ||
    (value.availability !== "available" && value.availability !== "unavailable") ||
    (value.display_crs !== "EPSG:4326" && value.display_crs !== null) ||
    (value.geometry_status !== "source" && value.geometry_status !== "derived" && value.geometry_status !== "unavailable") ||
    !record(value.provenance)) return null;
  const display = value.display_geometry === null ? null : geometry(value.display_geometry);
  const native = value.native_geometry === null ? null : geometry(value.native_geometry);
  if ((value.display_geometry !== null && display === null) || (value.native_geometry !== null && native === null)) return null;
  // The server uses this triple to state geometry absence. A client must not fill it.
  if (value.availability === "unavailable" && (display !== null || value.display_crs !== null || value.geometry_status !== "unavailable")) return null;
  if (value.availability === "available" && (display === null || value.display_crs !== "EPSG:4326")) return null;
  const provenance = value.provenance;
  const required = ["source_id", "source_record_id", "authority", "source_ref", "source_version", "retrieved_at"] as const;
  if (required.some((key) => typeof provenance[key] !== "string")) return null;
  if (value.native_crs !== null && typeof value.native_crs !== "string") return null;
  if (value.geometry_accuracy_basis !== null && typeof value.geometry_accuracy_basis !== "string") return null;
  if (value.geometry_precision_m !== null && typeof value.geometry_precision_m !== "number") return null;
  if (value.transform_provenance !== null && (!record(value.transform_provenance) || typeof value.transform_provenance.method !== "string" ||
    typeof value.transform_provenance.source_crs !== "string" || value.transform_provenance.display_crs !== "EPSG:4326")) return null;
  return value as SpatialItem;
}

/** Features with unavailable geometry stay in the accounting but never get a marker. */
export function renderableFeatures(items: readonly SpatialItem[]): readonly RenderableFeature[] {
  return items.flatMap((item) => item.availability === "available" && item.display_geometry !== null
    ? [{ type: "Feature" as const, id: item.asset_id, geometry: item.display_geometry, properties: item }]
    : []);
}

/**
 * How many loaded records became markers and how many did not. The unavailable
 * count is derived from the whole loaded set inside this function, so a caller
 * cannot report zero by handing it only the available records.
 */
export function geometryAccounting(items: readonly SpatialItem[]) {
  const renderable = renderableFeatures(items).length;
  return { totalLoaded: items.length, renderable, unavailableGeometry: items.length - renderable };
}

function coverageRow(value: unknown): CoverageRow | null {
  if (!record(value)) return null;
  const strings = ["asset_class", "status", "scope_id", "source_scope", "reason"] as const;
  if (strings.some((key) => typeof value[key] !== "string")) return null;
  return {
    assetClass: value.asset_class as string,
    status: value.status as string,
    scopeId: value.scope_id as string,
    scope: value.source_scope as string,
    reason: value.reason as string,
    observed: count(value.observed_count),
    denominator: count(value.denominator_count),
    unknown: count(value.unknown_count),
    unavailable: count(value.unavailable_count),
  };
}

/** Every coverage row across the loaded pages, de-duplicated on class + scope id. */
export function coverageRows(pages: readonly SpatialPage[]): readonly CoverageRow[] {
  const seen = new Set<string>();
  return pages.flatMap((page) => page.coverage).flatMap((row) => {
    const key = `${row.assetClass} ${row.scopeId}`;
    if (seen.has(key)) return [];
    seen.add(key);
    return [row];
  });
}

export function isSpatialFailure(value: SpatialPage | SpatialFailure): value is SpatialFailure {
  return "status" in value;
}

export function pageFrom(value: unknown): SpatialPage | SpatialFailure | null {
  if (!record(value)) return null;
  if ((value.status === "unavailable" || value.status === "error") && record(value.error) &&
    typeof value.error.code === "string" && typeof value.error.message === "string") {
    const meta = record(value.meta) ? value.meta : null;
    const requestId = meta !== null && typeof meta.request_id === "string" ? meta.request_id : undefined;
    return {
      status: value.status,
      error: { code: value.error.code, message: value.error.message, ...(requestId === undefined ? {} : { requestId }) },
    };
  }
  if (value.api_version !== "v1" || (value.state !== "tx" && value.state !== "mn") || typeof value.artifact_version !== "string" ||
    typeof value.artifact_id !== "string" || typeof value.release_sha256 !== "string" || typeof value.layer !== "string" ||
    value.inventory_mode !== "physical_observed" || value.electrical_model_mode !== "none" || !Array.isArray(value.items) ||
    !record(value.page) || !Array.isArray(value.coverage)) return null;
  const items = value.items.map(spatialItem);
  if (items.some((item) => item === null) || typeof value.page.limit !== "number" || typeof value.page.total !== "number" ||
    (value.page.cursor !== null && typeof value.page.cursor !== "string") || (value.page.next_cursor !== null && typeof value.page.next_cursor !== "string")) return null;
  const coverage = value.coverage.map(coverageRow);
  if (coverage.some((row) => row === null)) return null;
  return {
    api_version: "v1", state: value.state, artifact_version: value.artifact_version, artifact_id: value.artifact_id,
    release_sha256: value.release_sha256, layer: value.layer, inventory_mode: "physical_observed", electrical_model_mode: "none",
    items: items as SpatialItem[], page: value.page as SpatialPage["page"], coverage: coverage as CoverageRow[],
  };
}
