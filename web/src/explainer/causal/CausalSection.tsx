import { useMemo, useState } from "react";

import { FailureState } from "../../failure-states/FailureState";
import {
  assertModel,
  CAUSAL_EDGES,
  CAUSAL_MODEL,
  claimContrasts,
  contrast,
  intervene,
  outageRisk,
  variableById,
  type Contrast,
  type Variable,
  type VariableId,
} from "./causalToy";
import { causalQuery, SECTION_EFFECT_REQUEST } from "./evidenceGate";

/** The layer's status, written once and rendered wherever the section names it. */
export const CAUSAL_LAYER_STATUS = "Implemented and evidence-gated";

/**
 * Everything on this page's causal panels is computed from the illustrative
 * teaching model in `./causalToy.ts`. No number here is a fitted estimate, and
 * this string is attached to every figure that could be mistaken for one.
 */
const ILLUSTRATIVE = "Illustrative";

const NODE_LAYOUT: Readonly<Record<VariableId, { x: number; y: number }>> = {
  weather_severity: { x: 62, y: 34 },
  exposure: { x: 62, y: 124 },
  investment: { x: 62, y: 268 },
  line_failures: { x: 296, y: 124 },
  substation_loss: { x: 296, y: 30 },
  customers_out: { x: 512, y: 214 },
};

const NODE_WIDTH = 152;
const NODE_HEIGHT = 44;

function percent(value: number, digits = 1): string {
  return `${Number((value * 100).toFixed(digits))}%`;
}

function signedPercent(value: number, digits = 1): string {
  const formatted = percent(Math.abs(value), digits);
  if (Math.abs(value) < 5e-5) return "0%";
  return `${value > 0 ? "+" : "−"}${formatted}`;
}

function center(id: VariableId) {
  const node = NODE_LAYOUT[id];
  return { x: node.x + NODE_WIDTH / 2, y: node.y + NODE_HEIGHT / 2 };
}

interface Selection {
  readonly variableId: VariableId;
  readonly state: string;
}

/** Every (variable, state) pair the viewer may act on. The outcome is not one. */
function selectableOptions(model: readonly Variable[]): readonly (Selection & { label: string })[] {
  return model
    .filter((variable) => variable.id !== "customers_out")
    .flatMap((variable) =>
      variable.states.map((state, index) => ({
        variableId: variable.id,
        state,
        label: `${variable.label}: ${variable.stateLabels[index]}`,
      })),
    );
}

function GraphDiagram({ selection, intervening }: { selection: Selection; intervening: boolean }) {
  const cut = new Set(
    intervening
      ? CAUSAL_EDGES.filter(([, child]) => child === selection.variableId).map(
          ([parent, child]) => `${parent}->${child}`,
        )
      : [],
  );
  return (
    <figure className="pipeline" style={{ display: "block" }}>
      <div>
        <p className="eyebrow">2D STRUCTURAL DIAGRAM · {ILLUSTRATIVE.toUpperCase()}</p>
        <h2>The graph is the assumption</h2>
        <p>
          Node and edge names follow spec 07&rsquo;s hand-drawn network. Amber edges leave{" "}
          <strong>utility investment</strong>: it causes line failures and, separately, causes
          customers to lose power. That second edge is what makes a raw correlation between line
          failures and customers-out the wrong number to quote.
        </p>
      </div>
      <svg
        viewBox="0 0 700 330"
        role="img"
        width="700"
        height="330"
        aria-label={
          intervening
            ? `Causal graph with the edges into ${selection.variableId} deleted by the intervention`
            : "Causal graph: weather, exposure and investment into line failures, substation loss and customers out"
        }
      >
        <defs>
          <marker id="causal-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
            <path d="M 0 0 L 10 5 L 0 10 z" fill="#6f97b4" />
          </marker>
          <marker id="causal-arrow-confounder" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
            <path d="M 0 0 L 10 5 L 0 10 z" fill="#ffcc66" />
          </marker>
        </defs>
        {CAUSAL_EDGES.map(([parent, child]) => {
          const from = center(parent);
          const to = center(child);
          const isCut = cut.has(`${parent}->${child}`);
          const confounder = parent === "investment";
          return (
            <line
              key={`${parent}->${child}`}
              x1={from.x}
              y1={from.y}
              x2={to.x}
              y2={to.y}
              stroke={isCut ? "#3d5f7c" : confounder ? "#ffcc66" : "#6f97b4"}
              strokeWidth={isCut ? 2 : 3}
              strokeDasharray={isCut ? "9 7" : undefined}
              markerEnd={isCut ? undefined : `url(#causal-arrow${confounder ? "-confounder" : ""})`}
            />
          );
        })}
        {CAUSAL_MODEL.map((variable) => {
          const node = NODE_LAYOUT[variable.id];
          const selected = variable.id === selection.variableId;
          return (
            <g key={variable.id}>
              <rect
                x={node.x}
                y={node.y}
                width={NODE_WIDTH}
                height={NODE_HEIGHT}
                rx="10"
                fill={selected ? "#123a52" : "#0a1a2b"}
                stroke={selected ? "#46d7b0" : "#2c5573"}
                strokeWidth={selected ? 3 : 2}
              />
              <text x={node.x + NODE_WIDTH / 2} y={node.y + 20} textAnchor="middle" fill="#edf5ff" fontSize="13">
                {variable.label}
              </text>
              <text x={node.x + NODE_WIDTH / 2} y={node.y + 35} textAnchor="middle" fill="#9dbdd4" fontSize="11">
                {variable.states.join(" · ")}
              </text>
            </g>
          );
        })}
      </svg>
      <figcaption>
        {intervening
          ? `do(${selection.variableId} = ${selection.state}) deletes the dashed edges: whatever used to explain this node no longer travels with it.`
          : "Conditioning keeps every edge. The sub-population that already has this value carries its causes along."}
      </figcaption>
    </figure>
  );
}

