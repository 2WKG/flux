/**
 * The browser boundary for 2WKG-89's spatial-layer response.
 *
 * MapLibre/deck consume `display_geometry` only. It is server-produced WGS84;
 * native geometry remains source evidence and is deliberately never projected
 * or guessed in this browser.
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
  coverage: readonly unknown[];
}>;

export type SpatialFailure = Readonly<{ status: "unavailable"; error: Readonly<{ code: string; message: string; request_id?: string }> }>;

export type RenderableFeature = Readonly<{ type: "Feature"; id: string; geometry: GeoJsonGeometry; properties: SpatialItem }>;

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function geometry(value: unknown): GeoJsonGeometry | null {
  if (!record(value) || typeof value.type !== "string" || value.coordinates === undefined) return null;
  return { type: value.type, coordinates: value.coordinates };
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

/** Features with unavailable geometry stay in accounting but never get a marker. */
export function renderableFeatures(items: readonly SpatialItem[]): readonly RenderableFeature[] {
  return items.flatMap((item) => item.availability === "available" && item.display_geometry !== null
    ? [{ type: "Feature" as const, id: item.asset_id, geometry: item.display_geometry, properties: item }]
    : []);
}

export function geometryAccounting(items: readonly SpatialItem[]) {
  const renderable = renderableFeatures(items).length;
  return { totalLoaded: items.length, renderable, unavailableGeometry: items.length - renderable };
}

export function pageFrom(value: unknown): SpatialPage | SpatialFailure | null {
  if (!record(value)) return null;
  if (value.status === "unavailable" && record(value.error) && typeof value.error.code === "string" && typeof value.error.message === "string") {
    return { status: "unavailable", error: { code: value.error.code, message: value.error.message, request_id: typeof value.meta === "object" && value.meta !== null && typeof (value.meta as Record<string, unknown>).request_id === "string" ? (value.meta as Record<string, string>).request_id : undefined } };
  }
  if (value.api_version !== "v1" || (value.state !== "tx" && value.state !== "mn") || typeof value.artifact_version !== "string" ||
    typeof value.artifact_id !== "string" || typeof value.release_sha256 !== "string" || typeof value.layer !== "string" ||
    value.inventory_mode !== "physical_observed" || value.electrical_model_mode !== "none" || !Array.isArray(value.items) ||
    !record(value.page) || !Array.isArray(value.coverage)) return null;
  const items = value.items.map(spatialItem);
  if (items.some((item) => item === null) || typeof value.page.limit !== "number" || typeof value.page.total !== "number" ||
    (value.page.cursor !== null && typeof value.page.cursor !== "string") || (value.page.next_cursor !== null && typeof value.page.next_cursor !== "string")) return null;
  return {
    api_version: "v1", state: value.state, artifact_version: value.artifact_version, artifact_id: value.artifact_id,
    release_sha256: value.release_sha256, layer: value.layer, inventory_mode: "physical_observed", electrical_model_mode: "none",
    items: items as SpatialItem[], page: value.page as SpatialPage["page"], coverage: value.coverage,
  };
}
