/** Deterministic LOD selection from a camera distance and a placement scale.
 *
 * This is pure geometry, not a measurement: given the same distance, scale,
 * and thresholds it always returns the same level. It never reads a frame
 * time or a real GPU cost, and it never selects a level the archetype
 * catalog does not declare (`lod0`, `lod1`, `lod2` only -- see
 * `archetype-catalog.ts`).
 */

import type { LodLevel } from "./archetype-catalog.js";

export interface LodDistanceThresholds {
  /** At or below this effective distance, lod0 is selected. */
  readonly lod0MaxDistanceMeters: number;
  /** Above lod0's threshold and at or below this one, lod1 is selected. Above it, lod2. */
  readonly lod1MaxDistanceMeters: number;
}

/**
 * Implementation defaults with no contract backing.
 *
 * `data/3d/asset-archetypes-v1.json` and `docs/design/3d-asset-contract.md`
 * declare triangle, byte, texture, and LOD-reduction budgets and state **no**
 * distance thresholds at all. These two numbers are therefore a starting
 * point chosen here, not a contract value, and they have not been derived
 * from a measurement either. A caller with a real camera and a real scene is
 * expected to pass its own `LodDistanceThresholds` to `selectLod`; treat
 * these only as the placeholder that keeps the pure function callable.
 */
export const DEFAULT_LOD_THRESHOLDS: LodDistanceThresholds = {
  lod0MaxDistanceMeters: 150,
  lod1MaxDistanceMeters: 1500,
};

export type LodSelectionFailureReason = "non_finite_distance" | "non_positive_scale";

export type LodSelectionResult =
  | { readonly kind: "selected"; readonly lod: LodLevel; readonly effectiveDistanceMeters: number }
  | { readonly kind: "rejected"; readonly reason: LodSelectionFailureReason; readonly detail: string };

/**
 * A larger placement scale reads as closer: an object scaled up presents a
 * bigger silhouette per unit of camera distance, so the effective distance is
 * the raw distance divided by scale. Distance is clamped at zero (never
 * negative); scale must be a positive finite number or the call is refused
 * rather than silently defaulted to 1.
 */
export function selectLod(
  distanceMeters: number,
  scale: number,
  thresholds: LodDistanceThresholds = DEFAULT_LOD_THRESHOLDS,
): LodSelectionResult {
  if (!Number.isFinite(distanceMeters)) {
    return { kind: "rejected", reason: "non_finite_distance", detail: `distanceMeters must be finite; got ${distanceMeters}.` };
  }
  if (!Number.isFinite(scale) || scale <= 0) {
    return { kind: "rejected", reason: "non_positive_scale", detail: `scale must be a positive finite number; got ${scale}.` };
  }

  const clampedDistance = Math.max(0, distanceMeters);
  const effectiveDistanceMeters = clampedDistance / scale;

  let lod: LodLevel;
  if (effectiveDistanceMeters <= thresholds.lod0MaxDistanceMeters) {
    lod = "lod0";
  } else if (effectiveDistanceMeters <= thresholds.lod1MaxDistanceMeters) {
    lod = "lod1";
  } else {
    lod = "lod2";
  }

  return { kind: "selected", lod, effectiveDistanceMeters };
}