function ContrastPanel({ result, intervening }: { result: Contrast; intervening: boolean }) {
  const shown = intervening ? result.intervened : result.observed;
  return (
    <article className="method-entry">
      <h2>
        {intervening ? "do(" : "P(customers out ≥ 5% | "}
        {result.variableId} = {result.state}
        {intervening ? ")" : ")"}
      </h2>
      <p>
        <strong style={{ fontSize: "1.8rem", color: "#edf5ff" }}>{percent(shown)}</strong>{" "}
        <span>of counties at least 5% out · {ILLUSTRATIVE.toLowerCase()}</span>
      </p>
      <table>
        <thead>
          <tr>
            <th>Operation</th>
            <th>Risk</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td>Condition: P(out | {result.variableId} = {result.state})</td>
            <td>{percent(result.observed)}</td>
          </tr>
          <tr>
            <td>Intervene: P(out | do({result.variableId} = {result.state}))</td>
            <td>{percent(result.intervened)}</td>
          </tr>
          <tr>
            <td>Gap the correlation would have hidden</td>
            <td>{signedPercent(result.gap)}</td>
          </tr>
        </tbody>
      </table>
      <p>
        {result.confounded
          ? "These disagree. The variable has causes in the graph, so the sub-population that already has this value is not the population you would create by setting it."
          : "These agree exactly. This variable has no parents in the graph, so there is nothing upstream for the sub-population to carry — an assumption the graph makes, not a fact the numbers established."}
      </p>
    </article>
  );
}

