import { useEffect, useMemo, useRef, useState } from "react";
import type {
  ArtifactRef,
  CascadeData,
  CriticalLoadLoss,
  TrippedElement,
  UnavailableCode,
} from "../contracts/copilot-tools";
import { STATUS_COPY } from "../source-truth";

/**
 * The cascade vocabulary has exactly one owner: `web/src/contracts/copilot-tools`,
 * generated from `copilot/tools/schemas.py`. `web/src/contracts/README.md` says
 * so in as many words, so this panel imports `CascadeData`, `TrippedElement`,
 * `CriticalLoadLoss`, `ArtifactRef` and `UnavailableCode` instead of restating
 * them. Nothing below widens a frozen union or adds a field the contract does
 * not publish; the earlier hand-written copy (and its invented `county_impacts`
 * surface) is deleted rather than relabelled.
 *
 * The only types written here are the two HTTP *request* payloads and the
 * response envelope, which the tool contract does not describe because they
 * belong to the route layer: PR #331 (`codex/2wkg-436-437-http-clean`,
 * `copilot/interactive_routes.py`) mounts `POST /interactive/scenario/edit` and
 * `POST /interactive/cascade` and wraps every result in `_result()`. Its
 * `scenario_id` is a free string (`"interactive"`), not the tool contract's
 * `ScenarioId` union, so `RunCascadeInput` is deliberately not reused here.
 */
export type CascadeElementKind = TrippedElement["kind"];

export type CascadeSelectableElement = Readonly<{
  id: string;
  label: string;
  kind: CascadeElementKind;
  disabled?: boolean;
}>;

/** `ScenarioEditRequest` in PR #331's `copilot/interactive_routes.py`. */
export type ScenarioEditRequest = Readonly<{
  base_scenario_id: string;
  hour: number;
  seed: number;
  ops: readonly Readonly<{ op: "outage"; element_id: string }>[];
}>;

/** `CascadeRequest` in PR #331's `copilot/interactive_routes.py`. */
export type CascadeRequest = Readonly<{
  element_ids: readonly string[];
  scenario_id: string;
  hour: number;
  seed: number;
  edit_hash?: string;
}>;

/** PR #331's `_result()` envelope, byte for byte. */
export type InteractiveEnvelope<T> = Readonly<{
  data: T;
  model_fidelity: string;
  network_provenance: string;
  limitations: readonly string[];
}>;

export type ScenarioEditData = Readonly<{
  edit_hash: string;
}>;

export type CascadeStage = Readonly<{
  stage: number;
  tripped: readonly TrippedElement[];
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
  runCascade: (request: CascadeRequest, signal: AbortSignal) => Promise<InteractiveEnvelope<CascadeData>>;
  onAcceptedResult?: (result: InteractiveEnvelope<CascadeData>) => void;
  className?: string;
  budgetSeconds?: number;
}>;

type PanelState =
  | Readonly<{ phase: "idle" }>
  | Readonly<{ phase: "editing" }>
  | Readonly<{ phase: "running" }>
  | Readonly<{ phase: "cancelled" }>
  | Readonly<{ phase: "unavailable"; code: UnavailableCode | null; message: string }>
  | Readonly<{ phase: "error"; message: string }>;

/** PR #331 constrains `edit_hash` to `^[a-f0-9]{16,64}$`; anything else is not that hash. */
const EDIT_HASH = /^[a-f0-9]{16,64}$/;

function uniqueIds(ids: readonly string[]): string[] {
  return [...new Set(ids)];
}

/** Groups only the solver-supplied stages; no browser timing or ordering is invented. */
export function cascadeStages(result: CascadeData): readonly CascadeStage[] {
  const grouped = new Map<number, TrippedElement[]>();
  for (const trip of result.tripped_element_ids) {
    const atStage = grouped.get(trip.stage) ?? [];
    atStage.push(trip);
    grouped.set(trip.stage, atStage);
  }
  return [...grouped.entries()]
    .sort(([left], [right]) => left - right)
    .map(([stage, tripped]) => ({ stage, tripped }));
}

/**
 * The human label for a `network_provenance` token. CLAUDE.md ("ACTIVSg2000 is
 * synthetic topology; label it in user-visible results") wants the label, not
 * the machine token. A token with no published label is named as unlabelled
 * rather than printed as if it were prose.
 */
