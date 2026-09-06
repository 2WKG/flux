import { useEffect, useMemo, useRef, useState } from "react";

/**
 * Structural contracts for the interactive client.  The client owns HTTP and
 * response validation; this panel only coordinates its two typed operations.
 * They match the `/interactive/scenario/edit` and `/interactive/cascade`
 * payloads so the client can be passed in without a UI-side adapter.
 */
export type CascadeElementKind = "generator" | "load" | "line" | "transformer";
export type CascadeCause = "forced" | "weather" | "overload" | "island";

export type CascadeSelectableElement = Readonly<{
  id: string;
  label: string;
  kind: CascadeElementKind;
  disabled?: boolean;
}>;

export type ScenarioEditRequest = Readonly<{
  base_scenario_id: string;
  hour: number;
  seed: number;
  ops: readonly Readonly<{ op: "outage"; element_id: string }>[];
}>;

export type CascadeRequest = Readonly<{
  element_ids: readonly string[];
  scenario_id: string;
  hour: number;
  seed: number;
  edit_hash?: string;
}>;

export type InteractiveEnvelope<T> = Readonly<{
  data: T;
  model_fidelity: string;
  network_provenance: string;
  limitations: readonly string[];
}>;

export type ScenarioEditData = Readonly<{
  edit_hash: string;
}>;

export type CascadeTrip = Readonly<{
  element_id: string;
  kind: string;
  cause: CascadeCause;
  stage: number;
}>;

/** Optional enriched county details are rendered only when the server sends them. */
export type CascadeCountyImpact = Readonly<{
  county_fips: string;
  stage?: number;
  lost_mw?: number;
  customers_out?: number;
  fraction_dark?: number;
}>;

export type CascadeFacilityImpact = Readonly<{
  id?: string;
  name?: string;
  kind?: string;
  hour_lost?: number;
  stage?: number;
}>;

/**
 * `counties_dark` and `critical_loads_lost` preserve the current core shape;
 * rich counterparts make later server evidence available without fabricating
 * county customer counts or facility timings in the browser.
 */
export type InteractiveCascadeData = Readonly<{
  run_id: string;
  scenario_id: string;
  hour: number;
  tripped_element_ids: readonly CascadeTrip[];
  lost_load_mw?: number;
  counties_dark?: readonly string[];
  county_impacts?: readonly CascadeCountyImpact[];
  critical_loads_lost?: readonly (string | CascadeFacilityImpact)[];
  status?: "available" | "unavailable";
  unavailable?: Readonly<{ reason?: string }> | null;
}>;

export type CascadeStage = Readonly<{
  stage: number;
  tripped: readonly CascadeTrip[];
}>;

export type CascadeRequestError = Readonly<{
  kind?: "unavailable" | "timeout" | "cancelled" | "failed";
  message?: string;
}>;

export type CascadePlaybackPanelProps = Readonly<{
  elements: readonly CascadeSelectableElement[];
  scenarioId: string;
  hour: number;
  seed?: number;
  selectedElementIds?: readonly string[];
  defaultSelectedElementIds?: readonly string[];
  onSelectedElementIdsChange?: (elementIds: readonly string[]) => void;
  /** The client implementation performs POST `/interactive/scenario/edit`. */
  prepareEdit?: (request: ScenarioEditRequest, signal: AbortSignal) => Promise<InteractiveEnvelope<ScenarioEditData>>;
  /** The client implementation performs POST `/interactive/cascade`. */
  runCascade: (request: CascadeRequest, signal: AbortSignal) => Promise<InteractiveEnvelope<InteractiveCascadeData>>;
  onAcceptedResult?: (result: InteractiveEnvelope<InteractiveCascadeData>) => void;
  className?: string;
  budgetSeconds?: number;
}>;

type PanelState =
  | Readonly<{ phase: "idle" }>
  | Readonly<{ phase: "editing" }>
  | Readonly<{ phase: "running" }>
  | Readonly<{ phase: "cancelled" }>
  | Readonly<{ phase: "unavailable"; message: string }>
  | Readonly<{ phase: "error"; message: string }>;

function uniqueIds(ids: readonly string[]): string[] {
  return [...new Set(ids)];
}

/** Groups only the solver-supplied stages; no browser timing or ordering is invented. */
export function cascadeStages(result: InteractiveCascadeData): readonly CascadeStage[] {
  const grouped = new Map<number, CascadeTrip[]>();
  for (const trip of result.tripped_element_ids) {
    const atStage = grouped.get(trip.stage) ?? [];
    atStage.push(trip);
    grouped.set(trip.stage, atStage);
  }
  return [...grouped.entries()]
    .sort(([left], [right]) => left - right)
    .map(([stage, tripped]) => ({ stage, tripped }));
}

