import { useCallback, useEffect, useMemo, useReducer, useRef, useState, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import fixture from "../../data/demo/bundle.json";
import { deriveSourceTruth, sourceSummary, STATUS_COPY } from "./source-truth";
import { ChatDock, type ChatError, type ChatMessage, type ChatStatus } from "./chat/ChatDock";
import { EMPTY_SCENE_CONTEXT, type SceneContext } from "./chat/ask-contract";
import { RunTrace } from "./ask/run-state/RunTrace";
import { createRunState } from "./ask/run-state/reducer";
import type { RunIdentity, RunState } from "./ask/run-state/types";
import { ResultCards } from "./ask/results";
import type { AskResult } from "./ask/results/types";
import { FailureState } from "./failure-states/FailureState";
import { fromClientState } from "./failure-states/adapters";
import type { FailureStateInput } from "./failure-states/types";
import { Inspector } from "./inspector/Inspector";
import type { InspectorAsset } from "./inspector/types";
import { LayerControls } from "./layers/LayerControls";
import { descriptorsFor, type EvidenceDisclosure } from "./layers/descriptor-adapter";
import { buildRegistrySnapshots, LAYER_REGISTRY, type DataStatus } from "./layers/registry";
import { legendForLayer } from "./layers/legend";
import { createReadApiClient } from "./data/client-state";
import { loadRegistryDataStatuses } from "./data/layer-status";
import { loadScenarioAsset } from "./data/scenario-asset";
import { runAsk } from "./data/ask-stream";
import { resultsFromRun } from "./data/ask-result";
import { loadGridLayer, GRID_LAYERS, type GridState } from "./data/grid-client";
import type { SpatialItem, SpatialPage } from "./data/grid-inventory";
import { GridInventoryPanel, type GridLoad } from "./renderer/GridInventoryPanel";
import { ControlRoom, type ControlRoomProps, type RegionId } from "./demo";
import "./styles.css";

type Id = "baseline" | "a" | "b";
type View = "load" | "delta";
type Provenance = { sourceId: string; sourceRef: string; sourceVersion: string; scope: string; artifactId: string; inputHash: string };
type Scenario = {
  id: Id; label: string; status: "available"; modelMode: string; assumptionSetId: string;
  intervention: null | { id: string; capacityMw: number; modeledContributionMw: number; description: string };
  metrics: { shedMw: number; shedMwh: number; availableGenerationMw: number; demandMw: number; improvementMw: number; lineLoadings: Record<string, number> };
  units: { shedMw: string; shedMwh: string; availableGenerationMw: string; demandMw: string; improvementMw: string; lineLoading: string };
  provenance: Provenance; limitations: string[];
};
type Bus = { id: string; name: string; x: number; y: number };
type Line = { id: string; from: string; to: string };
type Candidate = { id: Id; name: string; busId: string; x: number; y: number; capacityMw: number; description: string };
type Bundle = {
  schemaVersion: number; fixtureHash: string;
  execution: { status: "available"; modelMode: string; assumptionSetId: string; assumptions: { name: string; demandMw: number; demandMultiplier: number; generationAvailabilityFraction: number; durationHours: number; notes: string[] }; provenance: Provenance; limitations: string[] };
  network: { buses: Bus[]; lines: Line[]; candidates: Candidate[] };
  scenarios: Record<Id, Scenario>;
};

function evidenceDisclosure(page: SpatialPage | undefined): EvidenceDisclosure | undefined {
  const item = page?.items[0];
  if (page === undefined || item === undefined) return undefined;
  const coverage = page.coverage[0];
  const coverageText = coverage === undefined
    ? `${page.page.total} published ${page.layer} records`
    : `${coverage.scope}: observed ${coverage.observed ?? "not reported"} of ${coverage.denominator ?? "not reported"}; unavailable ${coverage.unavailable ?? "not reported"}`;
  return {
    evidenceClass: "observed",
    evidence: {
      source: item.provenance.authority,
      vintage: item.provenance.source_version,
      coverage: coverageText,
      transformation: item.transform_provenance
        ? `${item.transform_provenance.method}: ${item.transform_provenance.source_crs} → ${item.transform_provenance.display_crs}`
        : "Server-provided EPSG:4326 display geometry",
      uncertainty: item.geometry_accuracy_basis ?? coverage?.reason ?? "The release supplied no additional uncertainty note.",
      syntheticTopologyCaveat: `${page.inventory_mode}; electrical model mode: ${page.electrical_model_mode}.`,
    },
  };
}

function evidenceDisclosuresForGridLoad(load: GridLoad): Readonly<Record<string, EvidenceDisclosure | undefined>> {
  if (load.kind !== "loaded") return {};
  const pages = new Map(load.pages.map((page) => [page.layer, page]));
  const line = evidenceDisclosure(pages.get("line"));
  return {
    topology: line,
    facilities: evidenceDisclosure(pages.get("generation") ?? pages.get("substation") ?? pages.get("storage")),
    provenance: line,
  };
}

const data = fixture as unknown as Bundle;
const ORDER: Id[] = ["baseline", "a", "b"];
const BUSES: Record<string, Bus> = Object.fromEntries(data.network.buses.map((bus) => [bus.id, bus]));
const BASELINE_LOADS = data.scenarios.baseline.metrics.lineLoadings;
const WORST_SHED = Math.max(...ORDER.map((id) => data.scenarios[id].metrics.shedMw));

/**
 * The screen's one primary state label, derived from the bundle's persisted
 * provenance by src/source-truth.ts. No surface writes its own status text.
 */
const SOURCE_TRUTH = deriveSourceTruth(data.execution.provenance);

/**
 * The dock's collapsed claim while no Copilot stream has been established.
 * `web/server.mjs` serves this artifact from a static origin with
 * `connect-src 'self'` and mounts no API of its own, so on the shipped demo it
 * stays true; behind an origin that does serve `/ask` it is replaced the moment
 * a stream returns.
 */
const OFFLINE_DOCK_LABEL = "Not available in this offline build";

/** `ASK_LIMITS.attemptIdPattern` is `^[A-Za-z0-9_-]{16,128}$`; this satisfies it. */
function newAttemptId(): string {
  const random = Math.random().toString(36).slice(2).padEnd(12, "0").slice(0, 12);
  return `attempt-${random}-${Date.now().toString(36)}`.replace(/[^A-Za-z0-9_-]/g, "-").slice(0, 128);
}

const READ_CLIENT = createReadApiClient();

const reducedMotion = () =>
  typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;

/** Utilization bands. The thresholds are presentation bands over the fixture's own percentages. */
function loadTone(loading: number): "low" | "mid" | "high" {
  return loading >= 90 ? "high" : loading >= 75 ? "mid" : "low";
}

/** Relief bands, in percentage points removed from a corridor versus the baseline run. */
function deltaTone(delta: number): "none" | "some" | "strong" {
  if (delta > -1) return "none";
  return delta <= -15 ? "strong" : "some";
}

/** Typographic minus (U+2212), so a relief figure never renders as a stray hyphen. */
const signed = (value: number) => (value > 0 ? `+${value}` : `−${Math.abs(value)}`);

/** Animate a value toward its target so a scenario switch reads as a change, not a redraw. */
function useCountUp(target: number, ms = 480): number {
  const [value, setValue] = useState(target);
  const current = useRef(target);
  useEffect(() => {
    const origin = current.current;
    if (origin === target || reducedMotion()) {
      current.current = target;
      setValue(target);
      return;
    }
    const start = performance.now();
    let frame = requestAnimationFrame(function step(now: number) {
      const progress = Math.min(1, (now - start) / ms);
      const eased = 1 - Math.pow(1 - progress, 3);
      const next = Math.round(origin + (target - origin) * eased);
      current.current = next;
      setValue(next);
      if (progress < 1) frame = requestAnimationFrame(step);
    });
    return () => cancelAnimationFrame(frame);
  }, [target, ms]);
  return value;
}

type Hover = { lineId: string; x: number; y: number } | null;

function Network({ selected, view, onSelect, hover, setHover }: {
  selected: Id; view: View; onSelect: (id: Id) => void; hover: Hover; setHover: (hover: Hover) => void;
}) {
  const loads = data.scenarios[selected].metrics.lineLoadings;
  const frame = useRef<HTMLDivElement>(null);

  const track = (lineId: string) => (event: { clientX: number; clientY: number }) => {
    const box = frame.current?.getBoundingClientRect();
    if (box) setHover({ lineId, x: event.clientX - box.left, y: event.clientY - box.top });
  };

  const focusLine = (line: Line) => () => {
    const box = frame.current?.getBoundingClientRect();
    const from = BUSES[line.from];
    const to = BUSES[line.to];
    // Keyboard focus has no pointer: anchor the readout to the corridor's own midpoint.
    if (box) setHover({ lineId: line.id, x: ((from.x + to.x) / 2 / 760) * box.width, y: ((from.y + to.y) / 2 / 540) * box.height });
  };

  return (
    <div className="frame" ref={frame} onMouseLeave={() => setHover(null)}>
      <svg viewBox="0 0 760 540" className="network" role="group" aria-label="Synthetic five-bus network. Each corridor reports its utilization and its change against the baseline run.">
        <defs>
          <radialGradient id="busGlow">
            <stop offset="0%" stopColor="#dceeff" stopOpacity="0.5" />
            <stop offset="100%" stopColor="#dceeff" stopOpacity="0" />
          </radialGradient>
        </defs>

        {data.network.lines.map((line) => {
          const from = BUSES[line.from];
          const to = BUSES[line.to];
          const loading = loads[line.id];
          const delta = loading - BASELINE_LOADS[line.id];
          const tone = view === "load" ? loadTone(loading) : deltaTone(delta);
          const midX = (from.x + to.x) / 2;
          const midY = (from.y + to.y) / 2;
          const active = hover?.lineId === line.id;
          return (
            <g
              key={line.id}
              className={`corridor tone-${tone}${active ? " active" : ""}`}
              tabIndex={0}
              role="button"
              aria-label={`${from.name} to ${to.name}: ${loading} percent utilization, ${delta === 0 ? "unchanged from" : `${signed(delta)} points versus`} baseline`}
              onMouseMove={track(line.id)}
              onFocus={focusLine(line)}
              onBlur={() => setHover(null)}
            >
              <line className="hit" x1={from.x} y1={from.y} x2={to.x} y2={to.y} />
              <line className="wire" x1={from.x} y1={from.y} x2={to.x} y2={to.y} strokeWidth={5 + (loading / 100) * 9} />
              <g className="reading" transform={`translate(${midX} ${midY - 15})`}>
                <rect x={-22} y={-13} width={44} height={20} rx={6} />
                <text>{view === "load" ? `${loading}%` : delta === 0 ? "0" : signed(delta)}</text>
              </g>
            </g>
          );
        })}

        {data.network.buses.map((bus) => (
          <g key={bus.id} className="bus">
            <circle cx={bus.x} cy={bus.y} r="34" fill="url(#busGlow)" />
            <circle cx={bus.x} cy={bus.y} r="11" />
            <text x={bus.x} y={bus.y + 34}>{bus.name}</text>
          </g>
        ))}

        {data.network.candidates.map((candidate) => {
          const chosen = selected === candidate.id;
          const scenario = data.scenarios[candidate.id];
          return (
            <g
              key={candidate.id}
              className={`pin${chosen ? " chosen" : ""}`}
              role="button"
              tabIndex={0}
              aria-pressed={chosen}
              aria-label={`${candidate.name}: ${candidate.capacityMw} megawatt candidate at ${BUSES[candidate.busId].name}. Modeled to cut unmet demand by ${scenario.metrics.improvementMw} megawatts.`}
              onClick={() => onSelect(candidate.id)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  onSelect(candidate.id);
                }
              }}
            >
              {chosen && <circle className="halo" cx={candidate.x} cy={candidate.y - 46} r="27" />}
              <circle className="disc" cx={candidate.x} cy={candidate.y - 46} r="19" />
              <text x={candidate.x} y={candidate.y - 40}>{candidate.id.toUpperCase()}</text>
              <text className="tag" x={candidate.x} y={candidate.y - 74}>+{candidate.capacityMw} MW</text>
            </g>
          );
        })}
      </svg>

      {hover && (() => {
        const line = data.network.lines.find((item) => item.id === hover.lineId);
        if (!line) return null;
        const loading = loads[line.id];
        const delta = loading - BASELINE_LOADS[line.id];
        return (
          <div className="tip" style={{ left: hover.x, top: hover.y }} role="status">
            <b>{BUSES[line.from].name} → {BUSES[line.to].name}</b>
            <div className="tip-row"><span>Utilization</span><em className={`tone-${loadTone(loading)}`}>{loading}%</em></div>
            <div className="tip-row">
              <span>vs baseline</span>
              <em className={delta < 0 ? "relief" : ""}>{delta === 0 ? "unchanged" : `${signed(delta)} pts`}</em>
            </div>
          </div>
        );
      })()}
    </div>
  );
}

