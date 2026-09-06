import { useState } from "react";

import { FailureState } from "../failure-states/FailureState";
import { STATUS_COPY } from "../source-truth";
import {
  TOY_BUSES,
  TOY_CASCADE_ARTIFACT_ID,
  TOY_CASCADE_ROUTE,
  TOY_CASCADE_TRACE,
  TOY_LINES,
  type CascadeStage,
  type SolvedLine,
} from "./toyCascadeTrace";

/**
 * The module that produced the replayed trace. The route table's `truthNote`
 * names the same module, and `src/pages/explainerBoundary.test.mjs` fails if the
 * two ever disagree -- so the page cannot describe a solver it is not showing.
 */
export const SOLVER_MODULE = "twin/toy_cascade.py";

const METHOD = [
  [
    "The scenario math",
    "The main page reads a checked-in five-bus synthetic fixture. This page replays a separate, smaller synthetic network so every calculation can be inspected.",
  ],
  [
    "The causal layer",
    "Experimental. It produces offline evidence artifacts; this page does not calculate or display a causal estimate. See docs/specs/07-causal-layer.md.",
  ],
  [
    "The JEPA predictor",
    "Experimental. Training and evaluation happen outside this build. This page does not present a prediction from it.",
  ],
  [
    "The GNN direction",
    "Aspirational. A graph export exists as a dataset, but no trained grid foundation model produces an on-screen result here.",
  ],
] as const;

function rounded(value: number, digits = 1) {
  return Number(value.toFixed(digits)).toString();
}

function busAction(stage: CascadeStage, busId: string) {
  const action = stage.balanceActions.find((entry) => entry.busId === busId);
  if (!action) return "None";
  return `${action.kind === "shed_load" ? "shed" : "curtail"} ${rounded(action.mw)} MW`;
}

function lineStroke(line: SolvedLine, active: boolean) {
  if (!active) return "#3d5f7c";
  if (line.utilizationPct > 100) return "#ff7d68";
  return line.utilizationPct > 80 ? "#ffcc66" : "#46d7b0";
}

/** The utilization band, spelled out so no reading depends on colour alone. */
function band(line: SolvedLine) {
  if (line.utilizationPct > 100) return "over rating";
  return line.utilizationPct > 80 ? "near rating" : "within rating";
}

function NetworkDiagram({ stage }: { stage: CascadeStage }) {
  const buses = new Map(TOY_BUSES.map((bus) => [bus.id, bus]));
  const active = new Set(stage.activeLineIds);
  const solved = new Map(stage.lines.map((line) => [line.id, line]));
  return (
    <figure className="pipeline">
      <div>
        <p className="eyebrow">2D SYNTHETIC SCHEMATIC</p>
        <h2>{stage.title}</h2>
        <p>{stage.explanation}</p>
        <p>Line colour: green ≤80% · amber 81–100% · red &gt;100% · gray tripped. Each flow label repeats the band in words.</p>
      </div>
      <svg
        viewBox="0 0 680 390"
        role="img"
        aria-label={`Five-bus teaching network at ${stage.title}`}
        width="680"
        height="390"
      >
        {TOY_LINES.map((line) => {
          const from = buses.get(line.from)!;
          const to = buses.get(line.to)!;
          const midX = (from.x + to.x) / 2;
          const midY = (from.y + to.y) / 2;
          const result = solved.get(line.id);
          return (
            <g key={line.id}>
              <line
                x1={from.x}
                y1={from.y}
                x2={to.x}
                y2={to.y}
                stroke={result ? lineStroke(result, active.has(line.id)) : "#3d5f7c"}
                strokeWidth="7"
                strokeDasharray={result ? undefined : "10 8"}
              />
              <text x={midX} y={midY - 11} textAnchor="middle" fill="#edf5ff" fontSize="12">
                {result
                  ? `${rounded(result.flowMw)} MW / ${line.ratingMw} MW (${band(result)})`
                  : "TRIPPED"}
              </text>
            </g>
          );
        })}
        {TOY_BUSES.map((bus) => (
          <g key={bus.id}>
            <circle cx={bus.x} cy={bus.y} r="12" fill="#dceeff" stroke="#082035" strokeWidth="5" />
            <text x={bus.x} y={bus.y + 37} textAnchor="middle" fill="#c8dded" fontSize="12">
              {bus.name}
            </text>
          </g>
        ))}
      </svg>
      <figcaption>
        Diagram distances are illustrative. Reactance, ratings, and bus injections are the only
        inputs to the server solve this diagram replays.
      </figcaption>
    </figure>
  );
}

