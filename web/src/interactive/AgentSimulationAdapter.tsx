/**
 * Determine, from the ordered generic `/ask` trace, which interactive-simulation
 * capabilities the received data actually carries.
 *
 * Two of the four capabilities are published by the frozen tool contract and are
 * read from it, never restated here:
 *
 * - **simulation action** — `ToolName` in `../contracts/copilot-tools` names
 *   `run_cascade`, `score_site`, `predict_outage` and `compare_interventions`,
 *   so a `tool_call`/`tool_result` carrying one of those names *is* a named
 *   simulation action with a typed input and output.
 * - **scene attribution** — every tool output carries
 *   `provenance?: ArtifactRef[]` (`artifact_id`, `artifact_version`,
 *   `source_kind`, `source_ref`). That is the attribution, and this component
 *   reads it out of the typed `tool_result.result` instead of discarding it.
 *
 * The other two — **provider identity** and a **reversal** operation — are
 * genuinely absent from the v1 contract, so they stay `unavailable` with the
 * frozen token and the finer machine reason carried alongside it.
 *
 * On top of that, the approved additive action nested in a successful
 * `tool_result.result.scene_action` is accepted only in its exact shape.
 *
 * Why this is not `../ask/run-state/RunTrace`: `RunTrace` owns the run's phase,
 * its cancellation affordance and the raw tool payloads. This component renders
 * neither; it renders the contract determination above, which `RunTrace` does
 * not make. `web/src/pages/MainPage.tsx` mounts both, `RunTrace` first.
 *
 * It is presentational: it neither opens a stream nor mutates a scene.
 */
import type { ArtifactRef } from "../contracts/copilot-tools";
import { isArtifactSourceKind, isSimulationToolName } from "../contracts/tool-names";
import type { AssetStatus } from "../labels";
import type { ErrorEvent, RunEvent, ToolCallEvent, ToolResultEvent } from "../ask/run-state/types";

export type SimulationCapability =
  | "simulation_action"
  | "provider"
  | "scene_attribution"
  | "reversal";

/**
 * A capability absent from the received generic ask event data.
 *
 * `availability` is the frozen `unavailable` token from `src/labels.ts`;
 * `reason` is the finer machine cause carried *alongside* it, never instead of
 * it, the way `src/failure-states/adapters.ts` already does.
 */
export interface UnavailableSimulationCapability {
  readonly availability: Extract<AssetStatus, "unavailable">;
  readonly reason: "absent_from_received_ask_event_data";
}

/** One additive action declared in a successful, attributed `tool_result`. */
export interface ReceivedSceneAction {
  readonly actionId: string;
  readonly kind: "scenario_edit" | "cascade";
  readonly toolCallId: string;
  readonly editHash?: string;
  readonly cascadeId?: string;
  readonly reversible: true;
  readonly status: "available" | "unavailable";
  readonly reason?: string;
}

export interface AgentSimulationAdapterProps {
  /** Arrival-ordered, reducer-validated v1 `/ask` events supplied by a parent. */
  readonly events: readonly RunEvent[];
}

type TraceEvent = ToolCallEvent | ToolResultEvent | ErrorEvent;

const capabilityCopy: Readonly<Record<SimulationCapability, readonly [string, string]>> = {
  simulation_action: ["Simulation action", "No published simulation tool and no attributed scene action are present in the received /ask event data."],
  provider: ["Provider", "No provider identity is present in the received /ask event data."],
  scene_attribution: ["Scene attribution", "No provenance artifact reference is present in the received /ask event data."],
  reversal: ["Reversal", "No reversal capability is present in the received /ask event data."],
};

const unavailable: UnavailableSimulationCapability = {
  availability: "unavailable",
  reason: "absent_from_received_ask_event_data",
};

const MISSING_CASCADE_ID_REASON =
  "The received cascade action has no stable cascade_id, so it cannot be applied.";

