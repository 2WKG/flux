/**
 * The explainer's low-complexity cascade section.
 *
 * It replays a cascade the SERVER solved. `twin/toy_cascade.py` runs the DC
 * screening chain, `scripts/export_toy_cascade_trace.py` freezes the result into
 * `data/explainer/toy-cascade-trace.json`, and `GET /explainer/toy-cascade`
 * serves those exact bytes. Nothing here computes a flow, an angle, or a trip:
 * every number on screen is read out of that artifact, and the section names the
 * artifact and its hash so a reader can re-solve it.
 *
 * This section imports no scene, renderer or map module, and no solver.
 */
import { useState } from "react";

import { FailureState } from "../../failure-states/FailureState";
import { STATUS_COPY } from "../../source-truth";
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
 * The server module that produced the replayed trace. The route table's
 * `truthNote` names the same module, and `src/pages/explainerBoundary.test.mjs`
 * fails if the two disagree -- so the legend cannot describe a solver the page
 * is not showing.
 */
export const SOLVER_MODULE = "twin/toy_cascade.py";

/** The sentence `web/test/routing.test.mjs` pins as this page's chunk marker. */
export const CASCADE_HEADLINE =
  "How the math works: follow a five-bus cascade, one equation at a time.";

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

/** The utilization band in words, so no reading depends on colour alone. */
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
        <h3>{stage.title}</h3>
        <p>{stage.explanation}</p>
        <p>
          Line colour: green ≤80% · amber 81–100% · red &gt;100% · gray tripped. Every flow label
          repeats the band in words.
        </p>
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
      <h3>Bus balance</h3>
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
      <h3>Each line’s DC arithmetic</h3>
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

/** The mounted section: a replayed server cascade, never a browser solve. */
export function CascadeSection() {
  const stages = TOY_CASCADE_TRACE.stages;
  const [stageIndex, setStageIndex] = useState(0);
  if (!stages.length) {
    return (
      <section
        className="pipeline"
        aria-label="Low-complexity cascade unavailable"
        data-source-status="unavailable"
      >
        <FailureState
          state={{
            kind: "unavailable",
            code: "toy_cascade_trace_unavailable",
            message: `The persisted teaching cascade ${TOY_CASCADE_ARTIFACT_ID} carries no stages, so no cascade is shown in place of one. Re-export it with scripts/export_toy_cascade_trace.py.`,
          }}
        />
      </section>
    );
  }
  const stage = stages[Math.min(stageIndex, stages.length - 1)];
  return (
    <section
      className="pipeline"
      aria-label="Low-complexity cascade"
      data-source-status="synthetic"
      data-trace-hash={TOY_CASCADE_TRACE.traceHash}
    >
      <div>
        <p className="eyebrow">
          {STATUS_COPY.synthetic.toUpperCase()} {TOY_CASCADE_TRACE.networkLabel.toUpperCase()} /
          LOW-COMPLEXITY DC CASCADE
        </p>
        <h2>{CASCADE_HEADLINE}</h2>
        <p>
          This {TOY_CASCADE_TRACE.networkLabel} is deliberately synthetic, and it is not the
          scenario explorer’s fixture or the server’s ACTIVSg2000 topology. It recreates the chain a
          DC screening model follows—balance injections, solve line flows, compare a rating, trip an
          overload, and solve again—without claiming to describe a real grid.
        </p>
        <p>
          Every number below was solved on the server by <code>{SOLVER_MODULE}</code>, frozen as{" "}
          <code>{TOY_CASCADE_ARTIFACT_ID}</code> (trace hash{" "}
          <code>{TOY_CASCADE_TRACE.traceHash}</code>) and served at{" "}
          <code>{TOY_CASCADE_ROUTE}</code>. This section replays that trace; it computes nothing.
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
      <NetworkDiagram stage={stage} />
      <div className="method">
        <BusBalance stage={stage} />
        <LineArithmetic stage={stage} />
      </div>
      <div>
        <p className="eyebrow">WHAT THIS LEAVES OUT</p>
        <h3>A DC screening lesson, not an operational grid model.</h3>
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
      </div>
    </section>
  );
}