function BusBalance({ stage }: { stage: CascadeStage }) {
  return (
    <article className="method-entry">
      <h2>Bus balance</h2>
      <p>
        <code>P = generation − demand</code>. Before each DC solve the server balances every
        disconnected island by proportional load shedding or generation curtailment.
      </p>
      <table>
        <thead>
          <tr>
            <th>Bus</th>
            <th>P (MW)</th>
            <th>Angle θ</th>
            <th>Action</th>
          </tr>
        </thead>
        <tbody>
          {TOY_BUSES.map((bus) => (
            <tr key={bus.id}>
              <td>{bus.name}</td>
              <td>{rounded(stage.injectionsMw[bus.id])}</td>
              <td>{rounded(stage.angles[bus.id], 3)}</td>
              <td>{busAction(stage, bus.id)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </article>
  );
}

function LineArithmetic({ stage }: { stage: CascadeStage }) {
  return (
    <article className="method-entry">
      <h2>Each line’s DC arithmetic</h2>
      <p>
        <code>Fᵢⱼ = (θᵢ − θⱼ) / Xᵢⱼ</code>; utilization is <code>|F| / rating × 100</code>. A
        negative result means power runs opposite the line name.
      </p>
      <table>
        <thead>
          <tr>
            <th>Line</th>
            <th>Calculation</th>
            <th>Use</th>
          </tr>
        </thead>
        <tbody>
          {stage.lines.map((line) => (
            <tr key={line.id}>
              <td>{line.id}</td>
              <td>
                ({rounded(stage.angles[line.from], 3)} − {rounded(stage.angles[line.to], 3)}) /{" "}
                {line.reactance} = {rounded(line.flowMw)} MW
              </td>
              <td>
                {rounded(line.utilizationPct)}% ({band(line)})
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {stage.nextTripLineId ? (
        <p>
          <strong>Next trip the server recorded:</strong> remove <code>{stage.nextTripLineId}</code>
          , the most overloaded active line, then solve again.
        </p>
      ) : (
        <p>
          <strong>End of this teaching cascade:</strong> no active line exceeds its listed rating.
        </p>
      )}
    </article>
  );
}

function Arithmetic({ stage }: { stage: CascadeStage }) {
  return (
    <section className="method" aria-label="Arithmetic for the selected cascade stage">
      <BusBalance stage={stage} />
      <LineArithmetic stage={stage} />
    </section>
  );
}

/** A load-on-demand 2D teaching page with no main-scene imports and no solver. */
export function ExplainerPage() {
  const stages = TOY_CASCADE_TRACE.stages;
  const [stageIndex, setStageIndex] = useState(0);
  if (!stages.length) {
    return (
      <main data-source-status="unavailable">
        <FailureState
          state={{
            kind: "unavailable",
            code: "toy_cascade_trace_unavailable",
            message: `The persisted teaching cascade ${TOY_CASCADE_ARTIFACT_ID} carries no stages. Re-export it with scripts/export_toy_cascade_trace.py.`,
          }}
        />
      </main>
    );
  }
  const stage = stages[Math.min(stageIndex, stages.length - 1)];
  return (
    <main data-source-status="synthetic">
      <header className="shell-intro">
        <p className="eyebrow">
          {STATUS_COPY.synthetic.toUpperCase()} {TOY_CASCADE_TRACE.networkLabel.toUpperCase()} /
          LOW-COMPLEXITY DC CASCADE
        </p>
        <h1>How the math works: follow a five-bus cascade, one equation at a time.</h1>
        <p>
          This {TOY_CASCADE_TRACE.networkLabel} is deliberately synthetic, and it is not the main
          page’s fixture or the server’s ACTIVSg2000 topology. It recreates the chain a DC screening
          model follows—balance injections, solve line flows, compare a rating, trip an overload,
          and solve again—without claiming to describe a real grid.
        </p>
        <p data-trace-provenance={TOY_CASCADE_TRACE.traceHash}>
          Every number below was solved on the server by <code>{SOLVER_MODULE}</code>, frozen as{" "}
          <code>{TOY_CASCADE_ARTIFACT_ID}</code> (trace hash{" "}
          <code>{TOY_CASCADE_TRACE.traceHash}</code>) and served at{" "}
          <code>{TOY_CASCADE_ROUTE}</code>. This page replays that trace; it computes nothing.
        </p>
      </header>
      <section className="method" aria-label="Method status">
        {METHOD.map(([title, body]) => (
          <article key={title} className="method-entry">
            <h2>{title}</h2>
            <p>{body}</p>
          </article>
        ))}
      </section>
      <section className="pipeline" aria-label="Cascade controls">
        <div>
          <p className="eyebrow">STEP THROUGH THE RECORDED CASCADE</p>
          <h2>{stage.title}</h2>
          <p>
            Choose a stage to inspect the bus balances and per-line arithmetic the server recorded
            for it.
          </p>
        </div>
        <div role="group" aria-label="Cascade stage">
          <button
            type="button"
            onClick={() => setStageIndex(Math.max(0, stageIndex - 1))}
            disabled={stageIndex === 0}
          >
            Previous
          </button>{" "}
          <button
            type="button"
            onClick={() => setStageIndex(Math.min(stages.length - 1, stageIndex + 1))}
            disabled={stageIndex === stages.length - 1}
          >
            Next
          </button>
          <p aria-live="polite">
            Stage {stageIndex + 1} of {stages.length}
          </p>
        </div>
      </section>
      <NetworkDiagram stage={stage} />
      <Arithmetic stage={stage} />
      <section className="pipeline" aria-label="Simplifications">
        <div>
          <p className="eyebrow">WHAT THIS LEAVES OUT</p>
          <h2>A DC screening lesson, not an operational grid model.</h2>
        </div>
        <ul>
          <li>No reactive power or voltage constraints.</li>
          <li>No dynamics, stability, or restoration timeline.</li>
          <li>
            No protection settings or relay behavior; the teaching rule trips one most-overloaded
            line.
          </li>
          <li>Islands balance through proportional load shedding or generation curtailment.</li>
          <li>All topology, ratings, and injections here are synthetic teaching inputs.</li>
          {TOY_CASCADE_TRACE.limitations.map((limitation) => (
            <li key={limitation}>{limitation}</li>
          ))}
        </ul>
      </section>
    </main>
  );
}
