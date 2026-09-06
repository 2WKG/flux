/**
 * Mounts the scenario edit panel inside the one App and gives it a real
 * round-trip.
 *
 * `ScenarioEditPanel` is presentational: it holds no request. This container
 * owns the ordered edit sequence and submits it through the shared interactive
 * client's `POST /interactive/scenario/edit`, then maps the result into the
 * panel's three server states. When the interactive router is not mounted on
 * the serving origin the request fails and the panel refuses **by name** --
 * the unavailable copy states the missing dependency -- rather than showing a
 * verdict the browser made up.
 *
 * Before this existed the panel had no importer, so `npm run build` tree-shook
 * it out and no user could reach it.
 * `test/scenario-edit-mounted.test.mjs` asserts the built bundle carries it.
 */
import { useCallback, useState } from "react";
import { createInteractiveClient, type InteractiveClient } from "../data/interactive-client";
import {
  ScenarioEditPanel,
  type GridEdit,
  type ScenarioEditServerState,
  type ServerFeasibilityVerdict,
} from "./ScenarioEditPanel";

const DEFAULT_CLIENT = createInteractiveClient();

/** The unavailable reason when no interactive route answered. */
export const NO_EDIT_ENDPOINT =
  "No stable scenario edit endpoint is mounted, so no feasibility verdict is available.";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * Read the server's own feasibility rows. A row that does not carry a server
 * verdict is dropped, never reinterpreted: the browser has no verdict of its
 * own to fall back on.
 */
export function serverVerdicts(payload: unknown): readonly ServerFeasibilityVerdict[] {
  if (!isRecord(payload) || !Array.isArray(payload.feasibility)) return [];
  const accepted: ServerFeasibilityVerdict[] = [];
  for (const row of payload.feasibility) {
    if (!isRecord(row)) continue;
    const { verdict, reason, op_index: opIndex, stage } = row;
    if (verdict !== "valid" && verdict !== "invalid" && verdict !== "unknown") continue;
    if (typeof reason !== "string" || reason.length === 0) continue;
    accepted.push({
      verdict,
      reason,
      ...(typeof opIndex === "number" && Number.isInteger(opIndex) ? { op_index: opIndex } : {}),
      ...(typeof stage === "string" && stage.length > 0 ? { stage } : {}),
    });
  }
  return accepted;
}

export function serverStateFor(state: { kind: string; data?: unknown; message?: string }): ScenarioEditServerState {
  switch (state.kind) {
    case "loading":
      return { kind: "loading" };
    case "ready": {
      const payload = state.data;
      const editHash = isRecord(payload) && typeof payload.edit_hash === "string" ? payload.edit_hash : undefined;
      return { kind: "ready", ...(editHash === undefined ? {} : { edit_hash: editHash }), feasibility: serverVerdicts(payload) };
    }
    case "unavailable":
      return { kind: "unavailable", reason: state.message ?? NO_EDIT_ENDPOINT };
    default:
      return { kind: "error", reason: state.message ?? "The scenario edit request did not return a usable result." };
  }
}

export interface ScenarioEditContainerProps {
  readonly baseScenarioId: string;
  /** Injected in tests; the default is the one shared HTTP boundary. */
  readonly client?: InteractiveClient;
}

export function ScenarioEditContainer({ baseScenarioId, client = DEFAULT_CLIENT }: ScenarioEditContainerProps) {
  const [scenarioId, setScenarioId] = useState(baseScenarioId);
  const [ops, setOps] = useState<readonly GridEdit[]>([]);
  const [serverState, setServerState] = useState<ScenarioEditServerState>({
    kind: "unavailable",
    reason: NO_EDIT_ENDPOINT,
  });

  const submit = useCallback(() => {
    setServerState({ kind: "loading" });
    void client
      .editScenario({ scenarioId, edits: ops as unknown as readonly never[] })
      .then((state) => setServerState(serverStateFor(state)));
  }, [client, ops, scenarioId]);

  return (
    <section className="scenario-edits" aria-label="Scenario edit composer">
      <ScenarioEditPanel
        baseScenarioId={scenarioId}
        onBaseScenarioIdChange={setScenarioId}
        ops={ops}
        onOpsChange={setOps}
        serverState={serverState}
      />
      <button type="button" onClick={submit} disabled={ops.length === 0}>
        Submit to the scenario edit service
      </button>
    </section>
  );
}