const NETWORK_PROVENANCE_LABELS: Readonly<Record<string, string>> = {
  synthetic_activsg2000: "synthetic (ACTIVSg2000)",
};

export function networkProvenanceLabel(token: string): string {
  return NETWORK_PROVENANCE_LABELS[token] ?? `unlabelled provenance token “${token}”`;
}

function serverMessage(error: unknown): { kind: "unavailable" | "timeout" | "cancelled" | "failed"; message: string } {
  if (typeof error === "object" && error !== null) {
    const candidate = error as CascadeRequestError;
    if (candidate.kind === "unavailable" || candidate.kind === "timeout" || candidate.kind === "cancelled") {
      return { kind: candidate.kind, message: candidate.message ?? "The server did not make a cascade result available." };
    }
    if (typeof candidate.message === "string" && candidate.message.length > 0) {
      return { kind: "failed", message: candidate.message };
    }
  }
  return { kind: "failed", message: "The cascade request did not return a usable server result." };
}

/**
 * The four element kinds the frozen `TrippedElement.kind` union defines, and
 * nothing else. An unrecognised kind is refused by name: CLAUDE.md forbids a
 * plausible default, and "Transmission outage" for an unknown kind was one.
 */
const ELEMENT_MEANING: Readonly<Record<CascadeElementKind, string>> = {
  gen: "Provider outage",
  line: "Transmission line outage",
  trafo: "Transformer outage",
  bus: "Substation bus outage",
};

export function elementMeaning(kind: string): string {
  const meaning = ELEMENT_MEANING[kind as CascadeElementKind];
  if (meaning !== undefined) return meaning;
  return `${STATUS_COPY.unavailable} — the tool contract publishes no element kind “${kind}”, so its effect is not stated.`;
}

/** `artifact_id@artifact_version` for every artifact the server bound this run to. */
function evidenceLabel(provenance: readonly ArtifactRef[]): string {
  return provenance.map((ref) => `${ref.artifact_id}@${ref.artifact_version}`).join(", ");
}

function facilityLabel(facility: CriticalLoadLoss): string {
  return `${facility.name} (${facility.id}) · ${facility.kind} · hour ${facility.hour_lost}`;
}

function CountyRows({ result, visibleStage, finalStage }: { result: CascadeData; visibleStage: number | null; finalStage: number | undefined }) {
  // The server publishes `counties_dark` for the run, not per stage, so it is
  // shown only once every stage the server returned is on screen.
  if (visibleStage !== finalStage || result.counties_dark.length === 0) {
    return <p>No county impact was supplied for this playback point.</p>;
  }
  return <ul aria-label="Counties darkening">{result.counties_dark.map((county) => <li key={county}>{county}</li>)}</ul>;
}

function FacilityRows({ result, visibleStage, finalStage }: { result: CascadeData; visibleStage: number | null; finalStage: number | undefined }) {
  if (visibleStage !== finalStage || result.critical_loads_lost.length === 0) {
    return <p>No critical-facility loss was supplied for this playback point.</p>;
  }
  return <ul aria-label="Critical facilities losing supply">
    {result.critical_loads_lost.map((facility) => <li key={facility.id}>{facilityLabel(facility)}</li>)}
  </ul>;
}

