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
import { descriptorsFor } from "./layers/descriptor-adapter";
import { buildRegistrySnapshots, LAYER_REGISTRY, type DataStatus } from "./layers/registry";
import { legendForLayer } from "./layers/legend";
import { createReadApiClient } from "./data/client-state";
import { loadRegistryDataStatuses } from "./data/layer-status";
import { runAsk } from "./data/ask-stream";
import { resultsFromRun } from "./data/ask-result";
import { loadGridLayer, GRID_LAYERS, type GridState } from "./data/grid-client";
import type { SpatialItem, SpatialPage } from "./data/grid-inventory";
import { GridInventoryPanel, type GridLoad } from "./renderer/GridInventoryPanel";
import { ContinentalGridMap } from "./renderer/ContinentalGridMap";
import { SyntheticModelScene } from "./renderer/SyntheticModelScene";
import {
  HistoricalForecastPanel,
  PrimaryDemo,
  ControlRoom,
  SyntheticTexasModelMap,
  createPrimaryDemoRuntime,
  cascadePlaybackFromPayload,
  historicalForecastFromPayload,
  texasModelSceneFromPayload,
  type HistoricalCountForecast,
  type CascadePlayback,
  type ModelPayload,
  type PrimarySceneMode,
  type RegionId,
  type TexasModelScene,
  type ControlRoomProps,
} from "./demo";
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

type DemoWeatherRecord = { ts: string; condition: string; label: string; observed_or_forecast: string; wind_ms: number; gust_ms: number; temp_c: number; ice_mm: number; precip_mm: number; provenance: string[]; rule: string };
type DemoBrief = { regions: Array<{ id: string; mode: string; availability: string }>; scenarios: Array<{ scenario_id: string; name: string; kind: string; provenance: string[]; weather: DemoWeatherRecord[] }> };
type DemoForecastPayload = Parameters<typeof historicalForecastFromPayload>[0];

function isDemoBrief(value: unknown): value is DemoBrief {
  if (!value || typeof value !== "object") return false;
  const record = value as Record<string, unknown>;
  return Array.isArray(record.regions) && Array.isArray(record.scenarios);
}

function isDemoForecastPayload(value: unknown): value is DemoForecastPayload {
  return Boolean(value && typeof value === "object" && typeof (value as Record<string, unknown>).status === "string");
}

function isModelPayload(value: unknown): value is ModelPayload {
  if (!value || typeof value !== "object") return false;
  const status = (value as Record<string, unknown>).status;
  return status === "available" || status === "partial" || status === "unavailable";
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null;
}

/**
 * Applies only the bridge's explicit scene action. It deliberately ignores
 * answer prose and raw solver-shaped objects: live runs are visualized only
 * after the server marks the result as the current synthetic cascade action
 * and the v1 stream finishes verified.
 */
function liveCascadeFromRun(state: RunState, context: SceneContext, region: RegionId): CascadePlayback | null {
  if (region !== "texas" || state.terminal?.type !== "done" || state.terminal.verified !== true
    || context.region !== "texas" || context.view_mode !== "texas_model"
    || context.scenario_id !== "uri_2021" || context.hour === null) return null;
  for (const trace of Object.values(state.tools)) {
    // The bridge's current interactive dispatcher names this `cascade`; the
    // direct demo bridge uses `synthetic_cascade`. The explicit scene action
    // below, rather than either display name, is the authority for linkage.
    if ((trace.tool !== "synthetic_cascade" && trace.tool !== "cascade") || trace.result?.ok !== true) continue;
    const result = asRecord(trace.result.result);
    const action = asRecord(result?.scene_action);
    if (!action || action.kind !== "synthetic_cascade_current" || action.persisted !== false
      || action.scenario_id !== context.scenario_id || action.hour !== context.hour
      || action.topology !== "synthetic (ACTIVSg2000)" || action.synthetic !== true
      || typeof action.run_id !== "string") continue;
    const requested = Array.isArray(action.element_ids) ? action.element_ids.filter((item): item is string => typeof item === "string") : [];
    if (context.selected_element_id && !requested.includes(context.selected_element_id)) continue;
    const events = Array.isArray(action.timeline) ? action.timeline.flatMap((item, index) => {
      const event = asRecord(item);
      if (!event || typeof event.element_id !== "string") return [];
      return [{
        id: `live-${event.stage ?? 0}-${index}-${event.element_id}`,
        elementId: event.element_id,
        stageLabel: `Stage ${typeof event.stage === "number" ? event.stage : 0} · ${typeof event.kind === "string" ? event.kind : "element"}`,
        summary: `${event.element_id} ${typeof event.cause === "string" ? event.cause : "event"}.`,
        availability: "available" as const,
      }];
    }) : [];
    if (events.length === 0) return null;
    return {
      availability: "available",
      runId: action.run_id,
      title: "Live synthetic Texas cascade",
      events,
      provenance: [{ label: "Verified current-run tool result", detail: "ephemeral write=false synthetic model result" }],
      limitations: ["This is a live synthetic model computation, not persisted playback and not physical-inventory connectivity."],
    };
  }
  return null;
}

