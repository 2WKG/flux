/** The layer registry, and the one rule salvaged from PR #219's `registry.ts`:
 * a layer id absent from the reported data is an explicit `unavailable` with a
 * named reason, never available-with-nothing-to-show.
 *
 * Per Gate 0 (`docs/design/minnesota-gate-0-approval.md`) aggregate mode is
 * the only accepted Minnesota coverage today, so a real caller wiring this
 * registry up now would report most of these layers `unavailable` with a named
 * reason -- and must never silently drop them from the registry instead.
 *
 * The status vocabulary is `../labels.ts` and is imported, never restated.
 */

import type { AssetStatus } from "../labels.js";
import type { LayerSnapshot } from "./filters.js";

/** Static, non-data-dependent facts about a layer class. */
export interface LayerDefinition {
  readonly id: string;
  readonly label: string;
  readonly description: string;
}

/**
 * A layer's data status, as reported by whatever produced its data. There is
 * no "empty but successful" variant: a layer either has data carrying one of
 * the four non-terminal statuses, is explicitly unavailable with a reason, or
 * reports that the request for its data failed.
 */
export type DataStatus =
  | { readonly kind: "available"; readonly status: Exclude<AssetStatus, "unavailable" | "request_failed"> }
  | { readonly kind: "unavailable"; readonly reason: string }
  | { readonly kind: "request_failed"; readonly reason: string; readonly requestId?: string };

/** The six layer classes 2WKG-373 names. */
export const LAYER_REGISTRY: readonly LayerDefinition[] = [
  { id: "topology", label: "Topology", description: "Buses, lines, and network structure." },
  { id: "facilities", label: "Facilities", description: "Generation, load, and facility points." },
  { id: "flows", label: "Flows", description: "Power-flow and loading results." },
  { id: "events", label: "Events", description: "Documented weather-stress and other scenario events." },
  { id: "proposals", label: "Proposals", description: "Facility alternatives and hypothetical comparisons." },
  { id: "provenance", label: "Provenance", description: "Source, evidence, citation, and coverage trail." },
];

export function snapshotOf(definition: LayerDefinition, dataStatus: DataStatus): LayerSnapshot {
  if (dataStatus.kind === "available") {
    return { id: definition.id, label: definition.label, status: dataStatus.status };
  }
  if (dataStatus.kind === "unavailable") {
    return { id: definition.id, label: definition.label, status: "unavailable", reason: dataStatus.reason };
  }
  return {
    id: definition.id,
    label: definition.label,
    status: "request_failed",
    reason: dataStatus.reason,
    requestId: dataStatus.requestId,
  };
}

/** The reason an unreported layer carries. Named, not a shrug. */
export function unreportedLayerReason(definition: LayerDefinition): string {
  return `No data status was reported for the ${definition.label} layer; it cannot be shown as available.`;
}

/**
 * Build one snapshot per registered layer. A layer id absent from
 * `dataStatuses` is not treated as available-with-nothing-to-show: it becomes
 * an explicit `unavailable` snapshot with a named reason.
 */
export function buildRegistrySnapshots(
  dataStatuses: Readonly<Record<string, DataStatus | undefined>>,
  definitions: readonly LayerDefinition[] = LAYER_REGISTRY,
): readonly LayerSnapshot[] {
  return definitions.map((definition) => {
    const status = dataStatuses[definition.id];
    if (status === undefined) {
      return snapshotOf(definition, { kind: "unavailable", reason: unreportedLayerReason(definition) });
    }
    return snapshotOf(definition, status);
  });
}