function CompareRail({ selected, onSelect }: { selected: Id; onSelect: (id: Id) => void }) {
  return (
    <section className="rail" aria-label="Scenario comparison">
      {ORDER.map((id) => {
        const scenario = data.scenarios[id];
        const share = (scenario.metrics.shedMw / WORST_SHED) * 100;
        const best = scenario.metrics.improvementMw > 0 && scenario.metrics.improvementMw === Math.max(...ORDER.map((key) => data.scenarios[key].metrics.improvementMw));
        return (
          <button key={id} className={`card${id === selected ? " selected" : ""}`} onClick={() => onSelect(id)} aria-pressed={id === selected}>
            <div className="card-head">
              <span className="key">{id === "baseline" ? "00" : id.toUpperCase()}</span>
              <span className="name">{scenario.label}</span>
              {best && <span className="badge">largest modeled cut</span>}
            </div>
            <div className="card-figure">
              <strong>{scenario.metrics.shedMw}</strong>
              <small>{scenario.units.shedMw} unmet</small>
            </div>
            <div className="meter"><i style={{ width: `${share}%` }} /></div>
            <div className="card-foot">
              {scenario.intervention
                ? <>−{scenario.metrics.improvementMw} {scenario.units.improvementMw} vs baseline · {scenario.intervention.capacityMw} MW sited</>
                : <>reference run · no capacity added</>}
            </div>
          </button>
        );
      })}
    </section>
  );
}