function weatherSymbol(condition: string): "clear" | "cloudy" | "rain" | "snow" | "wind" | "storm" | "heat" | "unknown" {
  return ["clear", "cloudy", "rain", "snow", "wind", "storm", "heat"].includes(condition) ? condition as "clear" | "cloudy" | "rain" | "snow" | "wind" | "storm" | "heat" : "unknown";
}

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
  // The workspace begins with a usable plain-English query, rather than a
  // closed utility: the map remains dominant and the dock stays in its rail.
  const [chatOpen, toggleChat] = useReducer(chatReducer, true);

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
  const [sceneRevision, setSceneRevision] = useState(0);
  const [chatPrefill, setChatPrefill] = useState<{ value: string; revision: number }>({ value: "", revision: 0 });
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

  const [gridState, setGridState] = useState<GridState>("tx");
  const [gridLayers, setGridLayers] = useState<readonly string[]>(GRID_LAYERS.tx);
  const [gridQuery, setGridQuery] = useState("");
  const [gridSelected, setGridSelected] = useState<SpatialItem | null>(null);
  const [gridLoad, setGridLoad] = useState<GridLoad>({ kind: "loading" });
  const [gridAttempt, setGridAttempt] = useState(0);
  const [controlRoomRegion, setControlRoomRegion] = useState<RegionId>("texas");
  const [sceneMode, setSceneMode] = useState<PrimarySceneMode>("inventory");
  const [weatherFrames, setWeatherFrames] = useState<ReturnType<typeof createPrimaryDemoRuntime>["scenarios"][number]["weather"]>([]);
  const [historicalForecast, setHistoricalForecast] = useState<HistoricalCountForecast>({ availability: "unavailable", reason: "The historical trajectory has not been requested." });
  const [forecastCountyFips, setForecastCountyFips] = useState("48201");
  const [forecastCountyFipses, setForecastCountyFipses] = useState<readonly string[]>([]);
  const [modelPayload, setModelPayload] = useState<ModelPayload>({ status: "unavailable", reason: "The synthetic model geometry has not been requested." });
  const [cascadePayload, setCascadePayload] = useState<Parameters<typeof cascadePlaybackFromPayload>[0] | null>(null);
  const [liveCascade, setLiveCascade] = useState<CascadePlayback | null>(null);
  const [selectedModelElementId, setSelectedModelElementId] = useState<string | undefined>();
  const currentRegionRef = useRef<RegionId>("texas");
  const currentSceneContextRef = useRef<SceneContext>(EMPTY_SCENE_CONTEXT);
  const currentAttemptRef = useRef(initialAttemptId);

  const contextRevision = `${controlRoomRegion}:${sceneRevision}:${attemptId}`;

  const updateSceneContext = useCallback((next: SceneContext | ((current: SceneContext) => SceneContext)) => {
    setSceneContext((current) => typeof next === "function" ? next(current) : next);
    setSceneRevision((revision) => revision + 1);
  }, []);

  const prefillChat = useCallback((value: string) => {
    setChatPrefill((current) => ({ value, revision: current.revision + 1 }));
  }, []);

  useEffect(() => { currentRegionRef.current = controlRoomRegion; }, [controlRoomRegion]);
  useEffect(() => { currentSceneContextRef.current = sceneContext; }, [sceneContext]);
  useEffect(() => { currentAttemptRef.current = attemptId; }, [attemptId]);

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
    loadRegistryDataStatuses(READ_CLIENT, { signal: controller.signal })
      .then((statuses) => setDataStatuses(statuses))
      .catch(() => undefined);
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    READ_CLIENT.get<Parameters<typeof cascadePlaybackFromPayload>[0]>("/cascade?scenario_id=uri_2021&run_id=uri_2021-s0-87d226a6", (value): value is Parameters<typeof cascadePlaybackFromPayload>[0] => Boolean(value && typeof value === "object"), () => false, { signal: controller.signal, retries: 0 })
      .then((state) => setCascadePayload(state.kind === "ready" ? state.data : null))
      .catch(() => setCascadePayload(null));
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    // These are server-verified canonical model IDs, not physical layer IDs.
    READ_CLIENT.get<ModelPayload>("/demo/model", isModelPayload, () => false, { signal: controller.signal, retries: 0 })
      .then((state) => setModelPayload(state.kind === "ready" ? state.data : { status: "unavailable", reason: state.kind === "unavailable" || state.kind === "failed" || state.kind === "invalid" ? state.message : "The model geometry is unavailable." }))
      .catch(() => setModelPayload({ status: "unavailable", reason: "The model geometry could not be read." }));
    return () => controller.abort();
  }, []);

  // Primary data comes from the explicitly versioned demo read surfaces. A
  // failure leaves a named unavailable state; it never falls back to the five-bus fixture.
  useEffect(() => {
    const controller = new AbortController();
    READ_CLIENT.get<DemoBrief>("/demo/brief?region=tx&scenario_id=uri_2021", isDemoBrief, () => false, { signal: controller.signal, retries: 0 })
      .then((state) => {
        if (state.kind !== "ready") return setWeatherFrames([]);
        const sourceScenario = state.data.scenarios.find((item) => item.scenario_id === "uri_2021");
        if (!sourceScenario) return setWeatherFrames([]);
        setWeatherFrames(sourceScenario.weather.map((frame) => ({
          id: frame.ts,
          timeLabel: new Date(frame.ts).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric" }),
          condition: frame.label,
          symbol: weatherSymbol(frame.condition),
          detail: `${frame.observed_or_forecast} HRRR frame · wind ${frame.wind_ms} m/s · gust ${frame.gust_ms} m/s · ${frame.temp_c} °C`,
          availability: "available",
          provenance: frame.provenance.map((label) => ({ label })),
          limitations: [frame.rule],
        })));
      })
      .catch(() => setWeatherFrames([]));
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    // Reset before every state/county read so a Texas trajectory is never shown
    // while Minnesota is loading (or the reverse).
    setHistoricalForecast({ availability: "unavailable", reason: "Loading the selected historical county trajectory." });
    READ_CLIENT.get<DemoForecastPayload>(`/demo/forecast?county_fips=${forecastCountyFips}`, isDemoForecastPayload, () => false, { signal: controller.signal, retries: 0 })
      .then((state) => {
        if (controller.signal.aborted) return;
        if (state.kind !== "ready") {
          setHistoricalForecast({ availability: "unavailable", reason: state.kind === "unavailable" || state.kind === "failed" || state.kind === "invalid" ? state.message : "The historical trajectory is unavailable." });
          return;
        }
        const scope = state.data.data?.scope?.observed_county_fips ?? [];
        setForecastCountyFipses(scope);
        setHistoricalForecast(historicalForecastFromPayload(state.data));
      })
      .catch(() => setHistoricalForecast({ availability: "unavailable", reason: "The historical trajectory could not be read." }));
    return () => controller.abort();
  }, [forecastCountyFips]);

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
  const { layers: layerDescriptors, refusals: layerRefusals } = useMemo(
    () => descriptorsFor(LAYER_REGISTRY, layerSnapshots),
    [layerSnapshots],
  );
  const layerLegends = useMemo(() => layerSnapshots.map(legendForLayer), [layerSnapshots]);
  const persistedCascade = cascadePayload ? cascadePlaybackFromPayload(cascadePayload) : undefined;
  const activeCascade = liveCascade ?? persistedCascade;
  const modelElementsById = useMemo(() => new Map((modelPayload.data?.elements ?? [])
    .flatMap((element) => element.element_id ? [[element.element_id, element] as const] : [])), [modelPayload]);
  const protectedModelElementIds = useMemo(() => (modelPayload.data?.elements ?? []).flatMap((element) => element.element_id && element.role === "grid_forming_slack" ? [element.element_id] : []), [modelPayload]);
  const selectedModelIsSlack = modelElementsById.get(selectedModelElementId ?? "")?.role === "grid_forming_slack";
  const selectModelElement = useCallback((elementId: string) => {
    setSelectedModelElementId(elementId || undefined);
    updateSceneContext({ ...EMPTY_SCENE_CONTEXT, region: "texas", county_fips: forecastCountyFips, view_mode: "texas_model", scenario_id: "uri_2021", hour: 0, selected_element_id: elementId || null });
  }, [forecastCountyFips, updateSceneContext]);
  const selectedCountyFipses = forecastCountyFipses.filter((countyFips) => controlRoomRegion === "texas" ? countyFips.startsWith("48") : countyFips.startsWith("27"));
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

  const onPrimaryRegionChange = useCallback((region: RegionId) => {
    setControlRoomRegion(region);
    const nextGridState: GridState = region === "texas" ? "tx" : "mn";
    setGridState(nextGridState);
    setGridLayers(GRID_LAYERS[nextGridState]);
    setGridSelected(null);
    setLiveCascade(null);
    setSelectedModelElementId(undefined);
    updateSceneContext({ ...EMPTY_SCENE_CONTEXT, region, county_fips: region === "texas" ? "48201" : "27053", view_mode: "physical_inventory" });
    // These initial FIPS selections are the reviewed records themselves; the
    // selectable list is later read from `data.scope.observed_county_fips`.
    setForecastCountyFips(region === "texas" ? "48201" : "27053");
    setSceneMode("inventory");
  }, [updateSceneContext]);

  const primaryControlRoomProps = createPrimaryDemoRuntime({
    regions: [
      {
        id: "texas",
        label: "Texas",
        summary: "Source-backed physical inventory and Uri weather context are available. The model scene is synthetic (ACTIVSg2000).",
        topology: {
          label: "synthetic (ACTIVSg2000)", mode: "synthetic", availability: "available",
          provenance: [{ label: "Texas model contract", detail: "synthetic topology; separate from physical inventory geometry" }],
          limitations: ["Model geometry and any cascade events are kept separate from source-backed physical inventory."],
        },
      },
      {
        id: "minnesota",
        label: "Minnesota",
        summary: "Source-backed physical inventory may be browsed; no Minnesota topology is asserted.",
        topology: {
          label: "aggregate / topology unavailable", mode: "aggregate", availability: "partial",
          provenance: [{ label: "Minnesota inventory boundary", detail: "physical inventory is not an electrical model" }],
          limitations: ["Minnesota remains inventory or aggregate only until an accepted topology contract is supplied."],
        },
      },
    ],
    selectedRegionId: controlRoomRegion,
    onRegionChange: onPrimaryRegionChange,
    weather: controlRoomRegion === "texas" ? weatherFrames : [],
    historicalModel: {
      availability: historicalForecast.availability,
      label: "Experimental historical observed-count trajectory",
      provenance: historicalForecast.provenance ?? [],
      limitations: historicalForecast.limitations,
    },
    cascade: activeCascade,
    suggestedPrompts: [
      { id: "ask-evidence", prompt: "What evidence is available for this selected region?", availability: askAvailable ? "available" : "unavailable" },
      { id: "open-texas-model", prompt: "Open the synthetic Texas model before asking about a component failure.", availability: controlRoomRegion === "texas" ? "available" : "unavailable" },
    ],
    onPromptSelect: (prompt) => {
      const texasContext = controlRoomRegion === "texas";
      if (prompt.id === "open-texas-model" && texasContext) setSceneMode("texas_model");
      updateSceneContext(texasContext
        ? { ...EMPTY_SCENE_CONTEXT, region: "texas", county_fips: forecastCountyFips, view_mode: prompt.id === "open-texas-model" || sceneMode === "texas_model" ? "texas_model" : "physical_inventory", scenario_id: "uri_2021", hour: 0, selected_element_id: selectedModelElementId ?? null }
        : { ...EMPTY_SCENE_CONTEXT, region: "minnesota", county_fips: forecastCountyFips, view_mode: "physical_inventory" });
      prefillChat(`${prompt.prompt}\n\nVisible context: ${controlRoomRegion === "texas" ? "Texas synthetic (ACTIVSg2000) model, Uri 2021 hour 0" : "Minnesota physical inventory / aggregate context"}; historical county ${historicalForecast.countyFips ?? "unavailable"}; selected model element ${selectedModelElementId ?? "none"}.`);
      if (!chatOpen) toggleChat("toggle");
    },
  });

  const texasModelSceneBase = texasModelSceneFromPayload(modelPayload, {
    availability: selectedModelIsSlack ? "unavailable" : "available",
    message: selectedModelIsSlack
      ? "Grid-forming slack is protected in this synthetic model and cannot be selected for a forced outage."
      : "Select a verified synthetic model ID, then ask the configured Copilot to run the component-failure scenario.",
    selectedElementId: selectedModelElementId,
    onSelectElement: selectModelElement,
    onRequestFailure: () => {
      if (!selectedModelElementId || selectedModelIsSlack) return;
      updateSceneContext({ ...EMPTY_SCENE_CONTEXT, region: "texas", county_fips: forecastCountyFips, view_mode: "texas_model", scenario_id: "uri_2021", hour: 0, selected_element_id: selectedModelElementId });
      prefillChat(`Simulate the synthetic cascade after ${selectedModelElementId} fails in Uri 2021 at hour 0.\n\nVisible context: Texas synthetic (ACTIVSg2000) model; historical county ${historicalForecast.countyFips ?? "unavailable"}; selected model element ${selectedModelElementId}.`);
      setSceneMode("texas_model");
      if (!chatOpen) toggleChat("toggle");
    },
  });
  const texasModelScene: TexasModelScene = texasModelSceneBase.availability !== "unavailable" ? {
    ...texasModelSceneBase,
    protectedElementIds: protectedModelElementIds,
    liveCascade: liveCascade ? { runId: liveCascade.runId, events: liveCascade.events } : undefined,
    visual: <SyntheticModelScene elements={modelPayload.data?.elements ?? []} selectedElementId={selectedModelElementId} highlightedElementIds={activeCascade?.events.flatMap((event) => event.elementId ? [event.elementId] : []) ?? []} onSelectElement={selectModelElement} fallback={<SyntheticTexasModelMap elements={modelPayload.data?.elements ?? []} selectedElementId={selectedModelElementId} onSelect={selectModelElement} />} />,
  } : texasModelSceneBase;

  const sendAsk = useCallback((body: Parameters<NonNullable<Parameters<typeof ChatDock>[0]["onSend"]>>[0]) => {
    const identity: RunIdentity = { attemptId, contextRevision };
    const submittedContext: SceneContext = { ...EMPTY_SCENE_CONTEXT, ...body.context };
    const submittedRegion = controlRoomRegion;
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
          const current = currentSceneContextRef.current;
          const live = currentAttemptRef.current === identity.attemptId
            && currentRegionRef.current === submittedRegion
            && current.scenario_id === submittedContext.scenario_id
            && current.hour === submittedContext.hour
            && current.selected_element_id === submittedContext.selected_element_id
            ? liveCascadeFromRun(state, submittedContext, submittedRegion)
            : null;
          if (live) {
            setLiveCascade(live);
            setSceneMode("texas_model");
            if (submittedContext.selected_element_id) setSelectedModelElementId(submittedContext.selected_element_id);
          }
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
  }, [attemptId, contextRevision, controlRoomRegion]);

  return <main data-source-status="unavailable" data-primary-demo="true">
    <nav>
      <div className="brand"><b>FLUX</b><span>Energy system desk</span></div>
      <div className="live"><i />Source state is named on every active scene</div>
    </nav>
    <PrimaryDemo
      controlRoom={primaryControlRoomProps}
      sceneMode={sceneMode}
      onSceneModeChange={(mode) => {
        setSceneMode(mode);
        if (mode === "inventory") {
          setSelectedModelElementId(undefined);
          updateSceneContext({ ...EMPTY_SCENE_CONTEXT, region: controlRoomRegion, county_fips: forecastCountyFips, view_mode: "physical_inventory" });
        } else {
          updateSceneContext({ ...EMPTY_SCENE_CONTEXT, region: "texas", county_fips: forecastCountyFips, view_mode: "texas_model", scenario_id: "uri_2021", hour: 0, selected_element_id: selectedModelElementId ?? null });
        }
      }}
      texasModelScene={texasModelScene}
      spatialStage={<ContinentalGridMap
        className="primary-demo__continental-map"
        selectedRegion={controlRoomRegion}
        onRegionSelect={onPrimaryRegionChange}
        onAssetSelect={setGridSelected}
      />}
      inspectorSlot={<><Inspector asset={inspectorAsset} className="asset-inspector" title="Evidence availability" /><HistoricalForecastPanel forecast={historicalForecast} countyFipses={selectedCountyFipses} selectedCountyFips={forecastCountyFips} onCountyChange={setForecastCountyFips} /></>}
      chatSlot={<ChatDockView
        open={chatOpen}
        onToggle={() => toggleChat("toggle")}
        collapsedLabel={askAvailable ? "Copilot endpoint reachable" : OFFLINE_DOCK_LABEL}
      >
        <ChatDock
          contextRevision={contextRevision}
          context={sceneContext}
          attemptId={attemptId}
          sourceLabel="Selected evidence context"
          sourceStatus={controlRoomRegion === "texas" ? "synthetic" : "unavailable"}
          status={chatStatus}
          error={chatError}
          messages={messages}
          prefill={chatPrefill}
          onContextChange={updateSceneContext}
          onSend={askAvailable ? sendAsk : undefined}
          onRetry={() => setAttemptId(newAttemptId())}
        />
        <RunTrace state={runState} />
        <ResultCards results={askResults} />
        {apiFailure ? <FailureState state={apiFailure} onRetry={() => setAttemptId(newAttemptId())} /> : null}
      </ChatDockView>}
      legacyFixture={<section>
        <p className="control-room__eyebrow">Retired fixture</p>
        <h3>Synthetic five-bus comparison</h3>
        <p>This fixture is not Texas, Minnesota, a physical inventory, or the synthetic ACTIVSg2000 model scene.</p>
        <CompareRail selected={selected} onSelect={select} />
        <article className="map">
          <div className="map-head"><p className="eyebrow">FIXTURE NETWORK · {scenario.label.toUpperCase()}</p></div>
          <Network selected={selected} view={view} onSelect={select} hover={hover} setHover={setHover} />
        </article>
      </section>}
    />
  </main>;

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
              <p className="eyebrow">{candidate!.name} · +{candidate!.capacityMw} MW AT {BUSES[candidate!.busId].name.toUpperCase()}</p>
              <h2>{candidate!.description}</h2>
              <p>Modeled contribution {scenario.intervention?.modeledContributionMw} MW of the {candidate!.capacityMw} MW sited. A fixture assumption, not an interconnection result.</p>
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
        {apiFailure ? <FailureState state={apiFailure!} onRetry={() => setAttemptId(newAttemptId())} /> : null}
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
