/**
 * Present the ordered, generic `/ask` trace at the seam where a future
 * interactive-simulation transport can be mounted.
 *
 * The v1 ask event contract names tool calls/results and terminal errors, but
 * it does not name a simulation action, its provider, a scene attribution, or
 * a reversal operation. This component therefore shows those four capabilities
 * as unavailable instead of inferring them from a tool name, prose, or an
 * arbitrary result object. It is intentionally presentational: it neither
 * opens a stream nor mutates a scene.
 */
import type { ErrorEvent, RunEvent, ToolCallEvent, ToolResultEvent } from "../ask/run-state/types";

export type SimulationCapability =
  | "simulation_action"
  | "provider"
  | "scene_attribution"
  | "reversal";

/** A capability absent from the received generic ask event data. */
export interface UnavailableSimulationCapability {
  readonly availability: "unavailable";
  readonly reason: "absent_from_received_ask_event_data";
}

export interface AgentSimulationAdapterProps {
  /** Arrival-ordered, reducer-validated v1 `/ask` events supplied by a parent. */
  readonly events: readonly RunEvent[];
}

type TraceEvent = ToolCallEvent | ToolResultEvent | ErrorEvent;

const capabilityCopy: Readonly<Record<SimulationCapability, readonly [string, string]>> = {
  simulation_action: ["Simulation action", "No explicit simulation action is present in the received /ask event data."],
  provider: ["Provider", "No provider identity is present in the received /ask event data."],
  scene_attribution: ["Scene attribution", "No scene attribution is present in the received /ask event data."],
  reversal: ["Reversal", "No reversal capability is present in the received /ask event data."],
};

const unavailable: UnavailableSimulationCapability = {
  availability: "unavailable",
  reason: "absent_from_received_ask_event_data",
};

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

  return (
    <section aria-label="Agent simulation status" data-agent-simulation-adapter="ask-v1">
      <h2>Agent simulation</h2>
      <dl>
        {(Object.entries(capabilityCopy) as readonly [SimulationCapability, readonly [string, string]][]).map(([capability, [label, detail]]) => (
          <div
            key={capability}
            data-agent-simulation-capability={capability}
            data-agent-simulation-availability={unavailable.availability}
            data-agent-simulation-reason={unavailable.reason}
          >
            <dt>{label}</dt>
            <dd>{detail}</dd>
          </div>
        ))}
      </dl>
      <ol aria-label="Received ask tool and error events">
        {trace.map((event) => (
          <li key={`${event.seq}:${event.type}`} data-ask-event-type={event.type} data-ask-event-seq={event.seq}>
            {traceSummary(event)}
          </li>
        ))}
      </ol>
    </section>
  );
}
