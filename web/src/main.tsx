import { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

type ScenarioId = "baseline" | "a" | "b";
type Bus = { id: string; name: string; x: number; y: number };
type Line = { id: string; from: string; to: string; capacityMw: number };
type Scenario = {
  label: string;
  shedMw: number;
  shedMwh: number;
  availableGenerationMw: number;
  demandMw: number;
  improvementMw: number;
  improvementMwh: number;
  lineLoadings: Record<string, number>;
  reasons: string[];
};
type Bundle = {
  fixtureHash: string;
  solverStatus: string;
  stress: { name: string; demandMultiplier: number; generationAvailability: number; durationHours: number };
  limitations: string[];
  sources: { label: string; detail: string }[];
  network: { buses: Bus[]; lines: Line[]; candidates: { id: "a" | "b"; name: string; busId: string; x: number; y: number; addedMw: number; description: string }[] };
  scenarios: Record<ScenarioId, Scenario>;
};

function loadingColor(value: number) {
  if (value >= 90) return "#f16b52";
  if (value >= 75) return "#f4bd4f";
  return "#42c7a5";
}

function Network({ bundle, selected, onSelect }: { bundle: Bundle; selected: ScenarioId; onSelect: (id: ScenarioId) => void }) {
  const buses = Object.fromEntries(bundle.network.buses.map((bus) => [bus.id, bus]));
  const loading = bundle.scenarios[selected].lineLoadings;
  return <svg className="network" viewBox="0 0 760 520" role="img" aria-label="Synthetic grid network">
    <rect x="0" y="0" width="760" height="520" rx="20" fill="#0d2138" />
    <g className="grid-lines">
      {bundle.network.lines.map((line) => {
        const from = buses[line.from]; const to = buses[line.to]; const percent = loading[line.id];
        return <g key={line.id}>
          <line x1={from.x} y1={from.y} x2={to.x} y2={to.y} stroke={loadingColor(percent)} strokeWidth="8" strokeLinecap="round" />
          <text x={(from.x + to.x) / 2} y={(from.y + to.y) / 2 - 10} textAnchor="middle" className="line-label">{percent}%</text>
        </g>;
      })}
    </g>
    {bundle.network.buses.map((bus) => <g key={bus.id}>
      <circle cx={bus.x} cy={bus.y} r="13" fill="#dcecff" stroke="#07121f" strokeWidth="5" />
      <text x={bus.x} y={bus.y + 32} textAnchor="middle" className="bus-label">{bus.name}</text>
    </g>)}
    {bundle.network.candidates.map((candidate) => <g key={candidate.id} className="candidate" onClick={() => onSelect(candidate.id)} tabIndex={0} role="button" aria-label={`Select ${candidate.name}`} onKeyDown={(event) => event.key === "Enter" && onSelect(candidate.id)}>
      <circle cx={candidate.x} cy={candidate.y - 34} r="17" fill={selected === candidate.id ? "#f4bd4f" : "#2f8cff"} stroke="#fff" strokeWidth="3" />
      <text x={candidate.x} y={candidate.y - 28} textAnchor="middle" className="pin-label">{candidate.id.toUpperCase()}</text>
    </g>)}
  </svg>;
}

function App() {
  const [bundle, setBundle] = useState<Bundle | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<ScenarioId>("baseline");
  const [showInfo, setShowInfo] = useState(false);

  const loadBundle = () => {
    setError(null);
    fetch("/demo/bundle.json", { cache: "no-store" })
      .then((response) => response.ok ? response.json() : Promise.reject(new Error(`Bundle load failed (${response.status})`)))
      .then((payload: Bundle) => setBundle(payload))
      .catch((reason: Error) => setError(`${reason.message}. Run python model/generate_demo.py, then retry.`));
  };

  useEffect(loadBundle, []);
  const scenario = bundle?.scenarios[selected];
  const selectedCandidate = useMemo(() => bundle?.network.candidates.find((candidate) => candidate.id === selected), [bundle, selected]);

  if (error) return <main className="error-card"><h1>Flux demo data is unavailable</h1><p>{error}</p><button onClick={loadBundle}>Retry</button></main>;
  if (!bundle || !scenario) return <main className="loading">Loading the offline demo bundle…</main>;

  return <main>
    <header className="hero">
      <div><p className="eyebrow">Flux · illustrative grid resilience</p><h1>Where does a 300 MW addition reduce modeled shedding most?</h1></div>
      <button className="secondary" onClick={() => setShowInfo(true)}>Sources & limits</button>
    </header>

    <section className="notice"><strong>Synthetic fixture:</strong> this offline five-bus model is a placeholder until D01 data is available. It is not a Texas-grid study or outage forecast.</section>

    <section className="scenario-tabs" aria-label="Scenario selection">
      {(["baseline", "a", "b"] as ScenarioId[]).map((id) => <button key={id} className={selected === id ? "active" : ""} onClick={() => setSelected(id)}>{bundle.scenarios[id].label}</button>)}
      <button className="reset" onClick={() => setSelected("baseline")}>Reset to baseline</button>
    </section>

    <section className="dashboard">
      <div className="map-card"><div className="card-title"><span>Synthetic branch loading</span><span className="legend"><i className="low" /> below 75% <i className="mid" /> 75–89% <i className="high" /> 90%+</span></div><Network bundle={bundle} selected={selected} onSelect={setSelected} /></div>
      <aside className="results-card">
        <p className="eyebrow">{scenario.label}</p>
        <div className="metric major"><span>Modeled shedding</span><strong>{scenario.shedMw} <small>MW</small></strong><em>{scenario.shedMwh} MWh over {bundle.stress.durationHours} hours</em></div>
        <div className="metric-grid">
          <div className="metric"><span>Change vs baseline</span><strong>{selected === "baseline" ? "—" : `−${scenario.improvementMw} MW`}</strong></div>
          <div className="metric"><span>Available generation</span><strong>{scenario.availableGenerationMw} MW</strong></div>
          <div className="metric"><span>Modeled demand</span><strong>{scenario.demandMw} MW</strong></div>
          <div className="metric"><span>Fixture hash</span><strong>{bundle.fixtureHash}</strong></div>
        </div>
        {selectedCandidate && <div className="candidate-copy"><h2>{selectedCandidate.name}</h2><p>{selectedCandidate.description}</p><ul>{scenario.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul></div>}
      </aside>
    </section>

    <section className="assumptions"><h2>Fixed stress assumptions</h2><dl><div><dt>Demand</dt><dd>{bundle.stress.demandMultiplier}× baseline</dd></div><div><dt>Generation availability</dt><dd>{Math.round(bundle.stress.generationAvailability * 100)}%</dd></div><div><dt>Snapshot duration</dt><dd>{bundle.stress.durationHours} hours</dd></div><div><dt>Calculation status</dt><dd>{bundle.solverStatus}</dd></div></dl></section>

    {showInfo && <div className="modal-backdrop" role="presentation" onMouseDown={() => setShowInfo(false)}><section className="modal" role="dialog" aria-modal="true" aria-label="Sources and limitations" onMouseDown={(event) => event.stopPropagation()}><button className="close" onClick={() => setShowInfo(false)} aria-label="Close">×</button><h2>Sources & limits</h2><ul>{bundle.sources.map((source) => <li key={source.label}><strong>{source.label}:</strong> {source.detail}</li>)}</ul><h3>What this does not establish</h3><ul>{bundle.limitations.map((limit) => <li key={limit}>{limit}</li>)}</ul></section></div>}
  </main>;
}

createRoot(document.getElementById("root")!).render(<App />);
