/**
 * The explainer: the site's `/explainer` page (`src/router/index.ts`).
 *
 * It is loaded as its own chunk by `src/shell/SiteShell.tsx` and imports
 * neither the scenario fixture nor any scene, renderer, or map module -- the
 * whole point of splitting the entries is that a visitor here downloads none of
 * that.
 *
 * The teaching content itself is 2WKG-482. What this page may not do, now or
 * then, is imply that a model is running when none is: the low-complexity
 * simulation, the causal layer, the JEPA predictor and the GNN direction are
 * all named below as what they are, and the missing simulation is rendered by
 * the shared request-state component rather than by a placeholder that looks
 * like output.
 */
import { FailureState } from "../failure-states/FailureState";

const METHOD = [
  {
    title: "The scenario math",
    body:
      "The scenario explorer solves nothing at runtime. It reads a checked-in five-bus fixture whose "
      + "unmet demand, corridor loadings and candidate contributions were computed offline and frozen.",
  },
  {
    title: "The causal layer",
    body:
      "Experimental. It is specified in docs/specs/07-causal-layer.md and produces evidence artifacts "
      + "offline; no causal estimate is computed in the browser and none is displayed on this page.",
  },
  {
    title: "The JEPA predictor",
    body:
      "Experimental. A joint-embedding predictor over outage counts is being trained and evaluated "
      + "outside this build. No prediction from it reaches any page here.",
  },
  {
    title: "The GNN / grid foundation-model direction",
    body:
      "Aspirational. The graph export exists as a dataset; there is no trained grid foundation model "
      + "behind this demo, and nothing on the site is produced by one.",
  },
];

/** The explainer page. It teaches the method and asserts no model output. */
export function ExplainerPage() {
  return (
    <main data-source-status="unavailable">
      <header className="shell-intro">
        <p className="eyebrow">METHOD / WHAT IS ACTUALLY RUNNING</p>
        <h1>How the math works, and how much of it is real.</h1>
        <p>
          The scenario explorer shows an answer. This page says where the answer comes from, which parts of
          the method are live, and which parts are still a direction rather than a result.
        </p>
      </header>

      <section className="method" aria-label="Method">
        {METHOD.map((entry) => (
          <article key={entry.title} className="method-entry">
            <h2>{entry.title}</h2>
            <p>{entry.body}</p>
          </article>
        ))}
      </section>

      <section className="pipeline" aria-label="Low-complexity simulation">
        <div>
          <p className="eyebrow">LOW-COMPLEXITY SIMULATION</p>
          <h2>The teaching simulation is not part of this build.</h2>
        </div>
        <FailureState
          state={{
            kind: "unavailable",
            message:
              "The explainer's own low-complexity simulation is not in this build. Nothing on this page is "
              + "model output, and no figure is shown in place of one.",
          }}
        />
      </section>
    </main>
  );
}
