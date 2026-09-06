/** Scale-aware detail: which labels and markers a scale shows, predictably.
 *
 * A pure function of the scale ladder, independent of any focus or breadcrumb
 * state. It is total over the three ladder scales and refuses everything else
 * by name (`unknown_scale`) rather than substituting a plausible level.
 * The caller (a future renderer) enforces `labelDensityCap`; this module never
 * counts, truncates, or picks which real labels win -- it only names the
 * budget and category for a scale so that behaviour is fixed and testable.
 */

import { RESET_SCALE, type Scale, SCALE_LADDER, isScale } from "./scale-ladder.js";

export type LabelDetail = "none" | "major_only" | "all";

export interface DetailLevel {
  readonly scale: Scale;
  /** Which class of label is shown at this scale. */
  readonly labelDetail: LabelDetail;
  /**
   * Whether individual facility markers are shown at this scale at all.
   *
   * Gated, not granted. Gate 0 (`docs/design/minnesota-gate-0-approval.md`
   * section 2) records "no geometry, no topology, no facility points" as the
   * accepted Minnesota position, and `allowsTopologyRendering` is false for
   * everything `web/src/scene/minnesota-adapter.ts` can return today. This
   * flag names the renderer's policy for a scale; a renderer may only honour
   * `true` once the `10-minnesota-demo.md` network decision gate accepts a
   * solver-complete source.
   */
  readonly showFacilityMarkers: boolean;
  /** Upper bound on simultaneously rendered labels at this scale; a renderer's cap, not a count of real data. */
  readonly labelDensityCap: number;
}

const DETAIL_LEVELS: Readonly<Record<Scale, DetailLevel>> = {
  statewide: { scale: "statewide", labelDetail: "major_only", showFacilityMarkers: false, labelDensityCap: 12 },
  region: { scale: "region", labelDetail: "all", showFacilityMarkers: false, labelDensityCap: 40 },
  facility: { scale: "facility", labelDetail: "all", showFacilityMarkers: true, labelDensityCap: 200 },
};

/** The complete, scale-indexed detail table, in ladder order. */
export const DETAIL_LEVEL_LADDER: readonly DetailLevel[] = SCALE_LADDER.map((scale) => DETAIL_LEVELS[scale]);

/** Why a detail level could not be resolved. Named, never substituted. */
export type DetailLevelRejectionReason = "unknown_scale";

export type DetailLevelResolution =
  | { readonly kind: "detail_level"; readonly level: DetailLevel }
  | { readonly kind: "rejected"; readonly reason: DetailLevelRejectionReason; readonly detail: string };

/**
 * Resolve the detail level for a scale, or refuse the scale by name.
 *
 * The input is deliberately `unknown`: the real callers are a URL hash, a
 * stored preference, and a message from another module, none of which are
 * type-checked at runtime. A value that is not on the ladder is refused --
 * never quietly answered with the statewide level, which would fabricate a
 * detail budget for a scale that does not exist.
 */
export function detailLevelForScale(scale: unknown): DetailLevelResolution {
  if (!isScale(scale)) {
    return {
      kind: "rejected",
      reason: "unknown_scale",
      detail: `${JSON.stringify(scale)} is not one of the ${SCALE_LADDER.join(", ")} scales; no detail level exists for it.`,
    };
  }
  return { kind: "detail_level", level: DETAIL_LEVELS[scale] };
}

export const RESET_DETAIL_LEVEL: DetailLevel = DETAIL_LEVELS[RESET_SCALE];
