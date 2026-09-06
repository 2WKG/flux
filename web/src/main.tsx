import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import fixture from "../../data/demo/bundle.json";
import { ResultCards } from "./ask/results";
import { RunTrace } from "./ask/run-state/RunTrace";
import { createRunState } from "./ask/run-state/reducer";
import { ChatDock, type SceneContext } from "./chat/ChatDock";
import { Inspector } from "./inspector/Inspector";
import { MapLibreDeckFoundation } from "./renderer/MapLibreDeckFoundation";
import { AppShell } from "./shell/AppShell";
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
const UNAVAILABLE_MODEL_SCENE = {
  kind: "rejected" as const,
  reason: "aggregate_only_no_geometry" as const,
  detail: "No accepted geographic feature artifact is available in the bundled static demo.",
};

function initialSceneContext(id: Id): SceneContext {
  return {
    geography: "No geographic coverage in this fixture",
    layers: ["Synthetic five-bus topology"],
    facility: null,
    scenario: data.scenarios[id].label,
    time: "Fixed synthetic snapshot",
  };
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
              role="group"
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

function App() {
  const [selected, setSelected] = useState<Id>("baseline");
  const [view, setView] = useState<View>("load");
  const [hover, setHover] = useState<Hover>(null);
  const [detail, setDetail] = useState(false);
  const [chatContext, setChatContext] = useState<SceneContext>(() => initialSceneContext("baseline"));
  const [contextVersion, setContextVersion] = useState(0);
  const disclosureTrigger = useRef<HTMLButtonElement>(null);
  const disclosureClose = useRef<HTMLButtonElement>(null);

  const scenario = data.scenarios[selected];
  const candidate = data.network.candidates.find((item) => item.id === selected);
  const shed = useCountUp(scenario.metrics.shedMw);
  const shedHours = useCountUp(scenario.metrics.shedMwh);
  const supply = useCountUp(scenario.metrics.availableGenerationMw);

  const select = useCallback((id: Id) => {
    setSelected(id);
    setHover(null);
    setChatContext((current) => ({ ...current, scenario: data.scenarios[id].label }));
    setContextVersion((version) => version + 1);
  }, []);

  const updateChatContext = useCallback((next: SceneContext) => {
    setChatContext(next);
    setContextVersion((version) => version + 1);
  }, []);

  const openDetail = useCallback(() => setDetail(true), []);
  const closeDetail = useCallback(() => {
    setDetail(false);
    requestAnimationFrame(() => disclosureTrigger.current?.focus());
  }, []);

  useEffect(() => {
    if (detail) disclosureClose.current?.focus();
  }, [detail]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && detail) return closeDetail();
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
  }, [closeDetail, detail, selected, select]);

  const relieved = useMemo(
    () =>
      data.network.lines
        .map((line) => ({ line, delta: scenario.metrics.lineLoadings[line.id] - BASELINE_LOADS[line.id] }))
        .filter((entry) => entry.delta < 0)
        .sort((left, right) => left.delta - right.delta),
    [scenario],
  );

  const sameAssumptions = ORDER.every((id) => data.scenarios[id].assumptionSetId === data.execution.assumptionSetId);
  const contextRevision = `${data.fixtureHash}:${selected}:c${contextVersion}`;
  const fixtureInspector = {
    status: "synthetic" as const,
    artifactLabel: "synthetic" as const,
    id: data.fixtureHash,
    name: "Synthetic five-bus fixture",
    kind: "Static topology fixture",
    scenario: scenario.label,
    readiness: "Bundled static demo",
    coverage: "No Minnesota or Texas geography",
    message: "This fixture is synthetic. Its labels and metrics do not identify real facilities, corridors, or grid operations.",
    fields: [
      { label: "Unmet demand", value: String(scenario.metrics.shedMw), unit: scenario.units.shedMw, uncertainty: "Fixture output" },
      { label: "Available supply", value: String(scenario.metrics.availableGenerationMw), unit: scenario.units.availableGenerationMw, uncertainty: "Fixture output" },
      { label: "Candidate capacity", value: candidate ? String(candidate.capacityMw) : undefined, unit: candidate ? "MW" : undefined, status: candidate ? "available" as const : "unavailable" as const, uncertainty: "No interconnection conclusion" },
    ],
    provenance: [{ sourceName: "Checked-in synthetic bundle", sourceRef: data.execution.provenance.sourceRef, sourceVersion: data.execution.provenance.sourceVersion, coverage: "Five-bus synthetic fixture" }],
    caveats: data.execution.limitations,
  };
  const staticRun = createRunState({ attemptId: "static-agent-unavailable", contextRevision }, "unavailable");
  const staticResults = [{
    id: `static-agent-${contextRevision}`,
    answer: "",
    scope: `Static demo agent · synthetic context ${contextRevision}`,
    status: { availability: "unavailable" as const, reason: "The static fixture build has no live agent or API connection." },
    citations: [],
    provenance: [],
    limitations: ["No live tool call was made.", "No result, recommendation, or scene action is available in static mode."],
  }];

  return (
    <>
      <AppShell
      title="Where does 300 MW cut the most unmet demand?"
      source={{
        status: "synthetic",
        label: "Synthetic five-bus fixture · no API required",
        detail: "Checked-in synthetic artifact; no live API or agent connection. Not a Minnesota or Texas topology, facility map, or interconnection result.",
      }}
      viewport={
        <>
        <section className="model-scene">
          <div className="model-scene__head">
            <div><p className="eyebrow">GEOGRAPHIC MODEL SCENE</p><p className="hint">Basemap context only. Feature geometry and 3D assets are unavailable.</p></div>
          </div>
          <MapLibreDeckFoundation adaptation={UNAVAILABLE_MODEL_SCENE} />
        </section>
        <article className="map">
          <div className="map-head">
            <div>
              <p className="eyebrow">NETWORK STATE · {scenario.label.toUpperCase()}</p>
              <p className="hint">Line weight tracks utilization. Hover or tab a corridor for its reading.</p>
            </div>
            <div className="map-actions">
              <div className="toggle" role="group" aria-label="Corridor colouring">
                <button className={view === "load" ? "on" : ""} onClick={() => setView("load")} aria-pressed={view === "load"}>Utilization</button>
                <button className={view === "delta" ? "on" : ""} onClick={() => setView("delta")} aria-pressed={view === "delta"}>Change vs baseline</button>
              </div>
              <button ref={disclosureTrigger} className="ghost" onClick={openDetail}>Data, units &amp; limits</button>
            </div>
          </div>

          <Network selected={selected} view={view} onSelect={select} hover={hover} setHover={setHover} />

          <div className="legend">
            {view === "load"
              ? <><i className="tone-low" />under 75% <i className="tone-mid" />75–89% <i className="tone-high" />90%+ <span>· {scenario.units.lineLoading} of rating</span></>
              : <><i className="tone-none" />unchanged <i className="tone-some" />relieved <i className="tone-strong" />15+ points relieved <span>· percentage points vs baseline</span></>}
          </div>
        </article>
        </>
      }
      comparison={<CompareRail selected={selected} onSelect={select} />}
      inspector={<Inspector asset={fixtureInspector} />}
      chat={
        <div className="agent-static">
          <ChatDock context={chatContext} contextRevision={contextRevision} sourceLabel="Checked-in synthetic fixture" sourceStatus="synthetic" status="unavailable" onContextChange={updateChatContext} />
          <section className="agent-static__trace" aria-label="Static agent run status">
            <h3>Run status</h3>
            <p>The static demo does not open a live agent connection.</p>
            <RunTrace state={staticRun} />
          </section>
          <ResultCards results={staticResults} />
        </div>
      }
      />

      {detail && (
        <div className="overlay" onMouseDown={closeDetail}>
          <section
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-label="Data disclosure"
            onMouseDown={(event) => event.stopPropagation()}
            onKeyDown={(event) => {
              if (event.key !== "Tab") return;
              // The disclosure currently has one native control; retain focus until it closes.
              event.preventDefault();
              disclosureClose.current?.focus();
            }}
          >
            <button ref={disclosureClose} onClick={closeDetail} aria-label="Close disclosure">×</button>
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
    </>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