function serverMessage(error: unknown): { kind: "unavailable" | "timeout" | "failed"; message: string } {
  if (typeof error === "object" && error !== null) {
    const candidate = error as CascadeRequestError;
    if (candidate.kind === "unavailable" || candidate.kind === "timeout") {
      return { kind: candidate.kind, message: candidate.message ?? "The server did not make a cascade result available." };
    }
    if (typeof candidate.message === "string") return { kind: "failed", message: candidate.message };
  }
  return { kind: "failed", message: "The cascade request did not return a usable server result." };
}

function elementMeaning(kind: CascadeElementKind): string {
  if (kind === "generator") return "Provider outage";
  if (kind === "load") return "Consumer outage — changes demand; wait for the server result";
  return "Transmission outage";
}

function facilityLabel(facility: string | CascadeFacilityImpact): string {
  if (typeof facility === "string") return facility;
  return facility.name ?? facility.id ?? "Unnamed facility returned by server";
}

function CountyRows({ result, visibleStage, finalStage }: { result: InteractiveCascadeData; visibleStage: number | null; finalStage: number | undefined }) {
  const impacts = result.county_impacts ?? [];
  const shown = impacts.filter((impact) => impact.stage === undefined
    ? visibleStage === finalStage
    : visibleStage !== null && impact.stage <= visibleStage);
  if (shown.length > 0) return <ul aria-label="Counties darkening">
    {shown.map((impact) => <li key={`${impact.county_fips}-${impact.stage ?? "final"}`}>
      {impact.county_fips}
      {typeof impact.customers_out === "number" ? ` · ${impact.customers_out} customers out` : ""}
      {typeof impact.lost_mw === "number" ? ` · ${impact.lost_mw} MW lost` : ""}
    </li>)}
  </ul>;
  const counties = result.counties_dark ?? [];
  if (visibleStage !== finalStage || counties.length === 0) return <p>No county impact was supplied for this playback point.</p>;
  return <ul aria-label="Counties darkening">{counties.map((county) => <li key={county}>{county}</li>)}</ul>;
}

function FacilityRows({ result, visibleStage, finalStage }: { result: InteractiveCascadeData; visibleStage: number | null; finalStage: number | undefined }) {
  const facilities = result.critical_loads_lost ?? [];
  const shown = facilities.filter((facility) => typeof facility === "string"
    ? visibleStage === finalStage
    : facility.stage === undefined ? visibleStage === finalStage : visibleStage !== null && facility.stage <= visibleStage);
  if (shown.length === 0) return <p>No critical-facility loss was supplied for this playback point.</p>;
  return <ul aria-label="Critical facilities losing supply">{shown.map((facility, index) => <li key={`${facilityLabel(facility)}-${index}`}>
    {facilityLabel(facility)}
    {typeof facility !== "string" && typeof facility.hour_lost === "number" ? ` · hour ${facility.hour_lost}` : ""}
  </li>)}</ul>;
}

/**
 * A server-evidence cascade controller. It deliberately has no `fetch` call:
 * the interactive client is the single HTTP and validation boundary.
 */
