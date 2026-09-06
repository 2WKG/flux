/** Filtering, and the load-bearing rule 2WKG-373 exists to enforce:
 * filtering never silently erases uncertainty.
 *
 * Salvaged from the closed PR #219 (`ghadikhou/2wkg-373-...`, commit bacd607),
 * retyped against `../labels.ts` — the module that owns the six source-truth
 * tokens — instead of #219's restated `UiStatus` union. Nothing here writes a
 * token, a display string, or a layer status of its own.
 *
 * A filter is any user choice that removes a layer from the visible set: a
 * manual visibility toggle, or a status filter ("hide unavailable layers").
 * Both paths go through `applyFilters`, and both produce the same guarantee:
 * a layer that gets filtered out is never simply gone. It appears in
 * `suppressed`, naming which layer, what status it carried, and why it was
 * suppressed. A caller that discards `suppressed` and renders only `visible`
 * has broken the contract this module exists to hold.
 *
 * Where #219 failed open, this fails closed. #219 passed an unrecognised
 * status string straight into `visible` and left it invisible to
 * `suppressesUncertainty()`. Here an unrecognised status is refused at the
 * module boundary by `isAssetStatus`: the layer is never visible, it is
 * disclosed as `unavailable` with the named refusal `unrecognized_status`,
 * and it counts as suppressed uncertainty.
 */

import { type AssetStatus, isAssetStatus } from "../labels.js";

/** Named refusal for a status this vocabulary does not define. */
export const UNRECOGNIZED_STATUS = "unrecognized_status";

export type SuppressionCause = "manual_toggle" | "status_filter" | typeof UNRECOGNIZED_STATUS;

/** A layer definition combined with its current, always-present data status. */
export interface LayerSnapshot {
  readonly id: string;
  readonly label: string;
  readonly status: AssetStatus;
  /** Populated whenever status is `unavailable` or `request_failed`. */
  readonly reason?: string;
  readonly requestId?: string;
}

export interface SuppressionDisclosure {
  readonly layerId: string;
  readonly label: string;
  readonly status: AssetStatus;
  /** Why the layer is not shown: its own data reason if it has one, else why the filter excluded it. */
  readonly reason: string;
  readonly cause: SuppressionCause;
}

export interface FilterCriteria {
  /** Layers hidden by an explicit per-layer visibility toggle. */
  readonly hiddenLayerIds: ReadonlySet<string>;
  /** Statuses a status filter has asked to hide (e.g. "hide synthetic"). */
  readonly excludedStatuses: ReadonlySet<AssetStatus>;
}

export interface FilterResult {
  readonly visible: readonly LayerSnapshot[];
  /** Every layer removed from `visible`, with a stated reason. Never omitted
   * to keep a filtered view "clean" -- an empty array here means nothing was
   * suppressed, not that disclosure was skipped. */
  readonly suppressed: readonly SuppressionDisclosure[];
}

/** Statuses that represent something less than a directly source-supported claim. */
export const LOWER_CONFIDENCE_STATUSES: ReadonlySet<AssetStatus> = new Set<AssetStatus>([
  "source_screened",
  "hypothetical",
  "synthetic",
]);

/** Statuses that always represent missing, weaker, or failed evidence -- never a value to hide quietly. */
export const UNCERTAIN_STATUSES: ReadonlySet<AssetStatus> = new Set<AssetStatus>([
  "unavailable",
  "request_failed",
  ...LOWER_CONFIDENCE_STATUSES,
]);

export function noFilters(): FilterCriteria {
  return { hiddenLayerIds: new Set(), excludedStatuses: new Set() };
}

/** The refusal text for a status outside `ASSET_STATUS_TOKENS`. Names the
 * offending value and the module that owns the vocabulary, so the disclosure
 * is actionable rather than a shrug. */
export function unrecognizedStatusReason(label: string, status: unknown): string {
  const rendered = typeof status === "string" ? `"${status}"` : String(status);
  return `${label} reported status ${rendered}, which is not one of the six source-truth tokens defined in src/labels.ts; it is refused as unavailable rather than shown.`;
}

function suppressionReason(snapshot: LayerSnapshot, cause: SuppressionCause): string {
  // A layer's own unavailable/failure reason always takes precedence: hiding
  // it must not replace an honest "why" with a generic filter label.
  if (snapshot.reason) return snapshot.reason;
  if (cause === "manual_toggle") {
    return `${snapshot.label} was hidden by a manual layer toggle.`;
  }
  return `${snapshot.label} was hidden because its status (${snapshot.status}) is excluded by the active status filter.`;
}

/**
 * Apply visibility and status filters to a set of layer snapshots.
 *
 * Every excluded layer is reported in `suppressed` with its status and a
 * reason, so an unavailable or lower-confidence class never disappears
 * without trace -- the whole point of this module. A snapshot whose status is
 * outside the frozen vocabulary is refused: it is never visible, and it is
 * disclosed as `unavailable` with the `unrecognized_status` cause.
 */
export function applyFilters(
  snapshots: readonly LayerSnapshot[],
  criteria: FilterCriteria,
): FilterResult {
  const visible: LayerSnapshot[] = [];
  const suppressed: SuppressionDisclosure[] = [];

  for (const snapshot of snapshots) {
    if (!isAssetStatus(snapshot.status)) {
      suppressed.push({
        layerId: snapshot.id,
        label: snapshot.label,
        status: "unavailable",
        reason: unrecognizedStatusReason(snapshot.label, snapshot.status),
        cause: UNRECOGNIZED_STATUS,
      });
      continue;
    }
    const manuallyHidden = criteria.hiddenLayerIds.has(snapshot.id);
    const statusExcluded = criteria.excludedStatuses.has(snapshot.status);
    if (!manuallyHidden && !statusExcluded) {
      visible.push(snapshot);
      continue;
    }
    // Manual toggle wins, so a layer hidden by both paths is reported once.
    const cause: SuppressionCause = manuallyHidden ? "manual_toggle" : "status_filter";
    suppressed.push({
      layerId: snapshot.id,
      label: snapshot.label,
      status: snapshot.status,
      reason: suppressionReason(snapshot, cause),
      cause,
    });
  }

  return { visible, suppressed };
}

/** True when at least one suppressed entry carries an uncertain status
 * (unavailable, request-failed, or one of the lower-confidence statuses).
 * A UI can use this to decide whether the disclosure panel must stay open --
 * it must never be false while uncertainty is hidden.
 */
export function suppressesUncertainty(result: FilterResult): boolean {
  return result.suppressed.some((entry) => UNCERTAIN_STATUSES.has(entry.status));
}

/** Disclosure entries restricted to the lower-confidence and unavailable/failed
 * statuses -- the set a "declutter" filter is most tempted to drop silently.
 */
export function uncertainSuppressions(result: FilterResult): readonly SuppressionDisclosure[] {
  return result.suppressed.filter((entry) => UNCERTAIN_STATUSES.has(entry.status));
}

/** A status filter that only targets the lower-confidence statuses -- e.g.
 * "show only confirmed data". It does not suppress `unavailable` or
 * `request_failed`: those disclose through their own reason, not a confidence
 * tier, and a caller that wants to hide them must add them explicitly and
 * will still receive their disclosure.
 */
export function lowerConfidenceStatuses(): ReadonlySet<AssetStatus> {
  return LOWER_CONFIDENCE_STATUSES;
}
