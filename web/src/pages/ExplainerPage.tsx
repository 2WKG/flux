/**
 * The explainer: the site's `/explainer` page (`src/router/index.ts`).
 *
 * It is loaded as its own chunk by `src/shell/SiteShell.tsx` and imports
 * neither the scenario fixture nor any scene, renderer, or map module. The
 * teaching sections disclose their evidence class and never substitute a model
 * result when their source is unavailable. The low-complexity cascade section
 * replays a trace solved on the server by `twin/toy_cascade.py`; no page here
 * solves anything in the browser.
 */
import { Component, type ReactNode } from "react";

import { CascadeSection } from "../explainer/cascade";
import { CausalSection } from "../explainer/causal";
import { GnnSection } from "../explainer/gnn";
import { JepaSection } from "../explainer/jepa";
import { FailureState } from "../failure-states/FailureState";

const METHOD = [
  ["The scenario math", "The scenario explorer solves nothing at runtime. It reads a checked-in fixture whose unmet demand, corridor loadings and candidate contributions were computed offline and frozen."],
  ["The causal layer", "Implemented and evidence-gated. The synthetic teaching figures are illustrative. The causal_query effect path is unavailable without a registered artifact."],
  ["The JEPA predictor", "Experimental. A joint-embedding predictor over outage counts is trained and evaluated outside this build. No prediction from it reaches any page here."],
  ["The GNN / grid foundation-model direction", "Aspirational. A graph export exists as a dataset; there is no trained grid foundation model behind this demo, and nothing on the site is produced by one."],
] as const;

class ExplainerSectionBoundary extends Component<
  { readonly label: string; readonly children: ReactNode },
  { readonly error: Error | null }
> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  render() {
    if (this.state.error) {
      return <section aria-label={`${this.props.label} unavailable`} data-source-status="unavailable">
        <FailureState
          state={{ kind: "unavailable", code: "explainer_section_unavailable", message: `${this.props.label} could not be rendered. No substitute values are shown.` }}
          onRetry={() => this.setState({ error: null })}
        />
      </section>;
    }
    return this.props.children;
  }
}

/** The explainer page teaches the method and asserts no unqualified model output. */
export function ExplainerPage() {
  return <main data-source-status="unavailable">
    <header className="shell-intro">
      <p className="eyebrow">METHOD / WHAT IS ACTUALLY RUNNING</p>
      <h1>How the math works, and how much of it is real.</h1>
      <p>The scenario explorer shows an answer. This page says where the answer comes from, which parts of the method are live, and which parts are still a direction rather than a result.</p>
    </header>
    <section className="method" aria-label="Method">
      {METHOD.map(([title, body]) => <article key={title} className="method-entry"><h2>{title}</h2><p>{body}</p></article>)}
    </section>
    <ExplainerSectionBoundary label="Low-complexity cascade section"><CascadeSection /></ExplainerSectionBoundary>
    <ExplainerSectionBoundary label="Causal teaching section"><CausalSection /></ExplainerSectionBoundary>
    <ExplainerSectionBoundary label="JEPA recorded evaluation"><JepaSection /></ExplainerSectionBoundary>
    <ExplainerSectionBoundary label="GNN teaching section"><GnnSection /></ExplainerSectionBoundary>
  </main>;
}