/**
 * A server-evidence cascade controller. It deliberately has no `fetch` call:
 * the interactive client (`src/data/interactive-client.ts`) is the single HTTP
 * and validation boundary, and is injected as the two callbacks below.
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
  const [result, setResult] = useState<InteractiveEnvelope<CascadeData> | null>(null);
  const [visibleStage, setVisibleStage] = useState<number | null>(null);
  const active = useRef<{ generation: number; controller: AbortController } | null>(null);
  const generation = useRef(0);

  const stages = useMemo(() => result ? cascadeStages(result.data) : [], [result]);
  const finalStage = stages.length > 0 ? stages[stages.length - 1].stage : undefined;
  const provenance = result?.data.provenance ?? [];

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

    /**
     * The stated budget is armed, not merely printed. The request is issued with
     * the deadline and the Cancel controller composed into one signal, so a
     * hung server ends in a named state instead of leaving the panel in
     * `running` forever with only a manual Cancel.
     */
    const deadline = AbortSignal.timeout(budgetSeconds * 1_000);
    const signal = AbortSignal.any([controller.signal, deadline]);
    deadline.addEventListener("abort", () => {
      if (generation.current !== requestGeneration) return;
      generation.current += 1;
      active.current = null;
      setState({
        phase: "error",
        message: `The server did not return a cascade result within the stated ${budgetSeconds}-second budget. Nothing was accepted.`,
      });
    }, { once: true });

    /**
     * The generation counter is the single acceptance guard. `signal.aborted`
     * is deliberately not consulted as a second one: every abort path here
     * (Cancel, a superseding run, the deadline) bumps the generation first, so
     * a redundant abort check would let the generation half be deleted with no
     * test able to see it — probe 1b of the review on PR #295.
     */
    const superseded = () => generation.current !== requestGeneration;

    try {
      let editHash: string | undefined;
      if (prepareEdit) {
        const edit = await prepareEdit({
          base_scenario_id: scenarioId,
          hour,
          seed,
          ops: selected.map((element_id) => ({ op: "outage", element_id })),
        }, signal);
        if (superseded()) return;
        if (!EDIT_HASH.test(edit.data.edit_hash)) {
          setState({ phase: "error", message: "The server accepted the edit without an immutable edit hash." });
          generation.current += 1;
          active.current = null;
          return;
        }
        editHash = edit.data.edit_hash;
        setState({ phase: "running" });
      }
      const response = await runCascade({ element_ids: selected, scenario_id: scenarioId, hour, seed, edit_hash: editHash }, signal);
      if (superseded()) return;
      generation.current += 1;
      active.current = null;
      const unavailable = response.data.unavailable;
      if (response.data.status === "unavailable" || unavailable) {
        setState({
          phase: "unavailable",
          code: unavailable?.code ?? null,
          message: unavailable?.reason ?? "The server marked this cascade unavailable and supplied no reason.",
        });
        return;
      }
      // Server evidence is the point of this panel: with no artifact reference
      // a stage list would be indistinguishable from a fabricated envelope.
      if ((response.data.provenance ?? []).length === 0) {
        setState({
          phase: "unavailable",
          code: "insufficient_evidence",
          message: "The server returned a cascade result carrying no artifact provenance, so no frame can be traced to a server artifact.",
        });
        return;
      }
      setResult(response);
      setState({ phase: "idle" });
      onAcceptedResult?.(response);
    } catch (error) {
      if (superseded()) return;
      generation.current += 1;
      active.current = null;
      const failure = serverMessage(error);
      if (failure.kind === "cancelled") {
        setState({ phase: "cancelled" });
        return;
      }
      setState(failure.kind === "unavailable"
        ? { phase: "unavailable", code: null, message: failure.message }
        : { phase: "error", message: failure.message });
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
    {state.phase === "unavailable" && <p role="alert">
      {STATUS_COPY.unavailable} · code {state.code ?? "none supplied"}: {state.message}
    </p>}
    {state.phase === "error" && <p role="alert">{STATUS_COPY.request_failed}: {state.message}</p>}

    {result && <section aria-label="Server cascade result">
      <h3>Run {result.data.run_id}</h3>
      <p>Server-reported shed load: {result.data.lost_load_mw} MW across {result.data.steps} solver steps.</p>
      <p>Model: {result.model_fidelity}. Network: {networkProvenanceLabel(result.network_provenance)}.</p>
      <ul aria-label="Server artifacts backing this run">
        {provenance.map((ref) => <li key={`${ref.artifact_id}@${ref.artifact_version}`}>
          {ref.artifact_id} · version {ref.artifact_version} · {ref.source_kind} · {ref.source_ref}
        </li>)}
      </ul>
      {result.limitations.length > 0 && <details><summary>Server limitations</summary><ul>{result.limitations.map((item) => <li key={item}>{item}</li>)}</ul></details>}

      {stages.length > 0 ? <div>
        <button type="button" onClick={() => setVisibleStage((current) => stages.find((stage) => current === null || stage.stage > current)?.stage ?? current)} disabled={visibleStage === finalStage}>
          {visibleStage === null ? `Show stage ${stages[0].stage}` : visibleStage === finalStage ? "All stages shown" : "Show next stage"}
        </button>
        {visibleStage !== null && stages.filter((stage) => stage.stage <= visibleStage).map((stage) => <section key={stage.stage} aria-label={`Cascade stage ${stage.stage}`}>
          <h4>Stage {stage.stage}</h4>
          <p>Evidence: {evidenceLabel(provenance)}</p>
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
