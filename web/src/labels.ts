/**
 * The six source-truth status tokens the demo IA defines: see the "UI label"
 * table in `docs/design/minnesota-demo-narrative-ia.md`, whose second column
 * names the `master` field that produces each one. The server asserts one of
 * these tokens and the browser never derives or invents another — in
 * particular there is no `source_backed` token anywhere in the vocabulary.
 *
 * The union lives here so it is written once. Two other open branches
 * hand-write the same six tokens today — PR #191 in `src/shell/AppShell.tsx`
 * and PR #183 in `src/chat/ChatDock.tsx` (as `SourceTruthLabel`) — and should
 * import from this module instead of restating the list when they land.
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
