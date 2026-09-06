/**
 * Derive the offline demo's own source-truth label from the fixture bundle's
 * persisted provenance, and nothing else.
 *
 * The demo IA (`docs/design/minnesota-demo-narrative-ia.md`, "Truth-label
 * visual system") requires every user-visible state label to come from a named
 * producer field. The browser-side vocabulary is `src/labels.ts` (the six IA
 * tokens, written once); the synthetic topology token is
 * `SYNTHETIC_TOPOLOGY_LABEL` in `src/scene/minnesota-adapter.ts`. Neither is
 * restated here.
 *
 * The rules below are the browser mirror of `copilot/routes/scenarios.py`
 * `_derive_labels`: a fixture source is `fixture` on no topology, an ACTIVSg
 * reference is `simulated` on the synthetic Texas topology, and any other
 * source is not inferred at all. What the provenance does not support is
 * `unavailable` -- never a plausible default, and never "source supported".
 */
import type { AssetStatus } from "./labels";
import { SYNTHETIC_TOPOLOGY_LABEL } from "./scene/minnesota-adapter";

/** The `source_kind` vocabulary the server contract already declares. */
export type SourceKind = "fixture" | "observed" | "simulated" | "heuristic" | "retrieval";

/**
 * The `sourceId` `model/generate_demo.py` writes for the checked-in five-bus
 * input. It is the demo's `fixture:` prefix equivalent.
 */
export const FIXTURE_SOURCE_ID = "flux_checked_in_synthetic_fixture";

/** Matches an ACTIVSg-derived reference the way `scenarios.py` does. */
const ACTIVSG_MARKER = "activsg";

export interface SourceTruth {
  /** One of the six IA tokens. */
  readonly status: AssetStatus;
  readonly sourceKind: SourceKind | null;
  /** Only ever the asserted synthetic topology token, or nothing. */
  readonly topology: typeof SYNTHETIC_TOPOLOGY_LABEL | null;
}

export interface DerivableProvenance {
  readonly sourceId: string;
  readonly sourceRef: string;
}

/** Derive the label triple from provenance. Unsupported provenance is `unavailable`. */
export function deriveSourceTruth(provenance: DerivableProvenance): SourceTruth {
  const haystack = `${provenance.sourceId} ${provenance.sourceRef}`.toLowerCase();
  if (haystack.includes(ACTIVSG_MARKER)) {
    return { status: "synthetic", sourceKind: "simulated", topology: SYNTHETIC_TOPOLOGY_LABEL };
  }
  if (provenance.sourceId === FIXTURE_SOURCE_ID || provenance.sourceId.startsWith("fixture:")) {
    return { status: "synthetic", sourceKind: "fixture", topology: null };
  }
  return { status: "unavailable", sourceKind: null, topology: null };
}

/**
 * Display copy for each IA token, keyed by the union so a token cannot be
 * forgotten. These strings are chrome for a status the data asserted; no
 * screen may write one directly.
 *
 * This map is the single owner of the six display strings -- the ownership
 * `src/layers/status-glyphs.ts:10-13` already names. The values are the IA's
 * "UI label" column verbatim (`docs/design/minnesota-demo-narrative-ia.md`,
 * the truth-label table), which hyphenates the first two. They previously read
 * "Source supported"/"Source screened" here while `src/layers/LayerControls.tsx`
 * carried the hyphenated IA spelling, so the same status read two ways; the IA
 * is the authority and this owner now matches it. `src/inspector/Inspector.tsx`
 * carried the unhyphenated spelling for longer still, and its own test pinned it;
 * both now read from here. `src/layers/legend.test.mjs` pins these values against
 * that table by label, not by line number, and `src/status-vocabulary.test.mjs`
 * pins that no surface re-spells them.
 */
export const STATUS_COPY: Record<AssetStatus, string> = {
  source_supported: "Source-supported",
  source_screened: "Source-screened",
  hypothetical: "Hypothetical",
  synthetic: "Synthetic",
  unavailable: "Unavailable",
  request_failed: "Request failed",
};

/** How the derived source identity reads in the nav and the status pill. */
export function sourceSummary(truth: SourceTruth): string {
  const kind = truth.sourceKind ? `${truth.sourceKind} source` : "no identified source";
  const topology = truth.topology ?? "no asserted topology";
  return `${STATUS_COPY[truth.status]} · ${kind} · ${topology}`;
}
