/** Parse the shared 3D asset budget contract, or refuse it.
 *
 * `docs/design/3d-asset-contract.md` and its machine-readable catalog at
 * `data/3d/asset-archetypes-v1.json` are the single source of truth for scene
 * budgets. This module does not invent a triangle count, a file-size ceiling,
 * or a scene budget: it reads exactly the fields the contract declares
 * (`budgets.perArchetypeTrianglesLod0`, `perArchetypeFileBytes`,
 * `textureMaxPixels`, `sceneTriangleBudget`, and each archetype's
 * `lod_triangles`) and refuses, by name, a catalog that is missing or
 * malformed rather than silently defaulting.
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

export interface SceneBudgets {
  readonly perArchetypeTrianglesLod0: number;
  readonly perArchetypeFileBytes: number;
  readonly textureMaxPixels: number;
  readonly sceneTriangleBudget: number;
}

export interface AssetArchetypeCatalog {
  readonly budgets: SceneBudgets;
  readonly archetypes: readonly Archetype[];
}

export type CatalogParseFailureReason =
  | "not_an_object"
  | "missing_budgets"
  | "invalid_budget_field"
  | "missing_archetypes"
  | "empty_archetypes"
  | "invalid_archetype";

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
  return {
    perArchetypeTrianglesLod0: raw.perArchetypeTrianglesLod0 as number,
    perArchetypeFileBytes: raw.perArchetypeFileBytes as number,
    textureMaxPixels: raw.textureMaxPixels as number,
    sceneTriangleBudget: raw.sceneTriangleBudget as number,
  };
}

function parseLodTriangles(raw: unknown, archetypeId: string): LodTriangles | CatalogParseResult {
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
  return { lod0: lod0 as number, lod1: lod1 as number, lod2: lod2 as number };
}

function parseArchetype(raw: unknown): Archetype | CatalogParseResult {
  if (!isRecord(raw) || typeof raw.id !== "string" || raw.id.length === 0) {
    return rejected("invalid_archetype", "Archetype entry is missing a non-empty string id.");
  }
  const lodTriangles = parseLodTriangles(raw.lod_triangles, raw.id);
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
    const archetype = parseArchetype(entry);
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

export function trianglesForLod(archetype: Archetype, lod: LodLevel): number {
  return archetype.lodTriangles[lod];
}
