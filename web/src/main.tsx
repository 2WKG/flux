import { useState } from "react";
import { createRoot } from "react-dom/client";
import fixture from "../../data/demo/bundle.json";
import "./styles.css";

type Id = "baseline" | "a" | "b";
type Provenance = { sourceId: string; sourceRef: string; sourceVersion: string; scope: string; artifactId: string; inputHash: string };
type Scenario = {
  id: Id; label: string; status: "available"; modelMode: string; assumptionSetId: string;
  intervention: null | { id: string; capacityMw: number; modeledContributionMw: number; description: string };
  metrics: { shedMw: number; shedMwh: number; availableGenerationMw: number; demandMw: number; improvementMw: number; lineLoadings: Record<string, number> };
  units: { shedMw: string; shedMwh: string; availableGenerationMw: string; demandMw: string; improvementMw: string; lineLoading: string };
  provenance: Provenance; limitations: string[];
};
type Bundle = {
  schemaVersion: number; fixtureHash: string;
  execution: { status: "available"; modelMode: string; assumptionSetId: string; assumptions: { name: string; demandMultiplier: number; generationAvailabilityFraction: number; durationHours: number; notes: string[] }; provenance: Provenance; limitations: string[] };
  network: { buses: { id: string; name: string; x: number; y: number }[]; lines: { id: string; from: string; to: string }[]; candidates: { id: Id; name: string; busId: string; x: number; y: number; capacityMw: number; description: string }[] };
  scenarios: Record<Id, Scenario>;
};
const color = (n: number) => n >= 90 ? "#ff7d68" : n >= 75 ? "#ffcc66" : "#46d7b0";

function Network({ data, selected, select }: { data: Bundle; selected: Id; select: (x: Id) => void }) {
  const buses = Object.fromEntries(data.network.buses.map(bus => [bus.id, bus]));
  const loads = data.scenarios[selected].metrics.lineLoadings;
  return <svg viewBox="0 0 760 540" className="network" aria-label="Synthetic scenario comparison network">
    {data.network.lines.map(line => { const from = buses[line.from], to = buses[line.to], value = loads[line.id]; return <g key={line.id}><line x1={from.x} y1={from.y} x2={to.x} y2={to.y} stroke={color(value)} /><text x={(from.x + to.x) / 2} y={(from.y + to.y) / 2 - 12}>{value}%</text></g>; })}
    {data.network.buses.map(bus => <g key={bus.id}><circle cx={bus.x} cy={bus.y} r="12"/><text x={bus.x} y={bus.y + 32}>{bus.name}</text></g>)}
    {data.network.candidates.map(candidate => <g key={candidate.id} className="pin" onClick={() => select(candidate.id)} role="button" tabIndex={0} aria-label={`Select ${candidate.name}`}><circle cx={candidate.x} cy={candidate.y - 38} r="18" className={selected === candidate.id ? "chosen" : ""}/><text x={candidate.x} y={candidate.y - 32}>{candidate.id.toUpperCase()}</text></g>)}
  </svg>;
}

