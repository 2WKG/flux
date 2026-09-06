/** Parse the shared 3D asset budget contract, or refuse it.
 *
 * `docs/design/3d-asset-contract.md` and its machine-readable catalog at
 * `data/3d/asset-archetypes-v1.json` are the single source of truth for scene
 * budgets. This module does not invent a triangle count, a file-size ceiling,
 * or a scene budget: it reads exactly the fields the contract declares
 * (`budgets.perArchetypeTrianglesLod0`, `perArchetypeFileBytes`,
 * `textureMaxPixels`, `sceneTriangleBudget`, `budgets.lodRule`, and each
 * archetype's `lod_triangles`) and refuses, by name, a catalog that is
 * missing or malformed rather than silently defaulting.
 *
 * Every parsed budget is consumed: `perArchetypeTrianglesLod0` and the
 * reduction shares read out of `budgets.lodRule` reject a non-conforming
 * archetype at parse time (the same rule
 * `scripts/validate_asset_archetypes.py` enforces, read from the catalog
 * rather than re-typed here); `perArchetypeFileBytes` and `textureMaxPixels`
 * are checked by `checkDeliveredAsset` against a delivered file's actual
 * byte count and texture dimensions; `sceneTriangleBudget` is consumed by
 * `scene-budget.ts`.
 *
 * This module never reads the file itself -- it has no `node:fs` import and
 * makes no assumption about running in Node vs. a browser. A caller (a test,
 * a build step, a future loader) reads the JSON and hands the parsed value to
 * `parseArchetypeCatalog`.
 */

export type LodLevel = "lod0" | "lod1" | "lod2";

export interface LodTriangles {
  readonly lod0: number;
  readonly lod1: number;
  readonly lod2: number;
}

export interface Archetype {
  readonly id: string;
  readonly lodTriangles: LodTriangles;
}

/**
 * The catalog's LOD reduction rule, parsed out of the prose
 * `budgets.lodRule` string rather than re-typed as a constant here, so a
 * change to the contract's percentages changes this module's behaviour.
 */
export interface LodRule {
  readonly lod1MaxShareOfLod0: number;
  readonly lod2MaxShareOfLod0: number;
  /** The exact contract sentence these shares were read from. */
  readonly source: string;
}

export interface SceneBudgets {
  readonly perArchetypeTrianglesLod0: number;
  readonly perArchetypeFileBytes: number;
  readonly textureMaxPixels: number;
  readonly sceneTriangleBudget: number;
  readonly lodRule: LodRule;
}

export interface AssetArchetypeCatalog {
  readonly budgets: SceneBudgets;
  readonly archetypes: readonly Archetype[];
}

export type CatalogParseFailureReason =
  | "not_an_object"
  | "missing_budgets"
  | "invalid_budget_field"
  | "invalid_lod_rule"
  | "missing_archetypes"
  | "empty_archetypes"
  | "invalid_archetype"
  | "lod0_over_budget"
  | "lod_chain_does_not_reduce";

export type CatalogParseResult =
  | { readonly kind: "parsed"; readonly catalog: AssetArchetypeCatalog }
  | { readonly kind: "rejected"; readonly reason: CatalogParseFailureReason; readonly detail: string };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isPositiveFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value > 0;
}

function rejected(reason: CatalogParseFailureReason, detail: string): CatalogParseResult {
  return { kind: "rejected", reason, detail };
}

const REQUIRED_BUDGET_FIELDS: readonly (keyof SceneBudgets)[] = [
  "perArchetypeTrianglesLod0",
  "perArchetypeFileBytes",
  "textureMaxPixels",
  "sceneTriangleBudget",
];

/**
 * Read the two reduction shares out of the contract's own `lodRule`
 * sentence (today: "lod1 <= 40% of lod0 triangles, lod2 <= 12%. ..."). The
 * percentages are never assumed: a rule string this parser cannot read is a
 * named rejection, so the module can never silently fall back to shares the
 * contract does not state.
 */