function record(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function requiredString(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function optionalString(value: unknown): string | undefined | null {
  return value === undefined ? undefined : requiredString(value);
}

/**
 * Read only the approved additive `tool_result.result.scene_action`
 * shape. Generic result objects remain opaque, and a malformed action is
 * deliberately indistinguishable from an absent one to callers.
 */
function sceneActionFromResult(event: ToolResultEvent): ReceivedSceneAction | null {
  if (!event.ok) return null;
  const result = record(event.result);
  const source = record(result?.scene_action);
  if (source === null) return null;

  const actionId = requiredString(source.action_id);
  const toolCallId = requiredString(source.tool_call_id);
  const kind = source.kind;
  const status = source.status;
  const editHash = optionalString(source.edit_hash);
  const cascadeId = optionalString(source.cascade_id);
  const reason = optionalString(source.reason);

  // A result may only declare the action that belongs to its own observed tool
  // call. `reversible` is preserved as a declared fact; this adapter supplies
  // no reversal command or scene callback.
  if (
    actionId === null
    || toolCallId === null
    || toolCallId !== event.call_id
    || (kind !== "scenario_edit" && kind !== "cascade")
    || source.reversible !== true
    || (status !== "available" && status !== "unavailable")
    || editHash === null
    || cascadeId === null
    || reason === null
  ) return null;

  // An edit hash names an edit, not a cascade run. A cascade that claims to be
  // available without its own stable identity stays explicitly unavailable;
  // this view must never substitute one identifier for the other.
  if (kind === "cascade" && status === "available" && cascadeId === undefined) {
    return {
      actionId,
      kind,
      toolCallId,
      ...(editHash === undefined ? {} : { editHash }),
      reversible: true,
      status: "unavailable",
      reason: MISSING_CASCADE_ID_REASON,
    };
  }

  return {
    actionId,
    kind,
    toolCallId,
    ...(editHash === undefined ? {} : { editHash }),
    ...(cascadeId === undefined ? {} : { cascadeId }),
    reversible: true,
    status,
    ...(reason === undefined ? {} : { reason }),
  };
}

/**
 * The `provenance: ArtifactRef[]` the frozen contract carries on every tool
 * output. Only complete references are kept: a partial one is dropped rather
 * than rendered with an invented id or version.
 */
function provenanceFromResult(event: ToolResultEvent): readonly ArtifactRef[] {
  if (!event.ok) return [];
  const result = record(event.result);
  const refs = result?.provenance;
  if (!Array.isArray(refs)) return [];
  const kept: ArtifactRef[] = [];
  for (const entry of refs) {
    const source = record(entry);
    if (source === null) continue;
    const artifactId = requiredString(source.artifact_id);
    const artifactVersion = requiredString(source.artifact_version);
    const sourceKind = requiredString(source.source_kind);
    const sourceRef = requiredString(source.source_ref);
    if (artifactId === null || artifactVersion === null || sourceKind === null || sourceRef === null) continue;
    if (!isArtifactSourceKind(sourceKind)) continue;
    kept.push({
      artifact_id: artifactId,
      artifact_version: artifactVersion,
      source_kind: sourceKind,
      source_ref: sourceRef,
    });
  }
  return kept;
}

function isTraceEvent(event: RunEvent): event is TraceEvent {
  return event.type === "tool_call" || event.type === "tool_result" || event.type === "error";
}

function traceSummary(event: TraceEvent): string {
  switch (event.type) {
    case "tool_call":
      return `${event.tool}: requested`;
    case "tool_result":
      return `${event.tool}: ${event.ok ? "completed" : "failed"}`;
    case "error":
      return `${event.error.code}: ${event.error.message}`;
  }
}

/**
 * A narrow mounting point for 436/437: consumers supply only the generic
 * ordered event list. There are deliberately no scene callbacks or inferred
 * simulation-result fields on this interface.
 */
export function AgentSimulationAdapter({ events }: AgentSimulationAdapterProps) {
  const trace = events.filter(isTraceEvent);
  const actions = events.flatMap((event) => event.type === "tool_result"
    ? [sceneActionFromResult(event)].filter((action): action is ReceivedSceneAction => action !== null)
    : []);
  const availableActions = actions.filter((action) => action.status === "available");
  const unavailableAction = actions.find((action) => action.status === "unavailable");
  // A published simulation tool name IS a named simulation action; refusing it
  // would be a wrong claim about data this component holds.
  const namedTools = [...new Set(trace
    .filter((event): event is ToolCallEvent | ToolResultEvent => event.type !== "error")
    .map((event) => event.tool)
    .filter(isSimulationToolName))];
  const actionAvailable = availableActions.length > 0 || namedTools.length > 0;
  const provenance = trace.flatMap((event) => event.type === "tool_result" ? [...provenanceFromResult(event)] : []);
  const attributionAvailable = provenance.length > 0;
  const availabilityOf = (capability: SimulationCapability) =>
    (capability === "simulation_action" && actionAvailable)
    || (capability === "scene_attribution" && attributionAvailable)
      ? "available"
      : unavailable.availability;

  return (
    <section aria-label="Agent simulation status" data-agent-simulation-adapter="ask-v1">
      <h2>Agent simulation</h2>
      <dl>
        {(Object.entries(capabilityCopy) as readonly [SimulationCapability, readonly [string, string]][]).map(([capability, [label, detail]]) => (
          <div
            key={capability}
            data-agent-simulation-capability={capability}
            data-agent-simulation-availability={availabilityOf(capability)}
            data-agent-simulation-reason={availabilityOf(capability) === "available"
              ? undefined
              : capability === "simulation_action" && unavailableAction?.reason !== undefined
                ? unavailableAction.reason
                : unavailable.reason}
          >
            <dt>{label}</dt>
            <dd>{capability === "simulation_action" && actionAvailable
              ? namedTools.length > 0
                ? `The received /ask events name published simulation tools: ${namedTools.join(", ")}.`
                : "An attributed simulation action is present in the received /ask event data."
              : capability === "scene_attribution" && attributionAvailable
                ? `Attributed to ${provenance.map((ref) => `${ref.artifact_id}@${ref.artifact_version}`).join(", ")}.`
                : capability === "simulation_action" && unavailableAction?.reason !== undefined
                  ? unavailableAction.reason
                  : detail}</dd>
          </div>
        ))}
      </dl>
      {actions.map((action) => (
        <article
          key={action.actionId}
          data-agent-scene-action={action.kind}
          data-agent-scene-action-id={action.actionId}
          data-agent-scene-action-status={action.status}
          data-agent-scene-action-tool-call-id={action.toolCallId}
          data-agent-scene-action-reversible={action.reversible}
        >
          <h3>{action.kind}</h3>
          <p>{action.status === "available" ? "Available" : "Unavailable"} action attributed to tool call {action.toolCallId}.</p>
          <p>Reversible: declared by the received action. No reversal operation is wired here.</p>
          {action.editHash ? <p>Edit hash: {action.editHash}</p> : null}
          {action.cascadeId ? <p>Cascade id: {action.cascadeId}</p> : null}
          {action.reason ? <p>{action.reason}</p> : null}
        </article>
      ))}
      <ol aria-label="Received ask tool and error events">
        {trace.map((event) => (
          <li key={event.seq} data-ask-event-type={event.type} data-ask-event-seq={event.seq}>
            {traceSummary(event)}
          </li>
        ))}
      </ol>
    </section>
  );
}
