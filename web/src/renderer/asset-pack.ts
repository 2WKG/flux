/**
 * Contract checks for the optional, same-origin CAD asset pack.
 *
 * The reviewed source manifest is committed, but its binary archive is not.
 * A static SPA server therefore answers a missing asset request with index.html.
 * Treat that as an installation prerequisite before attempting JSON or GLB parsing.
 */

export type AssetPackLoadState = "ready" | "install_required" | "request_failed";

export const ASSET_PACK_INSTALL_ACTION =
  "The reviewed CAD archive is not published with this checkout. Obtain the verified Flux Grid asset pack from the release owner, then run node scripts/install_flux_grid_pack.mjs /path/to/extracted/flux-grid-assets from the repository root and restart the UI.";

export class AssetPackError extends Error {
  constructor(
    readonly state: Exclude<AssetPackLoadState, "ready">,
    message: string,
  ) {
    super(message);
    this.name = "AssetPackError";
  }
}

type AssetResponseKind = "manifest" | "model" | "image" | "mapping";

const EXPECTED_CONTENT_TYPE: Readonly<Record<AssetResponseKind, string>> = {
  manifest: "application/json",
  model: "model/gltf-binary",
  image: "image/png",
  mapping: "application/json",
};

function normalizedContentType(response: Response): string {
  return (response.headers.get("content-type") ?? "").split(";", 1)[0].trim().toLowerCase();
}

/**
 * Refuse the static app shell before a caller attempts response.json() or
 * response.arrayBuffer().  HTML and 404/410 mean the optional pack was not
 * installed; a different successful type is a deployment error worth naming.
 */
export function assertAssetResponse(
  response: Response,
  kind: AssetResponseKind,
  resource: string,
): void {
  const type = normalizedContentType(response);
  if (response.status === 404 || response.status === 410 || type === "text/html") {
    throw new AssetPackError(
      "install_required",
      `The optional 3D asset pack is not installed: ${resource} returned ${response.status} ${type || "without a content type"}.`,
    );
  }
  if (!response.ok) {
    throw new AssetPackError(
      "request_failed",
      `3D asset request failed (${response.status}): ${resource}.`,
    );
  }
  const expected = EXPECTED_CONTENT_TYPE[kind];
  if (type !== expected) {
    throw new AssetPackError(
      "request_failed",
      `3D asset response has the wrong content type for ${resource}: expected ${expected}, received ${type || "none"}.`,
    );
  }
}

/** A compact, render-ready message for the inventory surface. */
export function assetPackNotice(state: AssetPackLoadState, detail: string): {
  readonly heading: string;
  readonly detail: string;
  readonly action: string | null;
} {
  switch (state) {
    case "ready":
      return { heading: "Verified 3D asset pack", detail, action: null };
    case "install_required":
      return { heading: "3D asset pack install required", detail, action: ASSET_PACK_INSTALL_ACTION };
    case "request_failed":
      return { heading: "3D asset pack request failed", detail, action: "Check the same-origin asset deployment, then retry the inventory view." };
  }
}