function parseLodRule(raw: unknown): LodRule | CatalogParseResult {
  if (typeof raw !== "string" || raw.trim().length === 0) {
    return rejected("invalid_lod_rule", "budgets.lodRule must be a non-empty string stating the LOD reduction rule.");
  }
  const lod1Match = /lod1\s*<=\s*([0-9]+(?:\.[0-9]+)?)\s*%/i.exec(raw);
  const lod2Match = /lod2\s*<=\s*([0-9]+(?:\.[0-9]+)?)\s*%/i.exec(raw);
  if (lod1Match === null || lod2Match === null) {
    return rejected(
      "invalid_lod_rule",
      `budgets.lodRule must state a percentage ceiling for lod1 and lod2 relative to lod0; got ${JSON.stringify(raw)}.`,
    );
  }
  const lod1MaxShareOfLod0 = Number(lod1Match[1]) / 100;
  const lod2MaxShareOfLod0 = Number(lod2Match[1]) / 100;
  if (!(lod1MaxShareOfLod0 > 0) || !(lod2MaxShareOfLod0 > 0)) {
    return rejected("invalid_lod_rule", `budgets.lodRule percentages must be positive; got ${JSON.stringify(raw)}.`);
  }
  return { lod1MaxShareOfLod0, lod2MaxShareOfLod0, source: raw };
}

function parseBudgets(raw: unknown): SceneBudgets | CatalogParseResult {
  if (!isRecord(raw)) {
    return rejected("missing_budgets", "The catalog has no `budgets` object.");
  }
  for (const field of REQUIRED_BUDGET_FIELDS) {
    if (!isPositiveFiniteNumber(raw[field])) {
      return rejected(
        "invalid_budget_field",
        `budgets.${field} must be a positive finite number; got ${JSON.stringify(raw[field])}.`,
      );
    }
  }
  const lodRule = parseLodRule(raw.lodRule);
  if ("kind" in lodRule) return lodRule;
  return {
    perArchetypeTrianglesLod0: raw.perArchetypeTrianglesLod0 as number,
    perArchetypeFileBytes: raw.perArchetypeFileBytes as number,
    textureMaxPixels: raw.textureMaxPixels as number,
    sceneTriangleBudget: raw.sceneTriangleBudget as number,
    lodRule,
  };
}

function parseLodTriangles(
  raw: unknown,
  archetypeId: string,
  budgets: SceneBudgets,
): LodTriangles | CatalogParseResult {
  if (!isRecord(raw)) {
    return rejected("invalid_archetype", `Archetype "${archetypeId}" has no lod_triangles object.`);
  }
  const { lod0, lod1, lod2 } = raw;
  if (![lod0, lod1, lod2].every(isPositiveFiniteNumber)) {
    return rejected(
      "invalid_archetype",
      `Archetype "${archetypeId}" lod_triangles must declare positive lod0, lod1, lod2 counts.`,
    );
  }
  const triangles: LodTriangles = { lod0: lod0 as number, lod1: lod1 as number, lod2: lod2 as number };

  if (triangles.lod0 > budgets.perArchetypeTrianglesLod0) {
    return rejected(
      "lod0_over_budget",
      `Archetype "${archetypeId}" declares lod0 ${triangles.lod0} triangles, above the contract's perArchetypeTrianglesLod0 ceiling of ${budgets.perArchetypeTrianglesLod0}.`,
    );
  }
  const { lod1MaxShareOfLod0, lod2MaxShareOfLod0 } = budgets.lodRule;
  if (triangles.lod1 > triangles.lod0 * lod1MaxShareOfLod0) {
    return rejected(
      "lod_chain_does_not_reduce",
      `Archetype "${archetypeId}" declares lod1 ${triangles.lod1} triangles, above ${lod1MaxShareOfLod0 * 100}% of lod0 ${triangles.lod0} required by budgets.lodRule.`,
    );
  }
  if (triangles.lod2 > triangles.lod0 * lod2MaxShareOfLod0) {
    return rejected(
      "lod_chain_does_not_reduce",
      `Archetype "${archetypeId}" declares lod2 ${triangles.lod2} triangles, above ${lod2MaxShareOfLod0 * 100}% of lod0 ${triangles.lod0} required by budgets.lodRule.`,
    );
  }
  return triangles;
}

function parseArchetype(raw: unknown, budgets: SceneBudgets): Archetype | CatalogParseResult {
  if (!isRecord(raw) || typeof raw.id !== "string" || raw.id.length === 0) {
    return rejected("invalid_archetype", "Archetype entry is missing a non-empty string id.");
  }
  const lodTriangles = parseLodTriangles(raw.lod_triangles, raw.id, budgets);
  if ("kind" in lodTriangles) return lodTriangles;
  return { id: raw.id, lodTriangles };
}

