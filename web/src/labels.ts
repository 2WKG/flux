/**
 * The six source-truth labels from the merged information architecture
 * (`docs/design/minnesota-demo-narrative-ia.md`, "Truth labels" table).
 *
 * This module is the single owner of the vocabulary so the shell, the
 * inspector, and the chat dock cannot drift into private copies of it. It
 * holds no product state: a server payload or an accepted artifact selects a
 * status, and the UI only renders the copy for whatever it was handed.
 */

/** Frozen UI statuses; only a supplied artifact or server result may select one. */
export type SourceStatus =
  | "source_supported"
  | "source_screened"
  | "hypothetical"
  | "synthetic"
  | "unavailable"
  | "request_failed";

/** The IA's user-visible copy for each token. */
export const SOURCE_STATUS_COPY: Record<SourceStatus, string> = {
  source_supported: "Source-supported",
  source_screened: "Source-screened",
  hypothetical: "Hypothetical",
  synthetic: "Synthetic",
  unavailable: "Unavailable",
  request_failed: "Request failed",
};

/**
 * The IA binds these two statuses to required accompanying copy: a missing
 * prerequisite and named next step for `unavailable`, and a safe message plus
 * the request ID for `request_failed`. A bare pill for either one is a
 * contract violation, so callers must supply the detail.
 */
export const SOURCE_STATUSES_REQUIRING_DETAIL = ["unavailable", "request_failed"] as const;

export type SourceStatusRequiringDetail = (typeof SOURCE_STATUSES_REQUIRING_DETAIL)[number];

export function requiresDetail(status: SourceStatus): status is SourceStatusRequiringDetail {
  return (SOURCE_STATUSES_REQUIRING_DETAIL as readonly SourceStatus[]).includes(status);
}