function MixPanel({ result }: { result: Contrast }) {
  return (
    <article className="method-entry">
      <h2>Why they differ: the upstream mix</h2>
      <p>
        Conditioning selects a sub-population; the shares below say who ends up in it. Intervening
        leaves those shares at their population values, because <code>do()</code> deletes the edges
        that produced them.
      </p>
      <table>
        <thead>
          <tr>
            <th>Upstream cause</th>
            <th>Conditioned</th>
            <th>Intervened</th>
            <th>Population</th>
          </tr>
        </thead>
        <tbody>
          {result.mix.map((row) => (
            <tr key={row.id}>
              <td>{row.stateLabel}</td>
              <td>{percent(row.observed)}</td>
              <td>{percent(row.intervened)}</td>
              <td>{percent(row.population)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p>All shares are {ILLUSTRATIVE.toLowerCase()}, computed from the toy CPTs in this bundle.</p>
    </article>
  );
}

function EvidenceGate() {
  const response = causalQuery(SECTION_EFFECT_REQUEST);
  if (response.status === "available") {
    // Unreachable with the shipped (empty) registry, but the branch exists so a
    // future registered artifact renders its own numbers rather than this copy.
    return (
      <article className="method-entry">
        <h2>Registered causal evidence</h2>
        <p>
          {response.estimand}: {response.answerNumbers.effect} (interval {response.interval[0]} to{" "}
          {response.interval[1]}, method <code>{response.method}</code>).
        </p>
      </article>
    );
  }
  return (
    <article className="method-entry">
      <h2>What the real tool answers here</h2>
      <p>
        This layer is <strong>{CAUSAL_LAYER_STATUS.toLowerCase()}</strong>. The fitted network,
        the difference-in-differences estimate and the counterfactual replay are produced offline
        and reach the copilot only through <code>copilot/tools/causal_query.py</code>, which reads
        deployment-registered artifacts and never estimates on demand.
      </p>
      <p>
        This static page registers no artifact, so the honest answer to{" "}
        <code>causal_query(kind=&quot;effect&quot;, treatment=&quot;hardening_saidi&quot;)</code> is
        the canonical unavailable envelope, carrying no effect number at all:
      </p>
      <FailureState
        state={{
          kind: "unavailable",
          code: response.unavailable.code,
          message: response.unavailable.message,
        }}
      />
      <p>
        The gate is not decorative. <code>causal/validation.py</code> refuses an interface fixture
        outright (<code>FIXTURE_NOT_ESTIMABLE</code>), refuses an artifact whose citations do not
        resolve to a declared source, and refuses any artifact carrying an unresolved{" "}
        <code>[UNVERIFIED]</code> claim. Each refusal returns the envelope above instead of a
        plausible number.
      </p>
    </article>
  );
}

/**
 * A self-contained teaching section for the causal layer.
 *
 * It mounts into the explainer page and imports nothing from the main scene. All
 * arithmetic is client-side, 2D, and synchronous: no WebGL, no deck.gl, no
 * network call, no map.
 */
export function CausalSection() {
  const model = useMemo(() => {
    try {
      return { model: assertModel(CAUSAL_MODEL), error: null as Error | null };
    } catch (error) {
      return { model: [] as readonly Variable[], error: error as Error };
    }
  }, []);
  const [selection, setSelection] = useState<Selection>({ variableId: "line_failures", state: "many" });
  const [intervening, setIntervening] = useState(false);

  const computed = useMemo(() => {
    if (model.error) return null;
    try {
      return {
        result: contrast(model.model, selection.variableId, selection.state),
        claims: claimContrasts(model.model),
        baseline: outageRisk(model.model),
        error: null as Error | null,
      };
    } catch (error) {
      return { result: null, claims: [], baseline: 0, error: error as Error };
    }
  }, [model, selection]);

  const failure = model.error ?? computed?.error ?? null;
  if (failure || !computed?.result) {
    return (
      <section aria-label="Causal layer">
        <FailureState
          state={{
            kind: "failed",
            code: "causal_toy_failed",
            message: failure?.message ?? "The causal teaching model produced no result.",
          }}
        />
      </section>
    );
  }
  const { result, claims, baseline } = computed;
  const options = selectableOptions(model.model);
  const selectedVariable = variableById(model.model, selection.variableId);
  const interventionRisk = outageRisk(intervene(model.model, { [selection.variableId]: selection.state }));

  return (
    <section aria-label="Causal layer" data-layer-status="implemented_evidence_gated">
      <header className="shell-intro">
        <p className="eyebrow">CAUSAL LAYER · {CAUSAL_LAYER_STATUS.toUpperCase()}</p>
        <h1>Two true sentences that are not the same claim.</h1>
        <p>
          &ldquo;Storms cause outages&rdquo; and &ldquo;under-invested areas have more
          outages&rdquo; can both hold in the same data and still answer different questions. The
          first is about weather nobody chooses. The second is about spending somebody chooses —
          and it is the one a policy decision turns on. A correlation cannot tell them apart,
          because the same rows support both. Separating them takes a stated structure: which
          variable causes which, written down before the arithmetic starts.
        </p>
        <p>
          Below, that structure is spec 07&rsquo;s graph, shrunk so every number is recomputable by
          hand. Each figure is <strong>{ILLUSTRATIVE.toLowerCase()}</strong>: it comes from the toy
          conditional tables in this bundle, not from a fitted model, and not from{" "}
          <code>causal_query</code>.
        </p>
      </header>

      <section className="method" aria-label="The confounder">
        <article className="method-entry">
          <h2>The confounder, concretely</h2>
          <p>
            Utility investment sits upstream of two things at once. An under-invested county has
            more line failures <em>and</em> — through older distribution plant and slower crews —
            more customers in the dark for the same failures. So when you compare counties that
            had many line failures against counties that had none, you are also comparing
            under-invested counties against maintained ones. Part of the difference you measure is
            the investment, not the failures.
          </p>
        </article>
        <article className="method-entry">
          <h2>Why structure, not more data</h2>
          <p>
            Collecting more county-storms does not fix this. The bias is not noise that averages
            out; it is a second path from investment to the outcome that the comparison keeps
            walking. You remove it by naming the paths and cutting the ones that do not represent
            the action you are asking about — which is what <code>do()</code> is.
          </p>
        </article>
        <article className="method-entry">
          <h2>Baseline</h2>
          <p>
            Across this whole toy population, {percent(baseline)} of county-windows reach at least
            5% of customers out. Every comparison below is against that, and every one of these
            numbers is {ILLUSTRATIVE.toLowerCase()}.
          </p>
        </article>
      </section>

      <section className="pipeline" aria-label="Condition or intervene">
        <div>
          <p className="eyebrow">SET A VARIABLE — TWO WAYS</p>
          <h2>Condition on it, or intervene on it</h2>
          <p>
            <strong>Condition</strong> answers &ldquo;among counties where this is already
            true, what happens?&rdquo; <strong>Intervene</strong> answers &ldquo;if we made this
            true everywhere, what happens?&rdquo; Same variable, same model, different question.
            Pick a variable and watch whether the two answers agree.
          </p>
        </div>
        <div>
          <label htmlFor="causal-selection">Variable and state</label>{" "}
          <select
            id="causal-selection"
            value={`${selection.variableId}:${selection.state}`}
            onChange={(event) => {
              const [variableId, state] = event.target.value.split(":");
              setSelection({ variableId: variableId as VariableId, state });
            }}
          >
            {options.map((option) => (
              <option key={`${option.variableId}:${option.state}`} value={`${option.variableId}:${option.state}`}>
                {option.label}
              </option>
            ))}
          </select>
          <div role="group" aria-label="Operation">
            <button type="button" onClick={() => setIntervening(false)} disabled={!intervening}>
              Condition
            </button>{" "}
            <button type="button" onClick={() => setIntervening(true)} disabled={intervening}>
              Intervene — do()
            </button>
          </div>
          <p aria-live="polite">
            {intervening ? "Intervening on " : "Conditioning on "}
            {selectedVariable.label} = {selection.state}: {percent(intervening ? interventionRisk : result.observed)}{" "}
            reach at least 5% out ({ILLUSTRATIVE.toLowerCase()}).
          </p>
        </div>
      </section>

      <GraphDiagram selection={selection} intervening={intervening} />

      <section className="method" aria-label="Conditioning versus intervening">
        <ContrastPanel result={result} intervening={intervening} />
        <MixPanel result={result} />
      </section>

      <section className="method" aria-label="Claims side by side">
        <article className="method-entry" style={{ gridColumn: "1 / -1" }}>
          <h2>The two sentences, and the one that breaks</h2>
          <table>
            <thead>
              <tr>
                <th>Claim</th>
                <th>Correlation</th>
                <th>Intervention</th>
                <th>Agree?</th>
              </tr>
            </thead>
            <tbody>
              {claims.map((claim) => (
                <tr key={claim.id}>
                  <td>
                    {claim.claim}
                    <br />
                    <small>{claim.note}</small>
                  </td>
                  <td>{signedPercent(claim.observedDifference)}</td>
                  <td>{signedPercent(claim.interventionalDifference)}</td>
                  <td>{claim.agrees ? "Yes" : "No"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p>
            All four columns are {ILLUSTRATIVE.toLowerCase()}. Read the pattern, not the level: two
            claims survive the swap only because this graph declares their variable to have no
            causes, and the third does not survive it at all.
          </p>
        </article>
      </section>

      <section className="method" aria-label="Evidence gate">
        <EvidenceGate />
        <article className="method-entry">
          <h2>What this section leaves out</h2>
          <ul>
            <li>
              Spec 07 discretises weather severity and customers-out into four states each; this
              miniature uses two, so no number here matches a fitted CPT.
            </li>
            <li>
              The graph is hand-specified, not discovered. Nothing on this page tests whether the
              edges are the right ones.
            </li>
            <li>
              The real <code>investment</code> node is a proxy — a SAIDI trend that is partly an
              outcome of the same weather — so treating it as a root, here and in the fitted model,
              is an assumption that weakens the second claim.
            </li>
            <li>
              The middle of the chain (<code>line_failures</code>, <code>substation_loss</code>)
              comes from the synthetic ACTIVSg2000 twin in the real pipeline, so it is
              model-derived rather than observed.
            </li>
            <li>
              No estimate, interval, refutation, or citation on this page came from{" "}
              <code>hardening_effect.json</code>, <code>causal_attribution</code>, or{" "}
              <code>counterfactual_runs</code>. This bundle reads none of them.
            </li>
          </ul>
        </article>
      </section>
    </section>
  );
}
