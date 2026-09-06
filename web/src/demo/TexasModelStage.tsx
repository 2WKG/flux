import type { ReactNode } from "react";
import type { DemoAvailability, ProvenanceNote } from "./ControlRoom";

export interface ModelCascadeEvent {
  readonly elementId: string;
  readonly kind: string;
  readonly stage: number;
  readonly cause: string;
  readonly loadingPercent?: number;
}

export interface QualifiedModelCascade {
  readonly runId: string;
  readonly availability: DemoAvailability;
  readonly playbackQualified: boolean;
  readonly reasons: readonly string[];
  readonly lostLoadMw?: number;
  /** Kept as a source ID until a counties artifact resolves it. */
  readonly countyFips?: readonly string[];
  readonly events: readonly ModelCascadeEvent[];
  readonly provenance?: readonly ProvenanceNote[];
}

export interface ComponentFailureAction {
  readonly availability: DemoAvailability;
  readonly message: string;
  readonly selectedElementId?: string;
  readonly onSelectElement?: (elementId: string) => void;
  /** Present only when the mounted backend has declared the action capability. */
  readonly onRequestFailure?: () => void;
}

export interface TexasModelScene {
  readonly availability: DemoAvailability;
  readonly topologyLabel: string;
  readonly synthetic: boolean;
  readonly solver?: string;
  /** IDs belong to a separate synthetic model scene, never physical inventory. */
  readonly elementIds: readonly string[];
  /** IDs the server explicitly could not resolve in its canonical model mapping. */
  readonly unresolvedElementIds?: readonly string[];
  /** An independently declared synthetic model renderer, keyed to `elementIds`. */
  readonly visual?: ReactNode;
  readonly action?: ComponentFailureAction;
  readonly cascade?: QualifiedModelCascade;
  readonly limitations?: readonly string[];
}

/** Events are eligible only after qualification and only when IDs exist in this model scene. */
export function qualifiedSceneEvents(scene: TexasModelScene): readonly ModelCascadeEvent[] {
  return resolveSceneEvents(scene).resolved;
}

/** Preserves every reported timeline ID; unmatched IDs are disclosed, never guessed into a scene. */
export function resolveSceneEvents(scene: TexasModelScene): { readonly resolved: readonly ModelCascadeEvent[]; readonly notLocated: readonly ModelCascadeEvent[] } {
  if (!scene.cascade || scene.cascade.availability !== "available" || !scene.cascade.playbackQualified) return { resolved: [], notLocated: [] };
  const ids = new Set(scene.elementIds);
  const resolved: ModelCascadeEvent[] = [];
  const notLocated: ModelCascadeEvent[] = [];
  for (const event of scene.cascade.events) (ids.has(event.elementId) ? resolved : notLocated).push(event);
  return { resolved, notLocated };
}

export function TexasModelStage({ scene }: { scene: TexasModelScene }) {
  const resolution = resolveSceneEvents(scene);
  const events = resolution.resolved;
  const action = scene.action;
  return <section className="texas-model-stage" aria-label="Texas grid model scene" data-model-synthetic={String(scene.synthetic)}>
    <header><p className="control-room__eyebrow">Texas grid model</p><h3>{scene.topologyLabel}</h3><p>{scene.solver ?? "Solver unavailable"}</p></header>
    {scene.availability !== "unavailable" ? <>
      <p className="texas-model-stage__notice">This is a synthetic model-ID scene. It has no physical-inventory geometry binding.</p>
      {scene.unresolvedElementIds?.length ? <p className="control-room__unavailable" role="status">Not located in the synthetic model: {scene.unresolvedElementIds.join(", ")}</p> : null}
      {scene.visual ? <div className="texas-model-stage__visual" aria-label="Synthetic Texas model visual">{scene.visual}</div> : <p className="control-room__unavailable" role="status">Model visual unavailable: no independent synthetic-coordinate renderer has been supplied.</p>}
      {action ? <div className="texas-model-stage__action">
        <label>Selected model component
          <select value={action.selectedElementId ?? ""} onChange={(event) => action.onSelectElement?.(event.target.value)} disabled={action.availability !== "available" || !action.onSelectElement}>
            <option value="">Choose a model ID</option>
            {scene.elementIds.map((id) => <option key={id} value={id}>{id}</option>)}
          </select>
        </label>
        <button type="button" onClick={action.onRequestFailure} disabled={action.availability !== "available" || !action.selectedElementId || !action.onRequestFailure}>Request component failure</button>
        <p>{action.message}</p>
      </div> : null}
      {events.length > 0 && scene.cascade ? <div className="texas-model-stage__events" aria-label="Qualified cascade events">
        <p><strong>Qualified persisted run:</strong> {scene.cascade.runId}</p>
        {scene.cascade.lostLoadMw !== undefined ? <p>Lost load: {scene.cascade.lostLoadMw} MW</p> : null}
        {scene.cascade.countyFips?.length ? <p>Dark county FIPS: {scene.cascade.countyFips.join(", ")}</p> : null}
        {resolution.notLocated.length ? <p className="control-room__unavailable" role="status">Not located in this model scene: {resolution.notLocated.map((event) => event.elementId).join(", ")}</p> : null}
        <ol>{events.map((event) => <li key={`${event.stage}-${event.elementId}`}>Stage {event.stage}: {event.elementId} · {event.kind} · {event.cause}{event.loadingPercent === undefined ? "" : ` · ${event.loadingPercent}% loading`}</li>)}</ol>
      </div> : <p className="control-room__unavailable" role="status">Cascade playback unavailable: no qualified persisted event list matches this model scene.</p>}
    </> : <p className="control-room__unavailable" role="status">Texas model unavailable: {scene.limitations?.join(" ") ?? "The model scene has not been supplied."}</p>}
  </section>;
}
