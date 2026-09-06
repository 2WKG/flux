import type { ClientState } from "../data/client-state";
import type { ReactNode } from "react";
import type { ArtifactRef } from "./copilot-contracts";

export const NO_PROVENANCE_MESSAGE = "Source: no artifact provenance returned.";
export const HEURISTIC_CAVEAT = "Heuristic result: not a learned-model estimate.";
export const LOADING_MESSAGE = "Loading artifact…";
export const EMPTY_MESSAGE = "No artifact rows are available.";

export function ArtifactProvenance({ provenance }: Readonly<{ provenance: readonly ArtifactRef[] }>) {
  if (provenance.length === 0) return <p>{NO_PROVENANCE_MESSAGE}</p>;
  return <>
    <ul aria-label="Artifact provenance">{provenance.map((artifact) => <li key={`${artifact.artifact_id}:${artifact.artifact_version}`}>
      {artifact.source_kind} · {artifact.artifact_id} · {artifact.artifact_version} · {artifact.source_ref}
    </li>)}</ul>
    {provenance.some((artifact) => artifact.source_kind === "heuristic") && <p>{HEURISTIC_CAVEAT}</p>}
  </>;
}

export function ArtifactPanelState<T>({ state, children }: Readonly<{ state: ClientState<T>; children: (data: T) => ReactNode }>) {
  if (state.kind === "ready") return <>{children(state.data)}</>;
  const message = state.kind === "unavailable" || state.kind === "failed" || state.kind === "invalid" ? state.message : state.kind === "empty" ? EMPTY_MESSAGE : LOADING_MESSAGE;
  return <section aria-live="polite"><strong>{state.kind}</strong><p>{message}</p></section>;
}
