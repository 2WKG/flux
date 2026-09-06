/**
 * The graph-neural-network teaching section of the explainer page (2WKG-485).
 *
 * Scope discipline, in order of importance:
 *
 * 1. **Status.** No graph neural network runs in Flux. There is no model, no
 *    training code, no checkpoint and no published error envelope, so this
 *    section renders the `not running` label and shows zero model output. It
 *    teaches the idea and the trade-off; it never implies a capability.
 * 2. **No fabricated numbers.** Every number on screen is either an input the
 *    reader can see (a reactance, a rating) or an exact count over the schematic
 *    graph (hops, neighbours, contingency candidates). There is no accuracy, no
 *    speed-up, no benchmark and no citation, because none has been verified.
 * 3. **Client-side, 2D.** Inline SVG and React state only: no WebGL, no network
 *    call, no import from the 3D scene.
 *
 * It is self-contained by design — two sibling sections are being built in
 * parallel and a later change mounts all three, so this file modifies nothing
 * outside `web/src/explainer/gnn/`.
 */
import { useMemo, useState } from "react";
import { STATUS_COPY } from "../../source-truth";

import {
  contingencyCounts,
  GNN_MODEL_OUTPUTS,
  GNN_STATUS,
  GNN_STATUS_EVIDENCE,
  hopDistances,
  messagePassingRounds,
  nodeDegrees,
  receptiveField,
  SCHEMATIC_EDGES,
  SCHEMATIC_NODES,
} from "./messagePassing";

const MAX_HOPS = 5;

/** Green for the seed, then cooler rings outward. Gray means this layer never saw the node. */
const HOP_FILL = ["#46d7b0", "#8fd3ff", "#6fb0e8", "#4f8dc7", "#3d6b9f", "#31537c"] as const;
const UNREACHED_FILL = "#20364a";
const EDGE_IDLE = "#2c4b64";
const EDGE_CARRYING = "#ffcc66";
const EDGE_SETTLED = "#3f7ba4";

const GRID_TO_GRAPH = [
  ["Bus", "Node", "Injection P = generation − demand, voltage class, whether it is a load or a source."],
  ["Line or transformer", "Edge", "Series reactance X and a thermal rating in MW. Both are already the inputs a DC screen uses."],
  ["Electrical neighbourhood", "1-hop neighbourhood", "A bus's flow is set by its own injection and by what its neighbours push into it."],
  ["Topology change", "Edge removal", "An outage is an edge dropped from the graph, which is why the same model shape covers every contingency."],
] as const;

function nodeFill(distance: number | null, layers: number): string {
  if (distance === null || distance > layers) return UNREACHED_FILL;
  return HOP_FILL[Math.min(distance, HOP_FILL.length - 1)];
}

