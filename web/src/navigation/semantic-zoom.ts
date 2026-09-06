/** Scale-aware detail: which labels and markers a scale shows, predictably.
 *
 * A pure function of `Scale`, independent of any focus or breadcrumb state.
 * The caller (a future renderer) enforces `labelDensityCap`; this module never
 * counts, truncates, or picks which real labels win -- it only names the
 * budget and category for a scale so that behaviour is fixed and testable.
 */

import { RESET_SCALE, type Scale, SCALE_LADDER } from "./scale-ladder.js";

export type LabelDetail = "none" | "major_only" | "all";

export interface DetailLevel {
  readonly scale: Scale;
  /** Which class of label is shown at this scale. */
  readonly labelDetail: LabelDetail;
  /** Whether individual facility markers are shown at this scale at all. */
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

export function detailLevelForScale(scale: Scale): DetailLevel {
  return DETAIL_LEVELS[scale];
}

export const RESET_DETAIL_LEVEL: DetailLevel = DETAIL_LEVELS[RESET_SCALE];
