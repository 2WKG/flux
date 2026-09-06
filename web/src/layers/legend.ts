/** Per-layer legend model: the entries a legend must render, each paired with a
 * readable label so hue is never the only signal.
 *
 * 2WKG-373 requires that *each layer* has a legend beside its data-status
 * disclosure. `registry.ts` already supplies the layers and their statuses and
 * `filters.ts` already discloses what filtering suppressed; this module answers
 * the remaining question — what a viewer must be shown in order to read those
 * statuses at all.
 *
 * Two rules are load-bearing, both from
 * `docs/design/minnesota-demo-narrative-ia.md` and Gate 0
 * (`docs/design/minnesota-gate-0-approval.md`):
 *
 * 1. Every entry carries a readable label and a named non-colour glyph. Colour
 *    never carries the claim alone.
 * 2. There are exactly six entries, one per frozen UI status. There is no
 *    seventh decorative "illustrative" entry — that label was deliberately
 *    retired because no server field asserts it, and minting one here would
 *    just move the same violation into the legend.
 */

import { ASSET_STATUS_TOKENS, isAssetStatus, type AssetStatus } from "../labels.js";
import { STATUS_COPY } from "../source-truth.js";
import { glyphForStatus, UNKNOWN_STATUS_GLYPH } from "./status-glyphs.js";
import type { LayerSnapshot } from "./filters.js";

export interface LegendEntry {
  readonly status: AssetStatus;
  /** Readable text. Never rely on the glyph or a colour alone. */
  readonly label: string;
  /** Named, non-colour visual signal — a glyph name, never a hex value. */
  readonly glyph: string;
  readonly description: string;
}

/**
 * The one-line meaning shown beside each label, condensed from the IA table's
 * *"Meaning and interaction"* column (`docs/design/minnesota-demo-narrative-ia.md`,
 * the truth-label table) -- condensed, not quoted, and deliberately not the
 * "Required accompanying copy" column, which is producer-supplied (see the note
 * on `legendForLayer`).
 *
 * Only the descriptions live here. The six *labels* are not restated: they are
 * owned by `../source-truth.ts` `STATUS_COPY`, exactly as `./status-glyphs.ts`
 * declares, and imported below.
 */
const ENTRY_DESCRIPTIONS: Readonly<Record<AssetStatus, string>> = {
  source_supported: "Directly supported by the recorded source; opens Evidence.",
  source_screened:
    "Screened against the recorded sources but not source-supported; never a finding.",
  hypothetical:
    "Compared inside the model's stated scope; never rendered as permitted, approved, or ready to build.",
  synthetic: "An identified synthetic artifact only; never positioned as Minnesota infrastructure.",
  unavailable:
    "A required artifact is absent, unbuilt, stale, or ineligible; the dependent value is hidden.",
  request_failed: "A request or provider failed; the last result may be stale but is not current.",
};

/** Every legend entry, in the frozen token order. */
export const STATUS_LEGEND: readonly LegendEntry[] = ASSET_STATUS_TOKENS.map((status) => ({
  status,
  label: STATUS_COPY[status],
  glyph: glyphForStatus(status),
  description: ENTRY_DESCRIPTIONS[status],
}));

export interface LayerLegend {
  readonly layerId: string;
  readonly layerLabel: string;
  /** The status this layer currently carries, always shown. */
  readonly currentStatus: AssetStatus;
  /** Why the layer is in that status, when it carries a reason. */
  readonly currentReason?: string;
  /**
   * The producer's request ID. Present on every `request_failed` legend -- the
   * IA requires it in that row's accompanying copy -- and carried whenever a
   * snapshot supplies one. A `request_failed` snapshot with no request ID gets
   * `REQUEST_ID_UNSUPPLIED`, never a fabricated or plausible-looking ID.
   */
  readonly currentRequestId?: string;
  /** The full key, so a viewer can read any status the layer may take. */
  readonly entries: readonly LegendEntry[];
  /** True when the layer's status is not one the server asserts. */
  readonly unrecognized: boolean;
}

/**
 * The named refusal a `request_failed` legend carries when the producer supplied
 * no request ID. The IA's accompanying copy for that row is "safe message,
 * request ID if supplied, retry guidance": when it is not supplied, the legend
 * says so by name rather than omitting the field or minting an ID of its own.
 */
export const REQUEST_ID_UNSUPPLIED = "request-id-unsupplied";

/**
 * Build the legend for one layer snapshot.
 *
 * An unrecognised status is not silently dropped or coerced to a friendly
 * default: the legend reports it as `unavailable` with the unknown glyph and
 * flags `unrecognized`, matching how `filters.ts` refuses the same value.
 *
 * On the IA's "Required accompanying copy" column: the one part of it this
 * module can carry is the request ID, because `LayerSnapshot` already has the
 * producer's `requestId`, so it is carried rather than dropped. The rest of
 * that column is producer-supplied prose -- `unavailable`'s named next step and
 * `request_failed`'s retry guidance -- and no field on `LayerSnapshot` asserts
 * it. This module refuses it rather than inventing it, the same refusal
 * `LayerControls.tsx` makes for the same two rows; a renderer must obtain that
 * copy from the producer.
 */
export function legendForLayer(snapshot: LayerSnapshot): LayerLegend {
  const recognized = isAssetStatus(snapshot.status);
  const currentStatus: AssetStatus = recognized ? snapshot.status : "unavailable";
  const requestId =
    snapshot.requestId ??
    (currentStatus === "request_failed" ? REQUEST_ID_UNSUPPLIED : undefined);
  return {
    layerId: snapshot.id,
    layerLabel: snapshot.label,
    currentStatus,
    ...(snapshot.reason === undefined ? {} : { currentReason: snapshot.reason }),
    ...(requestId === undefined ? {} : { currentRequestId: requestId }),
    entries: STATUS_LEGEND,
    unrecognized: !recognized,
  };
}

/** Build a legend for every layer, so no layer renders without one. */
export function legendsForLayers(snapshots: readonly LayerSnapshot[]): readonly LayerLegend[] {
  return snapshots.map(legendForLayer);
}

/** The glyph a legend uses for a status it does not recognise. */
export { UNKNOWN_STATUS_GLYPH };
