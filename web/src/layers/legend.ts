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

/** Display copy for the six frozen statuses, quoted from the narrative-IA table. */
const ENTRY_COPY: Readonly<Record<AssetStatus, { label: string; description: string }>> = {
  source_supported: {
    label: "Source-supported",
    description: "Directly supported by the recorded source; opens Evidence.",
  },
  source_screened: {
    label: "Source-screened",
    description: "Screened against the recorded sources but not source-supported; never a finding.",
  },
  hypothetical: {
    label: "Hypothetical",
    description: "Compared inside the model's stated scope; never permitted, approved, or ready to build.",
  },
  synthetic: {
    label: "Synthetic",
    description: "An identified synthetic artifact only; never positioned as Minnesota infrastructure.",
  },
  unavailable: {
    label: "Unavailable",
    description: "A required artifact is absent, unbuilt, stale, or ineligible; the dependent value is hidden.",
  },
  request_failed: {
    label: "Request failed",
    description: "A request or provider failed; the last result may be stale but is not current.",
  },
};

/** Every legend entry, in the frozen token order. */
export const STATUS_LEGEND: readonly LegendEntry[] = ASSET_STATUS_TOKENS.map((status) => ({
  status,
  label: ENTRY_COPY[status].label,
  glyph: glyphForStatus(status),
  description: ENTRY_COPY[status].description,
}));

export interface LayerLegend {
  readonly layerId: string;
  readonly layerLabel: string;
  /** The status this layer currently carries, always shown. */
  readonly currentStatus: AssetStatus;
  /** Why the layer is in that status, when it carries a reason. */
  readonly currentReason?: string;
  /** The full key, so a viewer can read any status the layer may take. */
  readonly entries: readonly LegendEntry[];
  /** True when the layer's status is not one the server asserts. */
  readonly unrecognized: boolean;
}

/**
 * Build the legend for one layer snapshot.
 *
 * An unrecognised status is not silently dropped or coerced to a friendly
 * default: the legend reports it as `unavailable` with the unknown glyph and
 * flags `unrecognized`, matching how `filters.ts` refuses the same value.
 */
export function legendForLayer(snapshot: LayerSnapshot): LayerLegend {
  const recognized = isAssetStatus(snapshot.status);
  return {
    layerId: snapshot.id,
    layerLabel: snapshot.label,
    currentStatus: recognized ? snapshot.status : "unavailable",
    ...(snapshot.reason === undefined ? {} : { currentReason: snapshot.reason }),
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
