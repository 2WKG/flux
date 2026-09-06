/** The named, non-colour glyph for each source-truth status.
 *
 * The IA requires a signal that is not hue: "Text is mandatory; hue alone is
 * never the signal" (`docs/design/minnesota-demo-narrative-ia.md:216`). These
 * six names are read straight out of that table's "Visual treatment" column;
 * the cited line is the row each name comes from. No name is invented here,
 * and no colour is encoded -- the hue belongs to CSS, the glyph name is the
 * accessible pairing the legend renders alongside the label.
 *
 * Salvaged from the closed PR #219's `legend.ts` (commit bacd607), keyed by
 * `AssetStatus` from `../labels.ts` so a token cannot be forgotten or renamed
 * here. #219's rival display-copy map is deliberately not salvaged: the
 * display strings are owned by `../source-truth.ts` `STATUS_COPY`.
 */

import { type AssetStatus, isAssetStatus } from "../labels.js";

export const STATUS_GLYPHS: Readonly<Record<AssetStatus, string>> = {
  // "solid teal label with check glyph" -- minnesota-demo-narrative-ia.md:225
  source_supported: "check",
  // "teal outline with half-check glyph" -- minnesota-demo-narrative-ia.md:226
  source_screened: "half-check",
  // "violet outline with arrow glyph" -- minnesota-demo-narrative-ia.md:227
  hypothetical: "arrow",
  // "indigo label with dotted fill" -- minnesota-demo-narrative-ia.md:228
  // (hyphenated here as a single glyph identifier, as with half-check)
  synthetic: "dotted-fill",
  // "amber outline with blocked glyph" -- minnesota-demo-narrative-ia.md:229
  unavailable: "blocked",
  // "red outline with error glyph" -- minnesota-demo-narrative-ia.md:230
  request_failed: "error",
};

/** The glyph a status outside the frozen six resolves to: a named refusal,
 * never a plausible default and never an `undefined` hole in the legend
 * (the defect this salvage exists to correct). */
export const UNKNOWN_STATUS_GLYPH = "unrecognized-status";

export function glyphForStatus(status: unknown): string {
  return isAssetStatus(status) ? STATUS_GLYPHS[status] : UNKNOWN_STATUS_GLYPH;
}
