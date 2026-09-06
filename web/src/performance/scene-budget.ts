/** Compute a scene triangle budget report from placements and the archetype
 * catalog. Never estimates or measures a real frame cost -- it sums the
 * declared per-LOD triangle counts the contract already committed, against
 * the declared `sceneTriangleBudget`. If a number was not supplied by the
 * catalog or the placement list, it is a named issue, not a zero.
 */

import type { Archetype, AssetArchetypeCatalog, LodLevel } from "./archetype-catalog.js";
import { findArchetype, isDeclaredLod, trianglesForLod } from "./archetype-catalog.js";

export interface Placement {
  readonly archetypeId: string;
  readonly count: number;
  readonly lod: LodLevel;
}

export interface ArchetypeBudgetLine {
  readonly archetypeId: string;
  readonly lod: LodLevel;
  readonly count: number;
  readonly trianglesPerInstance: number;
  readonly totalTriangles: number;
}

export type PlacementIssue =
  | { readonly kind: "unknown_archetype"; readonly archetypeId: string }
  | { readonly kind: "invalid_count"; readonly archetypeId: string; readonly count: number }
  | { readonly kind: "invalid_lod"; readonly archetypeId: string; readonly lod: string };

export interface OverBudgetContributor {
  readonly archetypeId: string;
  readonly lod: LodLevel;
  readonly totalTriangles: number;
  readonly shareOfSceneBudget: number;
}

export interface SceneBudgetReport {
  readonly totalTriangles: number;
  readonly sceneTriangleBudget: number;
  readonly withinBudget: boolean;
  readonly lines: readonly ArchetypeBudgetLine[];
  /**
   * Populated only when the scene does not fit. Every valid placement line,
   * named and sorted by its own contribution (largest first) -- never a
   * derived "fair share" number the contract does not define.
   */
  readonly overBudgetArchetypes: readonly OverBudgetContributor[];
  readonly issues: readonly PlacementIssue[];
}

function isValidCount(count: unknown): count is number {
  return typeof count === "number" && Number.isFinite(count) && Number.isInteger(count) && count > 0;
}

/**
 * Sum declared triangles across placements against the catalog's
 * sceneTriangleBudget. An unknown archetype id, a non-positive count, or a
 * LOD label the archetype does not declare is a named issue and is excluded
 * from the totals rather than silently coerced. `Placement.lod` is typed
 * `LodLevel`, but placements originate in a server artifact parsed at
 * runtime, so the label is re-checked here: an undeclared level would
 * otherwise index to `undefined` and poison the totals with `NaN`.
 */
export function buildSceneBudgetReport(
  catalog: AssetArchetypeCatalog,
  placements: readonly Placement[],
): SceneBudgetReport {
  const lines: ArchetypeBudgetLine[] = [];
  const issues: PlacementIssue[] = [];

  for (const placement of placements) {
    const archetype: Archetype | undefined = findArchetype(catalog, placement.archetypeId);
    if (archetype === undefined) {
      issues.push({ kind: "unknown_archetype", archetypeId: placement.archetypeId });
      continue;
    }
    if (!isValidCount(placement.count)) {
      issues.push({ kind: "invalid_count", archetypeId: placement.archetypeId, count: placement.count });
      continue;
    }
    if (!isDeclaredLod(archetype, placement.lod)) {
      issues.push({
        kind: "invalid_lod",
        archetypeId: placement.archetypeId,
        lod: String(placement.lod),
      });
      continue;
    }
    const trianglesPerInstance = trianglesForLod(archetype, placement.lod);
    lines.push({
      archetypeId: placement.archetypeId,
      lod: placement.lod,
      count: placement.count,
      trianglesPerInstance,
      totalTriangles: trianglesPerInstance * placement.count,
    });
  }

  const totalTriangles = lines.reduce((sum, line) => sum + line.totalTriangles, 0);
  const withinBudget = totalTriangles <= catalog.budgets.sceneTriangleBudget;

  const overBudgetArchetypes: OverBudgetContributor[] = withinBudget
    ? []
    : [...lines]
        .sort((a, b) => b.totalTriangles - a.totalTriangles)
        .map((line) => ({
          archetypeId: line.archetypeId,
          lod: line.lod,
          totalTriangles: line.totalTriangles,
          shareOfSceneBudget: line.totalTriangles / catalog.budgets.sceneTriangleBudget,
        }));

  return {
    totalTriangles,
    sceneTriangleBudget: catalog.budgets.sceneTriangleBudget,
    withinBudget,
    lines,
    overBudgetArchetypes,
    issues,
  };
}