function StatusBanner() {
  return (
    <article className="method-entry" aria-label="Graph neural network status">
      <h2>Status: not running</h2>
      <p>
        Flux has <strong>no graph neural network</strong>. No model definition, no training run, no
        checkpoint, no evaluation artifact. This section therefore shows no prediction, no accuracy
        figure, and no speed comparison — it explains the idea and the engineering trade-off, and stops
        there. What is on this page comes from graph structure you can count by eye.
      </p>
      <ul>
        {GNN_STATUS_EVIDENCE.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
      <table aria-label="Graph neural network model outputs">
        <thead><tr><th>Model field</th><th>Value</th></tr></thead>
        <tbody>
          <tr><td>Models</td><td>{GNN_MODEL_OUTPUTS.model_count}</td></tr>
          <tr><td>Recorded runs</td><td>{GNN_MODEL_OUTPUTS.run_count}</td></tr>
          <tr><td>Predictions</td><td>{GNN_MODEL_OUTPUTS.prediction_count}</td></tr>
          <tr><td>Published error metrics</td><td>{GNN_MODEL_OUTPUTS.published_error_metric_count}</td></tr>
        </tbody>
      </table>
      <p>
        The label flips to <em>experimental</em> only when a trained checkpoint and a published error
        envelope both exist, and even then only numbers from that artifact may appear here.
      </p>
    </article>
  );
}

function GridIsAGraph() {
  const degrees = nodeDegrees();
  const busiest = SCHEMATIC_NODES.reduce((best, node) => (degrees[node.id] > degrees[best.id] ? node : best));
  return (
    <section className="method" aria-label="The grid is already a graph">
      <article className="method-entry">
        <h2>The grid is already a graph</h2>
        <p>
          Nothing has to be converted. A power system is stored as buses joined by branches, which is a
          node set joined by an edge set. The features a learned model would read are the same ones the
          DC screen already reads: an injection per node, a reactance and a thermal rating per edge.
        </p>
        <table>
          <thead>
            <tr>
              <th>Power system</th>
              <th>Graph</th>
              <th>Features carried</th>
            </tr>
          </thead>
          <tbody>
            {GRID_TO_GRAPH.map(([grid, graph, features]) => (
              <tr key={grid}>
                <td>{grid}</td>
                <td>{graph}</td>
                <td>{features}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </article>
      <article className="method-entry">
        <h2>Why message passing is the natural shape</h2>
        <p>
          A bus's flow is not a function of that bus alone. It is set by its own injection and by what its
          neighbours push into it — and their flows are set the same way, one step further out. Message
          passing encodes exactly that: every layer, each node aggregates its neighbours' current state,
          combines it with its own, and updates. Stack K layers and each node has read everything within K
          hops.
        </p>
        <p>
          On the schematic below, <strong>{busiest.name}</strong> aggregates from {degrees[busiest.id]}{" "}
          neighbours per layer; the least-connected buses aggregate from{" "}
          {Math.min(...SCHEMATIC_NODES.map((node) => degrees[node.id]))}. That asymmetry is information the
          model gets for free from the topology, and it is why the same trained weights can be applied to a
          grid whose wiring changed.
        </p>
      </article>
    </section>
  );
}

function HopDiagram({ seedId, layers }: { seedId: string; layers: number }) {
  const distances = useMemo(() => hopDistances(seedId), [seedId]);
  const rounds = useMemo(() => messagePassingRounds(seedId, layers), [seedId, layers]);
  const carrying = new Set(rounds[rounds.length - 1].carryingEdgeIds);
  const nodes = new Map(SCHEMATIC_NODES.map((node) => [node.id, node]));
  return (
    <svg
      viewBox="0 0 708 320"
      role="img"
      aria-label={`Schematic nine-bus graph; ${layers} message-passing layers from ${
        nodes.get(seedId)?.name ?? seedId
      }`}
      width="708"
      height="320"
    >
      {SCHEMATIC_EDGES.map((edge) => {
        const from = nodes.get(edge.from)!;
        const to = nodes.get(edge.to)!;
        const fromDistance = distances[edge.from];
        const toDistance = distances[edge.to];
        const settled =
          fromDistance !== null && toDistance !== null && fromDistance <= layers && toDistance <= layers;
        const stroke = carrying.has(edge.id) ? EDGE_CARRYING : settled ? EDGE_SETTLED : EDGE_IDLE;
        return (
          <g key={edge.id}>
            <line
              x1={from.x}
              y1={from.y}
              x2={to.x}
              y2={to.y}
              stroke={stroke}
              strokeWidth={carrying.has(edge.id) ? 8 : 6}
            />
            <text
              x={(from.x + to.x) / 2}
              y={(from.y + to.y) / 2 - 10}
              textAnchor="middle"
              fill="#c8dded"
              fontSize="11"
            >
              X {edge.reactance} · {edge.ratingMw} MW
            </text>
          </g>
        );
      })}
      {SCHEMATIC_NODES.map((node) => {
        const distance = distances[node.id];
        const visible = distance !== null && distance <= layers;
        return (
          <g key={node.id}>
            <circle
              cx={node.x}
              cy={node.y}
              r={node.id === seedId ? 15 : 12}
              fill={nodeFill(distance, layers)}
              stroke={node.id === seedId ? "#edf5ff" : "#082035"}
              strokeWidth="5"
            />
            <text x={node.x} y={node.y + 34} textAnchor="middle" fill="#c8dded" fontSize="11">
              {node.name}
            </text>
            <text x={node.x} y={node.y + 47} textAnchor="middle" fill="#7fa3bd" fontSize="10">
              {visible ? `hop ${distance}` : "not yet seen"}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

function MessagePassingInteractive() {
  const [seedId, setSeedId] = useState(SCHEMATIC_NODES[0].id);
  const [layers, setLayers] = useState(1);
  const field = useMemo(() => receptiveField(seedId, layers), [seedId, layers]);
  const rounds = useMemo(() => messagePassingRounds(seedId, layers), [seedId, layers]);
  const nodeName = (id: string) => SCHEMATIC_NODES.find((node) => node.id === id)?.name ?? id;
  const newly = rounds[rounds.length - 1].newlyReached;
  return (
    <>
      <section className="pipeline" aria-label="Message-passing controls">
        <div>
          <p className="eyebrow">WATCH A SIGNAL SPREAD, ONE LAYER AT A TIME</p>
          <h2>{layers === 0 ? "Zero layers: each bus knows only itself" : `${layers} message-passing layer${layers === 1 ? "" : "s"}`}</h2>
          <p>
            Pick a bus where something changes — an outage, a demand spike — then add layers. Each layer is
            one hop of neighbour-to-neighbour aggregation. Amber edges are the ones carrying a message on
            this layer; gray buses have not been reached yet.
          </p>
        </div>
        <div role="group" aria-label="Message-passing controls">
          <label>
            Disturbed bus{" "}
            <select value={seedId} onChange={(event) => setSeedId(event.target.value)}>
              {SCHEMATIC_NODES.map((node) => (
                <option key={node.id} value={node.id}>
                  {node.name}
                </option>
              ))}
            </select>
          </label>
          <p>
            <button type="button" onClick={() => setLayers(Math.max(0, layers - 1))} disabled={layers === 0}>
              Fewer layers
            </button>{" "}
            <button
              type="button"
              onClick={() => setLayers(Math.min(MAX_HOPS, layers + 1))}
              disabled={layers === MAX_HOPS}
            >
              Add a layer
            </button>
          </p>
          <p aria-live="polite">
            {field.seenCount} of {field.totalCount} buses inside the receptive field · {field.blindCount}{" "}
            still invisible to this depth.
          </p>
        </div>
      </section>
      <figure className="pipeline">
        <div>
          <p className="eyebrow">2D SCHEMATIC GRAPH — NOT A REAL NETWORK</p>
          <h2>Nine buses, twelve branches</h2>
          <p>
            This topology is invented for teaching and is small enough to check by hand. It is not
            ACTIVSg2000, not Minnesota, and not any operating system. Positions are for legibility only;
            the reactance and rating printed on each edge are the electrical inputs.
          </p>
          <p>
            {newly.length
              ? `Layer ${layers} newly reaches: ${newly.map(nodeName).join(", ")}.`
              : layers === 0
                ? "No layers yet: every bus holds only its own features."
                : "No new bus is reached — the receptive field already covers the whole graph."}
          </p>
        </div>
        <HopDiagram seedId={seedId} layers={layers} />
        <figcaption>
          No model runs here. The colouring is breadth-first hop distance over the schematic topology —
          the shape of what a K-layer network could read, not what any network predicted.
        </figcaption>
      </figure>
    </>
  );
}

function TheTradeOff() {
  const counts = contingencyCounts();
  return (
    <>
      <section className="method" aria-label="Solver versus learned surrogate">
        <article className="method-entry">
          <h2>The DC solver: always right, always priced the same</h2>
          <p>
            The solver computes flows from physics. Give it injections, reactances and a topology and it
            returns the flows that topology implies — no training data, no distribution to drift out of,
            no silent failure mode. The cost is that it earns nothing from repetition: the ten-thousandth
            contingency costs a full solve, exactly like the first.
          </p>
        </article>
        <article className="method-entry">
          <h2>A learned surrogate: amortised, and approximate</h2>
          <p>
            A graph model moves the work forward in time. Training is expensive once; afterwards a
            forward pass is a fixed pile of matrix multiplies over the same graph. What you buy is
            throughput. What you pay is that the answer is an <em>estimate</em> — it can be wrong,
            it is least trustworthy on the unusual topologies that matter most, and it cannot tell you
            it is wrong.
          </p>
        </article>
      </section>
      <section className="pipeline" aria-label="Screen with the model, decide with the solver">
        <div>
          <p className="eyebrow">THE DESIGN RULE</p>
          <h2>Use the model to screen. Use the solver to decide.</h2>
          <p>
            The two are not competing for the same job. Screening asks <em>which of these thousands of
            cases deserve attention?</em> — an ordering problem, where being approximately right is
            useful and being fast is what makes the question askable at all. Deciding asks{" "}
            <em>is this case actually a violation?</em> — and that answer must be exact, so it comes from
            the solver, every time.
          </p>
          <p>
            The error that matters for a screen is therefore not average accuracy. It is the{" "}
            <strong>false-negative rate</strong>: how often a genuinely dangerous case is ranked low
            enough to be dropped. A screen tuned to keep that near zero passes more candidates through
            than it strictly needs to, and that is the correct trade.
          </p>
        </div>
        <div>
          <table>
            <thead>
              <tr>
                <th>On this schematic</th>
                <th>Candidates</th>
                <th>Who answers</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>N-1 (one branch out)</td>
                <td>{counts.n1}</td>
                <td>Solver alone is fine at this size</td>
              </tr>
              <tr>
                <td>N-2 (any two branches out)</td>
                <td>{counts.n2}</td>
                <td>Screen first, then solve the survivors</td>
              </tr>
            </tbody>
          </table>
          <p>
            Exact counts over the twelve schematic branches: {counts.edges} single outages, and{" "}
            {counts.edges} × {counts.edges - 1} ÷ 2 = {counts.n2} pairs. The pair count grows with the
            square of the branch count, which is why a real system's N-2 set outruns any budget of full
            solves long before it outruns a screen. Flux has no such screen today; the solver answers
            everything.
          </p>
        </div>
      </section>
    </>
  );
}

function BeforeAnyNumber() {
  return (
    <section className="pipeline" aria-label="What would have to exist first">
      <div>
        <p className="eyebrow">WHAT WOULD HAVE TO EXIST BEFORE A NUMBER APPEARS HERE</p>
        <h2>The gap between this explanation and a working screen.</h2>
      </div>
      <ul>
        <li>A labelled dataset: solved flows for many topologies, generated by the DC solver itself.</li>
        <li>A model definition and a training run that produces a checkpoint committed as an artifact.</li>
        <li>
          An evaluation on <em>held-out topologies</em>, not just held-out samples — a screen is only
          interesting on wiring it never trained on.
        </li>
        <li>
          A published error envelope stating the false-negative rate at the screening threshold, so the
          number on this page has a source.
        </li>
        <li>
          A decision path that still ends at the solver, so an approximation can never become the
          reported result.
        </li>
      </ul>
    </section>
  );
}

/** The self-contained GNN teaching section. Mounted by the explainer page in a separate change. */
export function GnnSection() {
  return (
    <section aria-label="Graph neural network surrogate" data-source-status="unavailable" data-gnn-status={GNN_STATUS}>
      <header className="shell-intro">
        <p className="eyebrow">{STATUS_COPY.unavailable} / GNN status: not running</p>
        <h1>The grid is a graph. A learned model would screen it; the solver still decides.</h1>
        <p>
          This section explains what a graph neural network would do for contingency screening, and why
          it would sit beside the DC solver rather than replace it. Flux does not run one. Nothing below
          is a Flux result.
        </p>
      </header>
      <section className="method" aria-label="Status">
        <StatusBanner />
      </section>
      <GridIsAGraph />
      <MessagePassingInteractive />
      <TheTradeOff />
      <BeforeAnyNumber />
    </section>
  );
}
