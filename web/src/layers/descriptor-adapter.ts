/**
 * `LayerSnapshot` (what `registry.ts` produces) to `LayerDescriptor` (what
 * `LayerControls` consumes). They share only `id` and `label`; nothing on
 * `master` converted one into the other, and every composition of the panel
 * needed the conversion, so a component was about to grow one.
 *
 * Three rules, and each one has a mutation that turns a test red:
 *
 * 1. **`category` is the registry id, asserted.** The six `LAYER_REGISTRY` ids
 *    happen to be exactly the six `LayerCategory` values. That is a real
 *    correspondence, but it was an unwritten coincidence: renaming one registry
 *    id would have silently produced an `Unrecognized category` chip. Here it
 *    throws by name.
 * 2. **`evidenceClass` and `evidence` are never defaulted.** They are producer
 *    facts. A snapshot whose status asserts a five-field disclosure
 *    (`source_supported`, `source_screened`, `hypothetical`, `synthetic`) and
 *    that arrives without one is a refusal, not an `observed` guess. The two
 *    terminal tokens carry no evidence of their own, so `unavailable` is the
 *    correct evidence class for them and is the only value this module writes.
 * 3. **`visibility` is reason-driven, not status-driven.** `resolveLayer`
 *    refuses `missing_status_reason` for a terminal-status layer marked
 *    `enabled: true`, so a snapshot that carries a reason must become
 *    `{enabled: false, reason}` whatever its status is.
 */

import type { LayerSnapshot } from "./filters";
import type { LayerDefinition } from "./registry";
import type { EvidenceClass, LayerCategory, LayerDescriptor, LayerEvidence } from "./LayerControls";

/** The six categories the panel defines, in the registry's own order. */
export const LAYER_CATEGORIES: readonly LayerCategory[] = [
  "topology", "facilities", "flows", "events", "proposals", "provenance",
];

/** The statuses whose descriptors must carry a producer disclosure. */
const STATUSES_ASSERTING_EVIDENCE = ["source_supported", "source_screened", "hypothetical", "synthetic"] as const;

/** What a producer must supply alongside a non-terminal status. */
export type EvidenceDisclosure = Readonly<{ evidenceClass: EvidenceClass; evidence: LayerEvidence }>;

export class LayerDescriptorRefusal extends Error {
  constructor(readonly code: "unregistered_category" | "missing_evidence_disclosure", message: string) {
    super(message);
    this.name = "LayerDescriptorRefusal";
  }
}

function categoryOf(definition: LayerDefinition): LayerCategory {
  const category = LAYER_CATEGORIES.find((value) => value === definition.id);
  if (category === undefined) {
    throw new LayerDescriptorRefusal(
      "unregistered_category",
      `Registry layer "${definition.id}" is not one of the six layer categories the panel defines.`,
    );
  }
  return category;
}

/**
 * Build one descriptor. `disclosure` is the producer's evidence for this layer;
 * omit it only for a layer whose status asserts none.
 */
export function descriptorFor(
  definition: LayerDefinition,
  snapshot: LayerSnapshot,
  disclosure?: EvidenceDisclosure,
): LayerDescriptor {
  const category = categoryOf(definition);
  const assertsEvidence = (STATUSES_ASSERTING_EVIDENCE as readonly string[]).includes(snapshot.status);
  if (assertsEvidence && disclosure === undefined) {
    throw new LayerDescriptorRefusal(
      "missing_evidence_disclosure",
      `Layer "${snapshot.id}" reports ${snapshot.status} but the producer supplied no evidence disclosure; the panel will not invent one.`,
    );
  }
  return {
    id: snapshot.id,
    label: snapshot.label,
    category,
    sourceStatus: snapshot.status,
    // The only evidence class this module writes, and only for the two tokens
    // whose whole meaning is that there is no evidence to class.
    evidenceClass: disclosure?.evidenceClass ?? ("unavailable" satisfies EvidenceClass),
    ...(disclosure === undefined ? {} : { evidence: disclosure.evidence }),
    visibility: snapshot.reason === undefined
      ? { enabled: true }
      : { enabled: false, reason: snapshot.reason },
  };
}

/**
 * Descriptors for a whole registry walk. `disclosures` is keyed by layer id;
 * a layer with no entry and a status that asserts evidence is dropped with its
 * refusal recorded, so one missing disclosure never blanks the panel.
 */
export function descriptorsFor(
  definitions: readonly LayerDefinition[],
  snapshots: readonly LayerSnapshot[],
  disclosures: Readonly<Record<string, EvidenceDisclosure | undefined>> = {},
): { readonly layers: readonly LayerDescriptor[]; readonly refusals: readonly LayerDescriptorRefusal[] } {
  const byId = new Map(definitions.map((definition) => [definition.id, definition]));
  const layers: LayerDescriptor[] = [];
  const refusals: LayerDescriptorRefusal[] = [];
  for (const snapshot of snapshots) {
    const definition = byId.get(snapshot.id);
    if (definition === undefined) {
      refusals.push(new LayerDescriptorRefusal("unregistered_category", `Snapshot "${snapshot.id}" has no registry definition.`));
      continue;
    }
    try {
      layers.push(descriptorFor(definition, snapshot, disclosures[snapshot.id]));
    } catch (error) {
      if (error instanceof LayerDescriptorRefusal) refusals.push(error);
      else throw error;
    }
  }
  return { layers, refusals };
}
