/** Search over scene records the server actually produced.
 *
 * This module is a pure transform. It is not a client to any API, never reads
 * DuckDB, and invents no field: a `SearchCandidate` is exactly the projection
 * of one `BoundPlacement` (`web/src/scene/minnesota-adapter.ts`), which is the
 * only scene output the repository produces. Every field below is copied
 * verbatim from that placement -- the same `scene_id`, the same coordinates,
 * the same server-asserted status label. There is no display name, no
 * free-text location, and no scale here, because no producer emits one and a
 * plausible default would be a fabrication.
 *
 * The status vocabulary is imported, never restated: `web/src/labels.ts` owns
 * the six IA tokens and states there is no `source_backed` token in the
 * browser vocabulary. `search()` output is a UI surface, so it is bound to
 * that set (`docs/design/minnesota-gate-0-approval.md` section 3, and the
 * `MAT_STATUS` slot vocabulary the adapter carries).
 *
 * One rule is enforced strictly: a result never leaves this module without its
 * provenance -- a non-empty `sourceArtifactId` and a status token from the
 * frozen set. A candidate that matched but cannot show provenance is named in
 * `excluded` with a reason rather than being silently dropped or defaulted,
 * mirroring the evidence-first rule in
 * `docs/design/minnesota-demo-narrative-ia.md` ("Evidence: artifact ID ... Any
 * missing required evidence wins") and the refusal style of the adapter.
 */

import { type AssetStatus, isAssetStatus } from "../labels.js";
import type { SceneAdaptation } from "../scene/minnesota-adapter.js";

/**
 * One searchable record, projected field-for-field from a `BoundPlacement`.
 *
 * `statusLabel` is typed against the imported six-token vocabulary rather than
 * a local union, so a retired token (e.g. `source_backed`) cannot re-enter here.
 */
export interface SearchCandidate {
  /** `BoundPlacement.id` -- the server's `scene_id`, verbatim. */
  readonly id: string;
  /** `BoundPlacement.sourceArtifactId`, verbatim. This is the provenance. */
  readonly sourceArtifactId: string;
  /** `BoundPlacement.archetypeId`, verbatim. */
  readonly archetypeId: string;
  /** `BoundPlacement.semanticType`, verbatim. */
  readonly semanticType: string;
  /** `BoundPlacement.position` -- [longitude, latitude] in EPSG:4326, verbatim. */
  readonly position: readonly [number, number];
  /** `BoundPlacement.statusLabel` -- asserted by the server, never supplied here. */
  readonly statusLabel: AssetStatus;
}

/** A result is the candidate re-emitted verbatim once its provenance is proven. */
export type SearchResult = SearchCandidate;

export type SearchExclusionReason = "missing_provenance";

export interface SearchExclusion {
  readonly id: string;
  readonly reason: SearchExclusionReason;
  readonly detail: string;
}

export interface SearchQuery {
  /**
   * Case-insensitive substring match against the only text the server sent:
   * the scene id, the archetype id, and the semantic type. Empty/whitespace
   * matches everything.
   */
  readonly text: string;
  /** Exact-match filter on the server's `semantic_type`. */
  readonly semanticType?: string;
  /** Exact-match filter on the server's `archetype_id`. */
  readonly archetypeId?: string;
}

export interface SearchOutcome {
  readonly results: readonly SearchResult[];
  /** Candidates that matched the query but were dropped, and why. Never silent. */
  readonly excluded: readonly SearchExclusion[];
}

/** Why a scene adaptation yields no searchable record. Named, never silently skipped. */
export type NotSearchableReason = "no_scene_binding" | "aggregate_only_no_geometry";

export type CandidateProjection =
  | { readonly kind: "candidate"; readonly candidate: SearchCandidate }
  | { readonly kind: "not_searchable"; readonly reason: NotSearchableReason; readonly detail: string };

/**
 * Project one adapter output into a searchable candidate, or name why it is not
 * one. This is the only supported way to obtain a `SearchCandidate`: it copies
 * the placement's own fields and adds nothing.
 *
 * The adapter's other two outcomes are refusals for this surface too. Aggregate
 * coverage declares `renderableGeometry: false` and names no scene record, so
 * there is nothing to address or focus; a rejection carries no record at all.
 */
export function candidateFromScene(adaptation: SceneAdaptation): CandidateProjection {
  switch (adaptation.kind) {
    case "bound_placement": {
      const placement = adaptation.placement;
      return {
        kind: "candidate",
        candidate: {
          id: placement.id,
          sourceArtifactId: placement.sourceArtifactId,
          archetypeId: placement.archetypeId,
          semanticType: placement.semanticType,
          position: placement.position,
          statusLabel: placement.statusLabel,
        },
      };
    }
    case "aggregate_coverage":
      return {
        kind: "not_searchable",
        reason: "aggregate_only_no_geometry",
        detail:
          `Aggregate coverage (${adaptation.manifestFormat}) names no scene record and declares ` +
          "renderableGeometry: false, so it exposes nothing addressable to search or focus.",
      };
    case "rejected":
      return {
        kind: "not_searchable",
        reason: "no_scene_binding",
        detail: `The adapter refused this payload (${adaptation.reason}): ${adaptation.detail}`,
      };
  }
}

/**
 * Provenance is a non-empty source artifact plus a status token this build's
 * vocabulary defines. `isAssetStatus` is the single authority on that set --
 * this module keeps no copy of the tokens, so a token retired from
 * `src/labels.ts` is rejected here the moment it is retired there.
 */
function hasValidProvenance(candidate: SearchCandidate): boolean {
  return (
    typeof candidate.sourceArtifactId === "string" &&
    candidate.sourceArtifactId.length > 0 &&
    isAssetStatus(candidate.statusLabel)
  );
}

function matchesQuery(candidate: SearchCandidate, query: SearchQuery, needle: string): boolean {
  if (query.semanticType !== undefined && candidate.semanticType !== query.semanticType) return false;
  if (query.archetypeId !== undefined && candidate.archetypeId !== query.archetypeId) return false;
  if (needle.length === 0) return true;
  const haystack = `${candidate.id} ${candidate.archetypeId} ${candidate.semanticType}`.toLowerCase();
  return haystack.includes(needle);
}

/**
 * Search candidates. Every returned result carries the provenance the server
 * asserted, and results are emitted in input order -- the order the caller
 * supplied the candidates in, with no re-ranking, tie-break, or score.
 */
export function search(candidates: readonly SearchCandidate[], query: SearchQuery): SearchOutcome {
  const needle = query.text.trim().toLowerCase();
  const results: SearchResult[] = [];
  const excluded: SearchExclusion[] = [];

  for (const candidate of candidates) {
    if (!matchesQuery(candidate, query, needle)) continue;
    if (!hasValidProvenance(candidate)) {
      excluded.push({
        id: candidate.id,
        reason: "missing_provenance",
        detail: `Candidate "${candidate.id}" matched the query but has no valid provenance and cannot be returned as a result.`,
      });
      continue;
    }
    results.push({
      id: candidate.id,
      sourceArtifactId: candidate.sourceArtifactId,
      archetypeId: candidate.archetypeId,
      semanticType: candidate.semanticType,
      position: candidate.position,
      statusLabel: candidate.statusLabel,
    });
  }

  return { results, excluded };
}