/** The dock's only state transition, kept pure so the toggle path is testable without a DOM. */
export type ChatAction = "toggle";
export function chatReducer(open: boolean, action: ChatAction): boolean {
  return action === "toggle" ? !open : open;
}

/**
 * The dock's markup as a pure function of its open state. The body is always
 * rendered (hidden while collapsed) so `aria-controls` names a real element.
 */
export function ChatDockView({ open, onToggle, collapsedLabel = OFFLINE_DOCK_LABEL, children }: {
  open: boolean;
  onToggle: () => void;
  /**
   * What the collapsed dock says about its own availability. It defaults to
   * the offline claim and is only replaced once a request has actually shown
   * otherwise: "not available" is the honest state until proven wrong.
   */
  collapsedLabel?: string;
  /**
   * The evidence surface the dock hosts. When no children are supplied — the
   * dock rendered on its own, with nothing mounted in it — it states that,
   * which is the state its own copy describes.
   */
  children?: ReactNode;
}) {
  return (
    <section className={`chat-dock ${open ? "expanded" : "collapsed"}`} aria-label="Evidence chat dock">
      <button className="chat-toggle" onClick={onToggle} aria-expanded={open} aria-controls="chat-dock-body">
        <span>
          <span className="eyebrow">Evidence chat</span>
          <strong>{open ? "Chat contract and limits" : "Ask about visible evidence"}</strong>
        </span>
        <span className="chat-state">{open ? "Collapse" : collapsedLabel}</span>
      </button>
      <div id="chat-dock-body" className="chat-body" hidden={!open}>
        {children ?? <>
          <p>This offline synthetic preview has no Copilot endpoint, model result, or Minnesota artifact to query.</p>
          <p>When a server-backed evidence surface is available, this dock must show its tool trail, citations, status, and limitations instead of inventing an answer.</p>
        </>}
      </div>
    </section>
  );
}

