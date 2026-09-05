import type { ClientState } from "../data/client-state";
import type { ReactNode } from "react";

export type Provenance = Readonly<{ source_kind: string; artifact_id: string; artifact_version: string }>;

export function ArtifactPanelState<T>({ state, children }: Readonly<{ state: ClientState<T>; children: (data: T) => ReactNode }>) {
  if (state.kind === "ready") return <>{children(state.data)}</>;
  const message = state.kind === "unavailable" || state.kind === "failed" || state.kind === "invalid" ? state.message : state.kind === "empty" ? "No artifact rows are available." : "Loading artifact…";
  return <section aria-live="polite"><strong>{state.kind}</strong><p>{message}</p></section>;
}
