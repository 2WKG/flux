import type { ClientState } from "../data/client-state";
import type { ReactNode } from "react";
import type { ArtifactRef } from "./copilot-contracts";

export function ArtifactProvenance({ provenance }: Readonly<{ provenance: readonly ArtifactRef[] }>) {
  if (provenance.length === 0) return <p>Source: no artifact provenance returned.</p>;
  return <ul aria-label="Artifact provenance">{provenance.map((artifact) => <li key={`${artifact.artifact_id}:${artifact.artifact_version}`}>
    {artifact.source_kind} · {artifact.artifact_id} · {artifact.artifact_version} · {artifact.source_ref}
  </li>)}</ul>;
}

export function ArtifactPanelState<T>({ state, children }: Readonly<{ state: ClientState<T>; children: (data: T) => ReactNode }>) {
  if (state.kind === "ready") return <>{children(state.data)}</>;
  const message = state.kind === "unavailable" || state.kind === "failed" || state.kind === "invalid" ? state.message : state.kind === "empty" ? "No artifact rows are available." : "Loading artifact…";
  return <section aria-live="polite"><strong>{state.kind}</strong><p>{message}</p></section>;
}
