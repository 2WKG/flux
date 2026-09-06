import { useMemo, useState } from "react";

import { FailureState } from "../failure-states/FailureState";
import { STATUS_COPY } from "../source-truth";
import { CausalSection } from "../explainer/causal";
import { runToyCascade, TOY_BUSES, TOY_LINES, type CascadeStage, type SolvedLine } from "./toyCascade";

const METHOD = [
  ["The scenario math", "The main page reads a checked-in five-bus synthetic fixture. This page uses a separate, smaller synthetic network so every calculation can be inspected."],
  ["The causal layer", "Implemented and evidence-gated. Toy figures on this page are illustrative. The causal_query effect path is unavailable without a registered artifact."],
  ["The JEPA predictor", "Experimental. Training and evaluation happen outside this build. This page does not present a prediction from it."],
  ["The GNN direction", "Aspirational. A graph export exists as a dataset, but no trained grid foundation model produces an on-screen result here."],
] as const;

function rounded(value: number, digits = 1) { return Number(value.toFixed(digits)).toString(); }
function busAction(stage: CascadeStage, busId: string) {
  const action = stage.balanceActions.find((entry) => entry.busId === busId);
  return action ? `${action.kind === "shed_load" ? "shed" : "curtail"} ${rounded(action.mw)} MW` : "None";
}
function lineStroke(line: SolvedLine, active: boolean) {
  if (!active) return "#3d5f7c";
  return line.utilizationPct > 100 ? "#ff7d68" : line.utilizationPct > 80 ? "#ffcc66" : "#46d7b0";
}

function NetworkDiagram({ stage }: { stage: CascadeStage }) {
  const buses = new Map(TOY_BUSES.map((bus) => [bus.id, bus]));
  const active = new Set(stage.activeLineIds);
  const solved = new Map(stage.lines.map((line) => [line.id, line]));
  return <figure className="pipeline"><div><p className="eyebrow">2D SYNTHETIC SCHEMATIC</p><h2>{stage.title}</h2><p>{stage.explanation}</p><p>Line colour: green ≤80% · amber 81–100% · red &gt;100% · gray tripped.</p></div>
    <svg viewBox="0 0 680 390" role="img" aria-label={`Five-bus toy network at ${stage.title}`} width="680" height="390">
      {TOY_LINES.map((line) => { const from = buses.get(line.from)!; const to = buses.get(line.to)!; const mx = (from.x + to.x) / 2; const my = (from.y + to.y) / 2; const result = solved.get(line.id); return <g key={line.id}><line x1={from.x} y1={from.y} x2={to.x} y2={to.y} stroke={result ? lineStroke(result, active.has(line.id)) : "#3d5f7c"} strokeWidth="7" strokeDasharray={result ? undefined : "10 8"} /><text x={mx} y={my - 11} textAnchor="middle" fill="#edf5ff" fontSize="12">{result ? `${rounded(result.flowMw)} MW / ${line.ratingMw} MW` : "TRIPPED"}</text></g>; })}
      {TOY_BUSES.map((bus) => <g key={bus.id}><circle cx={bus.x} cy={bus.y} r="12" fill="#dceeff" stroke="#082035" strokeWidth="5" /><text x={bus.x} y={bus.y + 37} textAnchor="middle" fill="#c8dded" fontSize="12">{bus.name}</text></g>)}
    </svg><figcaption>Diagram distances are illustrative. Reactance, ratings, and bus injections are the only inputs to this toy calculation.</figcaption></figure>;
}

