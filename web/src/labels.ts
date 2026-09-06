/**
 * The six source-truth status tokens the demo IA defines: see the "UI label"
 * table in `docs/design/minnesota-demo-narrative-ia.md`, whose second column
 * names the `master` field that produces each one. The server asserts one of
 * these tokens and the browser never derives or invents another — in
 * particular there is no `source_backed` token anywhere in the vocabulary.
 *
 * The union lives here so it is written once. Every browser surface that names
 * the vocabulary now aliases it instead of restating it: `SourceStatus`
 * (`src/ask/run-state/types.ts`, `src/failure-states/types.ts`),
 * `SourceTruthLabel` (`src/chat/ChatDock.tsx`), `ResultAvailability`
 * (`src/ask/results/types.ts`) and `SourceStatus` (`src/layers/LayerControls.tsx`).
 * `STATUS_LABELS` in `src/scene/minnesota-adapter.ts` stays a separate list
 * because it mirrors a server-side JSON artifact, and carries a type-level
 * assertion that the two coincide. `src/status-vocabulary.test.mjs` pins that no
 * surface re-declares the tokens or their display strings.
 *
 * `src/shell/AppShell.tsx` (PR #191) no longer exists; that branch is closed.
 */
export const ASSET_STATUS_TOKENS = [
  "source_supported",
  "source_screened",
  "hypothetical",
  "synthetic",
  "unavailable",
  "request_failed",
] as const;

export type AssetStatus = (typeof ASSET_STATUS_TOKENS)[number];

const KNOWN: ReadonlySet<string> = new Set(ASSET_STATUS_TOKENS);

/** True only for a token this vocabulary defines; never widens an unknown string. */
export function isAssetStatus(value: unknown): value is AssetStatus {
  return typeof value === "string" && KNOWN.has(value);
}