function App() {
  const [selected, setSelected] = useState<Id>("baseline");
  const [detail, setDetail] = useState(false);
  const data: Bundle = fixture as unknown as Bundle;
  const scenario = data.scenarios[selected];
  const candidate = data.network.candidates.find(item => item.id === selected);
  const sameAssumptions = Object.values(data.scenarios).every(item => item.assumptionSetId === data.execution.assumptionSetId);

  return <main><nav><div className="brand"><b>FLUX</b><span>Resilience desk</span></div><div className="live"><i/> bundled synthetic fixture · no API required</div><button onClick={() => setDetail(true)}>Data, units & limits</button></nav>
    <header><p className="eyebrow">SYSTEM RESILIENCE / SCENARIO EXPLORER</p><h1>Choose where added capacity makes the largest modeled difference.</h1><p>Selections use a checked-in, precomputed scenario artifact; no runtime data request is made. The output remains explicitly synthetic.</p></header>
    <section className="bar"><div><span>Scenario</span><label><select value={selected} onChange={event => setSelected(event.target.value as Id)} aria-label="Scenario selector">{(Object.keys(data.scenarios) as Id[]).map(id => <option key={id} value={id}>{data.scenarios[id].label}</option>)}</select></label></div><div><span>Assumption set</span><strong>{data.execution.assumptionSetId}</strong></div><div><span>Stress</span><strong>{data.execution.assumptions.demandMultiplier}× demand · {Math.round(data.execution.assumptions.generationAvailabilityFraction * 100)}% available</strong></div><div><span>Window</span><strong>{data.execution.assumptions.durationHours} h · output v{data.schemaVersion}</strong></div></section>
    <section className="switcher">{(Object.keys(data.scenarios) as Id[]).map(id => <button className={id === selected ? "selected" : ""} onClick={() => setSelected(id)} key={id}><small>{id === "baseline" ? "00" : id.toUpperCase()}</small>{data.scenarios[id].label}</button>)}<button className="reset" onClick={() => setSelected("baseline")}>Reset view</button></section>
    <section className="workspace"><article className="map"><div className="section-title"><span>NETWORK STATE · {scenario.modelMode}</span><p>Branch utilization <i className="low"/> normal <i className="mid"/> elevated <i className="high"/> constrained · {scenario.units.lineLoading}</p></div><Network data={data} selected={selected} select={setSelected}/><div className="map-footer">SYNTHETIC FIVE-BUS NETWORK <b>•</b> values derived from {scenario.provenance.artifactId}</div></article>
      <aside><div className="outcome"><p className="eyebrow">MODELED UNMET DEMAND</p><strong>{scenario.metrics.shedMw}<small> {scenario.units.shedMw}</small></strong><p>{scenario.metrics.shedMwh} {scenario.units.shedMwh} across the fixed window</p><div className="delta">{selected === "baseline" ? "Baseline reference" : `−${scenario.metrics.improvementMw} ${scenario.units.improvementMw} vs baseline`}</div></div><div className="stats"><div><span>Demand</span><b>{scenario.metrics.demandMw} {scenario.units.demandMw}</b></div><div><span>Available supply</span><b>{scenario.metrics.availableGenerationMw} {scenario.units.availableGenerationMw}</b></div></div>{candidate && <div className="insight"><p className="eyebrow">{candidate.name} / +{candidate.capacityMw} MW candidate</p><h2>{candidate.description}</h2><p>Modeled contribution: {scenario.intervention?.modeledContributionMw} MW. This is a fixture assumption, not an interconnection result.</p></div>}</aside></section>
    <section className="pipeline"><div><p className="eyebrow">SOURCE + MODEL CONTRACT</p><h2>Same assumptions. Traceable synthetic output.</h2></div><p>{sameAssumptions ? "Every displayed option has the same documented demand, duration, and baseline-generation assumptions." : "Comparison unavailable: scenario assumptions differ."} Bundled source artifact: <code>{data.execution.provenance.sourceRef}</code>.</p></section>
    {detail && <div className="overlay" onMouseDown={() => setDetail(false)}><section className="modal" onMouseDown={event => event.stopPropagation()}><button onClick={() => setDetail(false)} aria-label="Close disclosure">×</button><p className="eyebrow">DATA DISCLOSURE</p><h2>Provenance, assumptions, and limits</h2><dl><dt>Artifact</dt><dd>{data.execution.provenance.artifactId} · hash {data.execution.provenance.inputHash}</dd><dt>Source</dt><dd>{data.execution.provenance.sourceId} ({data.execution.provenance.sourceVersion})</dd><dt>Source reference</dt><dd><code>{data.execution.provenance.sourceRef}</code></dd><dt>Scope</dt><dd>{data.execution.provenance.scope}</dd></dl><ul>{data.execution.assumptions.notes.map(note => <li key={note}>{note}</li>)}</ul><ul>{data.execution.limitations.map(limit => <li key={limit}>{limit}</li>)}</ul></section></div>}
  </main>;
}

createRoot(document.getElementById("root")!).render(<App/>);