function Arithmetic({ stage }: { stage: CascadeStage }) {
  return <section className="method" aria-label="Arithmetic for the selected cascade stage"><article className="method-entry"><h2>Bus balance</h2><p><code>P = generation − demand</code>. Before each DC solve, each disconnected island is balanced by proportional load shedding or generation curtailment.</p><table><thead><tr><th>Bus</th><th>P (MW)</th><th>Angle θ</th><th>Action</th></tr></thead><tbody>{TOY_BUSES.map((bus) => <tr key={bus.id}><td>{bus.name}</td><td>{rounded(stage.injectionsMw[bus.id])}</td><td>{rounded(stage.angles[bus.id], 3)}</td><td>{busAction(stage, bus.id)}</td></tr>)}</tbody></table></article>
    <article className="method-entry"><h2>Each line’s DC arithmetic</h2><p><code>Fᵢⱼ = (θᵢ − θⱼ) / Xᵢⱼ</code>; utilization is <code>|F| / rating × 100</code>. A negative result means power runs opposite the line name.</p><table><thead><tr><th>Line</th><th>Calculation</th><th>Use</th></tr></thead><tbody>{stage.lines.map((line) => <tr key={line.id}><td>{line.id}</td><td>({rounded(stage.angles[line.from], 3)} − {rounded(stage.angles[line.to], 3)}) / {line.reactance} = {rounded(line.flowMw)} MW</td><td>{rounded(line.utilizationPct)}%</td></tr>)}</tbody></table>{stage.nextTripLineId ? <p><strong>Next toy trip rule:</strong> remove <code>{stage.nextTripLineId}</code>, the most overloaded active line, then solve again.</p> : <p><strong>End of this toy cascade:</strong> no active line exceeds its listed rating.</p>}</article></section>;
}

/** A load-on-demand 2D teaching page with no main-scene imports. */
export function ExplainerPage() {
  const result = useMemo(() => { try { return { stages: runToyCascade(), error: null as Error | null }; } catch (error) { return { stages: [] as readonly CascadeStage[], error: error as Error }; } }, []);
  const [stageIndex, setStageIndex] = useState(0);
  if (result.error) return <main><FailureState state={{ kind: "failed", code: "toy_cascade_failed", message: result.error.message }} /></main>;
  const stage = result.stages[stageIndex];
  return <main data-source-status="synthetic"><header className="shell-intro"><p className="eyebrow">{STATUS_COPY.synthetic.toUpperCase()} / LOW-COMPLEXITY DC CASCADE</p><h1>How the math works: follow a five-bus cascade, one equation at a time.</h1><p>This small teaching network is deliberately synthetic. It recreates the chain a DC screening model follows—balance injections, solve line flows, compare a rating, trip an overload, and solve again—without claiming to describe a real grid.</p></header>
    <section className="method" aria-label="Method status">{METHOD.map(([title, body]) => <article key={title} className="method-entry"><h2>{title}</h2><p>{body}</p></article>)}</section>
    <section className="pipeline" aria-label="Cascade controls"><div><p className="eyebrow">STEP THROUGH THE TOY CASCADE</p><h2>{stage.title}</h2><p>Choose a stage to inspect the recalculated bus balances and every active line’s arithmetic.</p></div><div role="group" aria-label="Cascade stage"><button type="button" onClick={() => setStageIndex(Math.max(0, stageIndex - 1))} disabled={stageIndex === 0}>Previous</button>{" "}<button type="button" onClick={() => setStageIndex(Math.min(result.stages.length - 1, stageIndex + 1))} disabled={stageIndex === result.stages.length - 1}>Next</button><p aria-live="polite">Stage {stageIndex + 1} of {result.stages.length}</p></div></section>
    <NetworkDiagram stage={stage} /><Arithmetic stage={stage} />
    <CausalSection />
    <section className="pipeline" aria-label="Simplifications"><div><p className="eyebrow">WHAT THIS LEAVES OUT</p><h2>A DC screening lesson, not an operational grid model.</h2></div><ul><li>No reactive power or voltage constraints.</li><li>No dynamics, stability, or restoration timeline.</li><li>No protection settings or relay behavior; the toy rule trips one most-overloaded line.</li><li>Islands balance through proportional load shedding or generation curtailment.</li><li>All topology, ratings, and injections here are synthetic teaching inputs.</li></ul></section>
  </main>;
}
