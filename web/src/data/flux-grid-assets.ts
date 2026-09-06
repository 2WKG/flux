import type { FluxPlacement, StatusLabel } from "../map/layers/fluxGridAssets";

export type AssetPlacementBounds = readonly [readonly [number, number], readonly [number, number]];

const STATUSES: readonly StatusLabel[] = [
  "source_supported", "source_screened", "hypothetical", "synthetic", "unavailable", "request_failed",
];

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function placement(value: unknown): FluxPlacement | null {
  if (!record(value) || typeof value.id !== "string" || value.id === "" ||
    typeof value.archetype_id !== "string" || value.archetype_id === "" ||
    typeof value.label !== "string" || value.label === "" ||
    typeof value.artifact_id !== "string" || value.artifact_id === "" ||
    !Array.isArray(value.position) || value.position.length !== 3 ||
    !value.position.every((coordinate) => typeof coordinate === "number" && Number.isFinite(coordinate)) ||
    !STATUSES.includes(value.status as StatusLabel)) return null;

  const [longitude, latitude, altitude] = value.position as number[];
  if (Math.abs(longitude) > 180 || Math.abs(latitude) >= 85.051129) return null;
  // The API's visual_mapping is a required disclosure: its archetype is a
  // render proxy, not an assertion that the source named a particular model.
  if (!(typeof value.visual_mapping === "string" && value.visual_mapping !== "") && !record(value.visual_mapping)) return null;
  return {
    id: value.id, archetype_id: value.archetype_id, position: [longitude, latitude, altitude],
    heading_degrees: typeof value.heading_degrees === "number" && Number.isFinite(value.heading_degrees) ? value.heading_degrees : 0,
    label: value.label, status: value.status as StatusLabel, artifact_id: value.artifact_id,
  };
}

/** Read only source-authenticated Texas placements for the current map viewport. */
export async function loadFluxGridPlacements(
  bounds: AssetPlacementBounds, signal: AbortSignal,
): Promise<readonly FluxPlacement[]> {
  const [[west, south], [east, north]] = bounds;
  if (![west, south, east, north].every(Number.isFinite) || west >= east || south >= north) {
    throw new Error("Asset placement request requires finite southwest/northeast bounds.");
  }
  const query = new URLSearchParams({ state: "tx", version: "1.1.0", bbox: `${west},${south},${east},${north}`, limit: "200" });
  const response = await fetch(`/api/v1/grid/asset-placements?${query}`, { signal, headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error(`Asset placement request failed (${response.status}).`);
  const body: unknown = await response.json();
  if (!record(body) || !Array.isArray(body.items)) throw new Error("Asset placement response has no items array.");
  const placements = body.items.map(placement);
  if (placements.some((item) => item === null)) throw new Error("Asset placement response contains an invalid item.");
  return placements as FluxPlacement[];
}
