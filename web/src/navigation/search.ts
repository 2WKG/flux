/** Search over supplied candidate records by location/type.
 *
 * This module reads only the candidates a caller supplies -- it is not a
 * client to any API and never reads DuckDB -- and it enforces one rule
 * strictly: a result never leaves this module without its provenance. A
 * candidate with no provenance is never guessed at or defaulted; it is
 * dropped into `excluded` with a named reason so the caller can see and
 * report the omission rather than silently losing it. This mirrors the
 * evidence-first rule in `docs/design/minnesota-demo-narrative-ia.md`
 * ("Evidence: artifact ID ... Any missing required evidence wins") and the
 * refusal style of `web/src/scene/minnesota-adapter.ts`.
 */

import type { Scale } from "./scale-ladder.js";

/** The two frozen truth-label vocabularies both resolve to this artifact-level set
 * (`docs/design/minnesota-gate-0-approval.md`, section 3). This module never invents
 * a fourth value; a candidate carrying anything else is treated as having no provenance. */
export type TruthLabel = "source_backed" | "synthetic" | "unavailable";

export interface Provenance {
  readonly sourceId: string;
  readonly artifactId: string;
  readonly truthLabel: TruthLabel;
}

export interface SearchCandidate {
  readonly id: string;
  readonly name: string;
  readonly scale: Scale;
  readonly recordType: string;
  /** Free-text location description (e.g. a county or region name). Never a coordinate. */
  readonly locationText: string | null;
  /** `null` means the caller could not supply provenance for this candidate. */
  readonly provenance: Provenance | null;
}

export interface SearchResult {
  readonly id: string;
  readonly name: string;
  readonly scale: Scale;
  readonly recordType: string;
  readonly locationText: string | null;
  readonly provenance: Provenance;
}

export type SearchExclusionReason = "missing_provenance";

export interface SearchExclusion {
  readonly id: string;
  readonly reason: SearchExclusionReason;
  readonly detail: string;
}

export interface SearchQuery {
  /** Case-insensitive substring match against name and location text. Empty/whitespace matches everything. */
  readonly text: string;
  readonly recordType?: string;
  readonly scale?: Scale;
}

export interface SearchOutcome {
  readonly results: readonly SearchResult[];
  /** Candidates that matched the query but were dropped, and why. Never silent. */
  readonly excluded: readonly SearchExclusion[];
}

const VALID_TRUTH_LABELS: ReadonlySet<TruthLabel> = new Set(["source_backed", "synthetic", "unavailable"]);

function hasValidProvenance(provenance: Provenance | null): provenance is Provenance {
  return (
    provenance !== null &&
    typeof provenance.sourceId === "string" &&
    provenance.sourceId.length > 0 &&
    typeof provenance.artifactId === "string" &&
    provenance.artifactId.length > 0 &&
    VALID_TRUTH_LABELS.has(provenance.truthLabel)
  );
}

function matchesQuery(candidate: SearchCandidate, query: SearchQuery, needle: string): boolean {
  if (query.recordType !== undefined && candidate.recordType !== query.recordType) return false;
  if (query.scale !== undefined && candidate.scale !== query.scale) return false;
  if (needle.length === 0) return true;
  const haystack = `${candidate.name} ${candidate.locationText ?? ""}`.toLowerCase();
  return haystack.includes(needle);
}

/** Search candidates by location/type. Every returned result carries real provenance. */
export function search(candidates: readonly SearchCandidate[], query: SearchQuery): SearchOutcome {
  const needle = query.text.trim().toLowerCase();
  const results: SearchResult[] = [];
  const excluded: SearchExclusion[] = [];

  for (const candidate of candidates) {
    if (!matchesQuery(candidate, query, needle)) continue;
    if (!hasValidProvenance(candidate.provenance)) {
      excluded.push({
        id: candidate.id,
        reason: "missing_provenance",
        detail: `Candidate "${candidate.id}" matched the query but has no valid provenance and cannot be returned as a result.`,
      });
      continue;
    }
    results.push({
      id: candidate.id,
      name: candidate.name,
      scale: candidate.scale,
      recordType: candidate.recordType,
      locationText: candidate.locationText,
      provenance: candidate.provenance,
    });
  }

  return { results, excluded };
}