export function CascadePlaybackPanel({
  elements,
  scenarioId,
  hour,
  seed = 0,
  selectedElementIds,
  defaultSelectedElementIds = [],
  onSelectedElementIdsChange,
  prepareEdit,
  runCascade,
  onAcceptedResult,
  className,
  budgetSeconds = 10,
}: CascadePlaybackPanelProps) {
  const [uncontrolledIds, setUncontrolledIds] = useState(() => uniqueIds(defaultSelectedElementIds));
  const selected = selectedElementIds === undefined ? uncontrolledIds : uniqueIds(selectedElementIds);
  const [state, setState] = useState<PanelState>({ phase: "idle" });
  const [result, setResult] = useState<InteractiveEnvelope<InteractiveCascadeData> | null>(null);
  const [visibleStage, setVisibleStage] = useState<number | null>(null);
  const active = useRef<{ generation: number; controller: AbortController } | null>(null);
  const generation = useRef(0);

  const stages = useMemo(() => result ? cascadeStages(result.data) : [], [result]);
  const finalStage = stages.length > 0 ? stages[stages.length - 1].stage : undefined;

  useEffect(() => () => active.current?.controller.abort(), []);

  const setSelection = (next: readonly string[]) => {
    const unique = uniqueIds(next);
    if (selectedElementIds === undefined) setUncontrolledIds(unique);
    onSelectedElementIdsChange?.(unique);
  };

  const toggleElement = (elementId: string) => setSelection(selected.includes(elementId)
    ? selected.filter((id) => id !== elementId)
    : [...selected, elementId]);

  const cancel = () => {
    const running = active.current;
    if (!running) return;
    generation.current += 1;
    running.controller.abort();
    active.current = null;
    setResult(null);
    setVisibleStage(null);
    setState({ phase: "cancelled" });
  };

  const start = async () => {
    if (selected.length === 0 || state.phase === "editing" || state.phase === "running") return;
    active.current?.controller.abort();
    const controller = new AbortController();
    const requestGeneration = generation.current + 1;
    generation.current = requestGeneration;
    active.current = { generation: requestGeneration, controller };
    setResult(null);
    setVisibleStage(null);
    setState({ phase: prepareEdit ? "editing" : "running" });

    try {
      let editHash: string | undefined;
      if (prepareEdit) {
        const edit = await prepareEdit({
          base_scenario_id: scenarioId,
          hour,
          seed,
          ops: selected.map((element_id) => ({ op: "outage", element_id })),
        }, controller.signal);
        if (controller.signal.aborted || generation.current !== requestGeneration) return;
        if (!edit.data.edit_hash) {
          setState({ phase: "error", message: "The server accepted the edit without an immutable edit hash." });
          active.current = null;
          return;
        }
        editHash = edit.data.edit_hash;
        setState({ phase: "running" });
      }
      const response = await runCascade({ element_ids: selected, scenario_id: scenarioId, hour, seed, edit_hash: editHash }, controller.signal);
      if (controller.signal.aborted || generation.current !== requestGeneration) return;
      active.current = null;
      if (response.data.status === "unavailable" || response.data.unavailable) {
        setState({ phase: "unavailable", message: response.data.unavailable?.reason ?? "The server marked this cascade unavailable." });
        return;
      }
      setResult(response);
      setState({ phase: "idle" });
      onAcceptedResult?.(response);
    } catch (error) {
      if (controller.signal.aborted || generation.current !== requestGeneration) return;
      active.current = null;
      const failure = serverMessage(error);
      setState(failure.kind === "unavailable" ? { phase: "unavailable", message: failure.message } : { phase: "error", message: failure.message });
    }
  };

  const canRun = selected.length > 0 && state.phase !== "editing" && state.phase !== "running";
  return <section className={className} aria-label="Cascade playback" data-cascade-phase={state.phase}>
    <header>
      <p>Interactive crisis mode</p>
      <h2>Choose outages, then replay the server result</h2>
      <p>Each run uses the synthetic network and the server’s DC-screening result. The server budget is up to {budgetSeconds} seconds.</p>
    </header>

    <fieldset disabled={state.phase === "editing" || state.phase === "running"}>
      <legend>Elements to take offline</legend>
      {elements.map((element) => <label key={element.id}>
        <input
          type="checkbox"
          checked={selected.includes(element.id)}
          disabled={element.disabled}
          onChange={() => toggleElement(element.id)}
        />
        {element.label} · {elementMeaning(element.kind)}
      </label>)}
    </fieldset>

    <div>
      <button type="button" onClick={() => { void start(); }} disabled={!canRun}>Run selected outages</button>
      {(state.phase === "editing" || state.phase === "running") && <button type="button" onClick={cancel}>Cancel run</button>}
    </div>

    {state.phase === "editing" && <p role="status">Preparing the immutable outage edit with the server.</p>}
    {state.phase === "running" && <p role="status">The server is solving the cascade. No result is shown until it returns.</p>}
    {state.phase === "cancelled" && <p role="status">Request cancelled. No cascade result was accepted.</p>}
    {state.phase === "unavailable" && <p role="alert">Cascade unavailable: {state.message}</p>}
    {state.phase === "error" && <p role="alert">Cascade request failed: {state.message}</p>}

    {result && <section aria-label="Server cascade result">
      <h3>Run {result.data.run_id}</h3>
      <p>{typeof result.data.lost_load_mw === "number" ? `Server-reported shed load: ${result.data.lost_load_mw} MW.` : "The server did not report shed load."}</p>
      <p>Model: {result.model_fidelity}. Network: {result.network_provenance}.</p>
      {result.limitations.length > 0 && <details><summary>Server limitations</summary><ul>{result.limitations.map((item) => <li key={item}>{item}</li>)}</ul></details>}

      {stages.length > 0 ? <div>
        <button type="button" onClick={() => setVisibleStage((current) => stages.find((stage) => current === null || stage.stage > current)?.stage ?? current)} disabled={visibleStage === finalStage}>
          {visibleStage === null ? `Show stage ${stages[0].stage}` : visibleStage === finalStage ? "All stages shown" : "Show next stage"}
        </button>
        {visibleStage !== null && stages.filter((stage) => stage.stage <= visibleStage).map((stage) => <section key={stage.stage} aria-label={`Cascade stage ${stage.stage}`}>
          <h4>Stage {stage.stage}</h4>
          <ul aria-label={`Tripped elements at stage ${stage.stage}`}>{stage.tripped.map((trip) => <li key={`${trip.element_id}-${trip.stage}`}>
            {trip.element_id} · {trip.kind} · cause: {trip.cause}
          </li>)}</ul>
        </section>)}
      </div> : <p>The server reported no ordered trip stages.</p>}

      <section><h4>Counties darkening</h4><CountyRows result={result.data} visibleStage={visibleStage} finalStage={finalStage} /></section>
      <section><h4>Critical facilities losing supply</h4><FacilityRows result={result.data} visibleStage={visibleStage} finalStage={finalStage} /></section>
    </section>}
  </section>;
}