/**
 * Parse an already-JSON.parsed catalog document into the typed shape this
 * module works with. Refuses (rather than defaults) a document missing any
 * budget field or any archetype's lod_triangles.
 */
export function parseArchetypeCatalog(raw: unknown): CatalogParseResult {
  if (!isRecord(raw)) {
    return rejected("not_an_object", "The catalog document is not a JSON object.");
  }

  const budgets = parseBudgets(raw.budgets);
  if ("kind" in budgets) return budgets;

  const rawArchetypes = raw.archetypes;
  if (!Array.isArray(rawArchetypes)) {
    return rejected("missing_archetypes", "The catalog has no `archetypes` array.");
  }
  if (rawArchetypes.length === 0) {
    return rejected("empty_archetypes", "The catalog's `archetypes` array is empty.");
  }

  const archetypes: Archetype[] = [];
  for (const entry of rawArchetypes) {
    const archetype = parseArchetype(entry, budgets);
    if ("kind" in archetype) return archetype;
    archetypes.push(archetype);
  }

  return { kind: "parsed", catalog: { budgets, archetypes } };
}

export function findArchetype(
  catalog: AssetArchetypeCatalog,
  archetypeId: string,
): Archetype | undefined {
  return catalog.archetypes.find((archetype) => archetype.id === archetypeId);
}

/** The LOD levels every archetype in the catalog declares. */
export const DECLARED_LOD_LEVELS: readonly LodLevel[] = ["lod0", "lod1", "lod2"];

/**
 * Runtime guard for a LOD label. `LodLevel` is a compile-time claim, but
 * placements come from a server artifact parsed at runtime (see the
 * browser/server boundary in `docs/specs/00-overview.md`), so a caller must
 * be able to ask whether the archetype actually declares the level before
 * indexing it. Checks the archetype's own declared counts, not a typed list.
 */
export function isDeclaredLod(archetype: Archetype, lod: unknown): lod is LodLevel {
  return (
    typeof lod === "string" &&
    Object.prototype.hasOwnProperty.call(archetype.lodTriangles, lod) &&
    typeof (archetype.lodTriangles as unknown as Record<string, unknown>)[lod] === "number"
  );
}

export function trianglesForLod(archetype: Archetype, lod: LodLevel): number {
  return archetype.lodTriangles[lod];
}

export type DeliveredAssetViolationKind = "file_too_large" | "texture_too_large";

export interface DeliveredAssetViolation {
  readonly kind: DeliveredAssetViolationKind;
  readonly archetypeId: string;
  readonly actual: number;
  readonly ceiling: number;
  readonly detail: string;
}

export interface DeliveredAsset {
  readonly archetypeId: string;
  /** Byte size of the delivered .glb, as measured by the caller. */
  readonly fileBytes: number;
  /** Largest texture dimension in pixels, as measured by the caller. */
  readonly textureMaxPixels: number;
}

/**
 * Consume the contract's `perArchetypeFileBytes` and `textureMaxPixels`
 * ceilings against a delivered asset's measured size. This module measures
 * nothing itself -- the caller supplies the actual numbers -- but the
 * ceilings come from the catalog, never from a constant typed here. Returns
 * every violation by name; an empty array means the delivered asset fits.
 */
export function checkDeliveredAsset(
  catalog: AssetArchetypeCatalog,
  delivered: DeliveredAsset,
): readonly DeliveredAssetViolation[] {
  const violations: DeliveredAssetViolation[] = [];
  if (delivered.fileBytes > catalog.budgets.perArchetypeFileBytes) {
    violations.push({
      kind: "file_too_large",
      archetypeId: delivered.archetypeId,
      actual: delivered.fileBytes,
      ceiling: catalog.budgets.perArchetypeFileBytes,
      detail: `${delivered.archetypeId}: ${delivered.fileBytes} bytes exceeds the contract's perArchetypeFileBytes ceiling of ${catalog.budgets.perArchetypeFileBytes}.`,
    });
  }
  if (delivered.textureMaxPixels > catalog.budgets.textureMaxPixels) {
    violations.push({
      kind: "texture_too_large",
      archetypeId: delivered.archetypeId,
      actual: delivered.textureMaxPixels,
      ceiling: catalog.budgets.textureMaxPixels,
      detail: `${delivered.archetypeId}: ${delivered.textureMaxPixels} px exceeds the contract's textureMaxPixels ceiling of ${catalog.budgets.textureMaxPixels}.`,
    });
  }
  return violations;
}