export function App() {
  const [selected, setSelected] = useState<Id>("baseline");
  const [view, setView] = useState<View>("load");
  const [hover, setHover] = useState<Hover>(null);
  const [detail, setDetail] = useState(false);
  const [chatOpen, toggleChat] = useReducer(chatReducer, false);

  // --- Server-backed state. All of it lives in this shell; every panel below is
  // presentational and is handed the result of a real request or the named
  // reason there is none. Nothing here falls back to a plausible value.
  const [dataStatuses, setDataStatuses] = useState<Readonly<Record<string, DataStatus>>>({});
  const [visibleLayerIds, setVisibleLayerIds] = useState<readonly string[]>([]);
  const [inspectorAsset, setInspectorAsset] = useState<InspectorAsset>({
    status: "unavailable", artifactLabel: "unavailable",
    message: "The scenario read route has not answered yet.",
  });
  const [apiFailure, setApiFailure] = useState<FailureStateInput | null>({
    kind: "loading",
    message: "Checking the evidence API for this scene.",
  });
  const [sceneContext, setSceneContext] = useState<SceneContext>(EMPTY_SCENE_CONTEXT);
  const [initialAttemptId] = useState<string>(() => newAttemptId());
  const [attemptId, setAttemptId] = useState<string>(initialAttemptId);
  const [chatStatus, setChatStatus] = useState<ChatStatus>("idle");
  const [chatError, setChatError] = useState<ChatError | undefined>(undefined);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  // The trace is mounted from the first paint with an idle run: "no run yet" is a
  // real state of the run surface, and a trace that only appears once a stream
  // succeeds cannot show a stream that failed to start.
  const [runState, setRunState] = useState<RunState>(() =>
    createRunState({ attemptId: initialAttemptId, contextRevision: `baseline:${initialAttemptId}` }, SOURCE_TRUTH.status));
  const [askResults, setAskResults] = useState<readonly AskResult[]>([]);
  const [askAvailable, setAskAvailable] = useState(false);

  const [gridState, setGridState] = useState<GridState>("mn");
  const [gridLayers, setGridLayers] = useState<readonly string[]>(GRID_LAYERS.mn);
  const [gridQuery, setGridQuery] = useState("");
  const [gridSelected, setGridSelected] = useState<SpatialItem | null>(null);
  const [gridLoad, setGridLoad] = useState<GridLoad>({ kind: "loading" });
  const [gridAttempt, setGridAttempt] = useState(0);
  const [controlRoomRegion, setControlRoomRegion] = useState<RegionId>("texas");

  const contextRevision = `${selected}:${attemptId}`;

  const scenario = data.scenarios[selected];
  const candidate = data.network.candidates.find((item) => item.id === selected);
  const shed = useCountUp(scenario.metrics.shedMw);
  const shedHours = useCountUp(scenario.metrics.shedMwh);
  const supply = useCountUp(scenario.metrics.availableGenerationMw);

  const select = useCallback((id: Id) => {
    setSelected(id);
    setHover(null);
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") return setDetail(false);
      if (detail || event.target instanceof HTMLSelectElement) return;
      const digit = ORDER[Number(event.key) - 1];
      if (digit) return select(digit);
      if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
        const step = event.key === "ArrowRight" ? 1 : -1;
        select(ORDER[(ORDER.indexOf(selected) + step + ORDER.length) % ORDER.length]);
      }
    };
    addEventListener("keydown", onKey);
    return () => removeEventListener("keydown", onKey);
  }, [detail, selected, select]);

  const relieved = useMemo(
    () =>
      data.network.lines
        .map((line) => ({ line, delta: scenario.metrics.lineLoadings[line.id] - BASELINE_LOADS[line.id] }))
        .filter((entry) => entry.delta < 0)
        .sort((left, right) => left.delta - right.delta),
    [scenario],
  );

  const sameAssumptions = ORDER.every((id) => data.scenarios[id].assumptionSetId === data.execution.assumptionSetId);

  // Ask the layer routes what each registry class's status is. The answer today
  // is "unavailable, with the adapter's own named reason", because no Minnesota
  // read route is bound -- but it is a real answer to a real request.
  useEffect(() => {
    const controller = new AbortController();
    loadRegistryDataStatuses(READ_CLIENT, { signal: controller.signal, state: gridState })
      .then((statuses) => setDataStatuses(statuses))
      .catch(() => undefined);
    return () => controller.abort();
  }, [gridState]);

  // The inspector reads the scenario the shell has selected.
  useEffect(() => {
    const controller = new AbortController();
    loadScenarioAsset(selected, READ_CLIENT, { signal: controller.signal })
      .then((asset) => setInspectorAsset(asset))
      .catch(() => undefined);
    return () => controller.abort();
  }, [selected]);

  // One probe decides what the dock is allowed to claim about itself. A health
  // route that does not answer is a named failure state, never a quiet default.
  useEffect(() => {
    const controller = new AbortController();
    READ_CLIENT.get(
      "/health",
      (value): value is Record<string, unknown> => typeof value === "object" && value !== null,
      () => false,
      { signal: controller.signal, retries: 0 },
    ).then((state) => {
      setAskAvailable(state.kind === "ready");
      setApiFailure(fromClientState(state, "The bundled synthetic scene above is unaffected and remains readable."));
    }).catch(() => undefined);
    return () => controller.abort();
  }, []);

  // The physical-inventory release, bounded by the page cap and by the layers
  // the viewer asked for. Every layer is requested once per selection change,
  // not once per pan.
  useEffect(() => {
    const controller = new AbortController();
    setGridLoad({ kind: "loading" });
    Promise.all(gridLayers.map((layer) => loadGridLayer({ state: gridState, layer, signal: controller.signal })))
      .then((outcomes) => {
        if (controller.signal.aborted) return;
        const refused = outcomes.find((outcome) => outcome.kind === "refused");
        if (refused && refused.kind === "refused") return setGridLoad(refused);
        const loaded = outcomes.flatMap((outcome) => outcome.kind === "loaded" ? outcome.pages : []) as readonly SpatialPage[];
        setGridLoad({
          kind: "loaded",
          pages: loaded,
          truncated: outcomes.some((outcome) => outcome.kind === "loaded" && outcome.truncated),
          nextCursor: outcomes.flatMap((outcome) => outcome.kind === "loaded" && outcome.nextCursor ? [outcome.nextCursor] : [])[0] ?? null,
        });
      })
      .catch(() => undefined);
    return () => controller.abort();
  }, [gridState, gridLayers, gridAttempt]);

  const layerSnapshots = useMemo(() => buildRegistrySnapshots(dataStatuses), [dataStatuses]);
  // No producer supplies an evidence disclosure yet, so every layer that would
  // need one is refused by name rather than given a default evidence class.
  const evidenceDisclosures = useMemo(() => evidenceDisclosuresForGridLoad(gridLoad), [gridLoad]);
  const { layers: layerDescriptors, refusals: layerRefusals } = useMemo(
    () => descriptorsFor(LAYER_REGISTRY, layerSnapshots, evidenceDisclosures),
    [layerSnapshots, evidenceDisclosures],
  );
  const layerLegends = useMemo(() => layerSnapshots.map(legendForLayer), [layerSnapshots]);
  const controlRoomProps: ControlRoomProps = {
    regions: [
      {
        id: "texas",
        label: "Texas",
        summary: "Published physical inventory is available; the electrical topology is not yet a browser-delivered artifact.",
        topology: {
          label: "Physical inventory · topology unavailable",
          mode: "unavailable",
          availability: "partial",
          provenance: [{ label: "Published Texas inventory", detail: "source-backed geometry; not an electrical network" }],
          limitations: ["Cascade playback remains unavailable until a qualified cascade artifact is delivered."],
        },
      },
      {
        id: "minnesota",
        label: "Minnesota",
        summary: "Published physical inventory is available; no Minnesota topology is asserted by this screen.",
        topology: {
          label: "Physical inventory · topology withheld",
          mode: "unavailable",
          availability: "partial",
          provenance: [{ label: "Published Minnesota inventory", detail: "source-backed geometry; no inferred topology" }],
          limitations: ["A topology view needs an accepted model artifact before it can be displayed."],
        },
      },
    ],
    selectedRegionId: controlRoomRegion,
    scenarios: [{
      id: "experimental-count-forecast",
      label: "2024 historical count-forecast context",
      description: "The experimental EAGLE-I count-trajectory artifact is not connected to this browser bundle yet.",
      availability: "unavailable",
      weather: [{
        id: "artifact-pending",
        timeLabel: "Historical artifact",
        condition: "Forecast not connected",
        symbol: "unknown",
        detail: "No weather condition is inferred from an outage-count trajectory.",
        availability: "unavailable",
      }],
      model: {
        availability: "unavailable",
        label: "Experimental count-trajectory model",
        provenance: [{ label: "Pending delivered experimental artifact" }],
        limitations: ["This is not an outage probability, live forecast, weather forecast, or cascade result."],
      },
    }],
    cascade: {
      availability: "unavailable",
      title: "Cascade playback",
      unavailableMessage: "No qualified cascade event is available for this selected context.",
      events: [],
    },
    suggestedPrompts: [{
      id: "ask-evidence",
      prompt: "What evidence is available for this selected region?",
      availability: askAvailable ? "available" : "unavailable",
    }],
    onRegionChange: setControlRoomRegion,
    onPromptSelect: () => { if (!chatOpen) toggleChat("toggle"); },
  };

  const sendAsk = useCallback((body: Parameters<NonNullable<Parameters<typeof ChatDock>[0]["onSend"]>>[0]) => {
    const identity: RunIdentity = { attemptId, contextRevision };
    setChatStatus("streaming");
    setChatError(undefined);
    setMessages((current) => [...current, { id: `${identity.attemptId}-${current.length}`, role: "user", content: body.question }]);
    const initial = createRunState(identity, SOURCE_TRUTH.status);
    setRunState(initial);
    runAsk(body, identity, initial, { onState: setRunState })
      .then(({ state, connection }) => {
        setRunState(state);
        setAskResults(resultsFromRun(state));
        if (connection) {
          setChatStatus("error");
          setChatError({ code: "unavailable", message: connection.kind === "unavailable" || connection.kind === "failed" || connection.kind === "invalid" ? connection.message : "The stream did not open." });
          setApiFailure(fromClientState(connection));
          return;
        }
        const terminal = state.terminal;
        if (terminal?.type === "done") {
          setChatStatus("done");
          setMessages((current) => state.text ? [...current, { id: `${identity.attemptId}-answer`, role: "assistant", content: state.text }] : current);
          return;
        }
        setChatStatus("error");
        setChatError(terminal?.type === "error"
          ? { code: terminal.error.code, message: terminal.error.message, retryable: terminal.error.retryable }
          : { code: "protocol_error", message: state.issues[state.issues.length - 1]?.message ?? "The stream ended without a terminal event." });
      })
      .catch(() => setChatStatus("error"));
  }, [attemptId, contextRevision]);

  return (
    // `data-source-status` publishes the derived IA token to the DOM so a browser
    // proof can pin the machine label, not the prose around it. It is written from
    // SOURCE_TRUTH, which src/source-truth.ts derives from the bundle's provenance.
    <main data-source-status={SOURCE_TRUTH.status}>
      <nav>
        <div className="brand"><b>FLUX</b><span>Resilience desk</span></div>
        <div className="live"><i />{sourceSummary(SOURCE_TRUTH)} · no API required for this scene</div>
        <button className="ghost" onClick={() => setDetail(true)}>Data, units &amp; limits</button>
      </nav>

      <header className="shell-intro">
        <p className="eyebrow">SYSTEM RESILIENCE / SCENARIO EXPLORER</p>
        <h1>Where does 300 MW cut the most unmet demand?</h1>
        <p>
          One fixed cold-stress snapshot, three runs from the same assumptions. Pick a candidate to see the
          corridors it relieves. Every figure is read from a checked-in synthetic artifact — no runtime request,
          and no claim about a real grid.
        </p>
      </header>

      <section className="shell-controls" aria-label="Scenario controls">
        <div>
          <p className="eyebrow">Scenario comparison</p>
          <p>Choose a bundled run. All choices keep the same synthetic five-bus assumptions.</p>
        </div>
        <span className="shell-status">{STATUS_COPY[SOURCE_TRUTH.status]} five-bus preview · not Minnesota data</span>
      </section>

      <CompareRail selected={selected} onSelect={select} />

      <section className="workspace" aria-label="Viewport-first scenario workspace">
        <article className="map scene-viewport">
          <div className="map-head">
            <div>
              <p className="eyebrow">NETWORK STATE · {scenario.label.toUpperCase()}</p>
              <p className="hint">Line weight tracks utilization. Hover or tab a corridor for its reading.</p>
            </div>
            <div className="toggle" role="group" aria-label="Corridor colouring">
              <button className={view === "load" ? "on" : ""} onClick={() => setView("load")} aria-pressed={view === "load"}>Utilization</button>
              <button className={view === "delta" ? "on" : ""} onClick={() => setView("delta")} aria-pressed={view === "delta"}>Change vs baseline</button>
            </div>
          </div>

          <Network selected={selected} view={view} onSelect={select} hover={hover} setHover={setHover} />

          <div className="legend">
            {view === "load"
              ? <><i className="tone-low" />under 75% <i className="tone-mid" />75–89% <i className="tone-high" />90%+ <span>· {scenario.units.lineLoading} of rating</span></>
              : <><i className="tone-none" />unchanged <i className="tone-some" />relieved <i className="tone-strong" />15+ points relieved <span>· percentage points vs baseline</span></>}
          </div>
          <LayerControls
            layers={layerDescriptors}
            visibleLayerIds={visibleLayerIds}
            onVisibleLayerIdsChange={setVisibleLayerIds}
          />
          <ul className="layer-list" aria-label="Layer status legend">
            {layerLegends.map((legend) => {
              const entry = legend.entries.find((item) => item.status === legend.currentStatus);
              return (
                <li className="layer-legend" key={legend.layerId}>
                  <span className="layer-legend-glyph" aria-hidden="true">{entry?.glyph}</span>
                  <b>{legend.layerLabel}</b>{" "}{entry?.label}{" \u00b7 "}{entry?.description}
                  {legend.currentReason ? <> {legend.currentReason}</> : null}
                  {legend.currentRequestId ? <> Request {legend.currentRequestId}.</> : null}
                </li>
              );
            })}
            {layerRefusals.map((refusal) => (
              <li className="layer-refusal" key={refusal.message} role="note">{refusal.message}</li>
            ))}
          </ul>
          <section className="timeline" aria-label="Scenario timeline">
            <div>
              <p className="eyebrow">Timeline</p>
              <strong>Fixed {data.execution.assumptions.durationHours}-hour snapshot</strong>
            </div>
            <div className="timeline-track" aria-hidden="true"><i /></div>
            <span>Bundled output · playback unavailable</span>
          </section>
        </article>

        <aside className="inspector" aria-label="Scenario inspector">
          <div className="outcome">
            <p className="eyebrow">MODELED UNMET DEMAND</p>
            <strong>{shed}<small> {scenario.units.shedMw}</small></strong>
            <p>{shedHours} {scenario.units.shedMwh} across the {data.execution.assumptions.durationHours}-hour window</p>
            <div className={selected === "baseline" ? "delta flat" : "delta"}>
              {selected === "baseline"
                ? "Baseline reference"
                : `−${scenario.metrics.improvementMw} ${scenario.units.improvementMw} vs baseline`}
            </div>
          </div>

          <div className="stats">
            <div><span>Demand</span><b>{scenario.metrics.demandMw} {scenario.units.demandMw}</b></div>
            <div><span>Available supply</span><b>{supply} {scenario.units.availableGenerationMw}</b></div>
          </div>

          {candidate ? (
            <div className="insight">
              <p className="eyebrow">{candidate.name} · +{candidate.capacityMw} MW AT {BUSES[candidate.busId].name.toUpperCase()}</p>
              <h2>{candidate.description}</h2>
              <p>Modeled contribution {scenario.intervention?.modeledContributionMw} MW of the {candidate.capacityMw} MW sited. A fixture assumption, not an interconnection result.</p>
              <ul className="relief">
                {relieved.slice(0, 3).map(({ line, delta }) => (
                  <li key={line.id}>
                    <span>{BUSES[line.from].name} → {BUSES[line.to].name}</span>
                    <em>{signed(delta)} pts</em>
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <div className="insight">
              <p className="eyebrow">NO CAPACITY ADDED</p>
              <h2>This is the reference run every candidate is measured against.</h2>
              <p>Select Candidate A or B — on the rail above, on the map, or with keys 1–3 — to compare against it.</p>
            </div>
          )}

          <Inspector asset={inspectorAsset} className="asset-inspector" title="Scenario provenance" />
        </aside>
      </section>

      <GridInventoryPanel
        load={gridLoad}
        state={gridState}
        layers={gridLayers}
        query={gridQuery}
        selected={gridSelected}
        onStateChange={(next) => { setGridState(next); setGridLayers(GRID_LAYERS[next]); setGridSelected(null); }}
        onLayersChange={setGridLayers}
        onQueryChange={setGridQuery}
        onSelect={setGridSelected}
        onRetry={() => setGridAttempt((value) => value + 1)}
      />

      <ControlRoom {...controlRoomProps} />

      <section className="pipeline">
        <div>
          <p className="eyebrow">SOURCE + MODEL CONTRACT</p>
          <h2>Same assumptions. Traceable synthetic output.</h2>
        </div>
        <p>
          {sameAssumptions
            ? `All three runs share ${data.execution.assumptions.demandMw} MW demand, ${data.execution.assumptions.durationHours} h, and one baseline generation assumption.`
            : "Comparison unavailable: scenario assumptions differ."}{" "}
          Artifact <code>{data.execution.provenance.artifactId}</code> · hash <code>{data.fixtureHash}</code>.
        </p>
      </section>

      <ChatDockView
        open={chatOpen}
        onToggle={() => toggleChat("toggle")}
        collapsedLabel={askAvailable ? "Copilot endpoint reachable" : OFFLINE_DOCK_LABEL}
      >
        <ChatDock
          contextRevision={contextRevision}
          context={sceneContext}
          attemptId={attemptId}
          sourceLabel="Bundled synthetic scene"
          sourceStatus={SOURCE_TRUTH.status}
          status={chatStatus}
          error={chatError}
          messages={messages}
          onContextChange={setSceneContext}
          onSend={askAvailable ? sendAsk : undefined}
          onRetry={() => setAttemptId(newAttemptId())}
        />
        <RunTrace state={runState} />
        <ResultCards results={askResults} />
        {apiFailure ? <FailureState state={apiFailure} onRetry={() => setAttemptId(newAttemptId())} /> : null}
      </ChatDockView>

      {detail && (
        <div className="overlay" onMouseDown={() => setDetail(false)}>
          <section className="modal" role="dialog" aria-modal="true" aria-label="Data disclosure" onMouseDown={(event) => event.stopPropagation()}>
            <button onClick={() => setDetail(false)} aria-label="Close disclosure">×</button>
            <p className="eyebrow">DATA DISCLOSURE</p>
            <h2>Provenance, assumptions, and limits</h2>
            <dl>
              <dt>Artifact</dt><dd>{data.execution.provenance.artifactId} · hash {data.execution.provenance.inputHash}</dd>
              <dt>Source</dt><dd>{data.execution.provenance.sourceId} ({data.execution.provenance.sourceVersion})</dd>
              <dt>Source reference</dt><dd><code>{data.execution.provenance.sourceRef}</code></dd>
              <dt>Scope</dt><dd>{data.execution.provenance.scope}</dd>
            </dl>
            <ul>{data.execution.assumptions.notes.map((note) => <li key={note}>{note}</li>)}</ul>
            <ul>{data.execution.limitations.map((limit) => <li key={limit}>{limit}</li>)}</ul>
          </section>
        </div>
      )}
    </main>
  );
}

/** Mount only in a browser document; the render tests import App directly. */
const mountPoint = typeof document === "undefined" ? null : document.getElementById("root");
if (mountPoint) createRoot(mountPoint).render(<App />);
