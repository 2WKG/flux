/**
 * Integration surface for the explainer page's causal-layer section.
 *
 * A separate change mounts `<CausalSection />` into `web/src/pages/ExplainerPage.tsx`
 * alongside the other teaching sections. Nothing outside this directory is
 * modified to add it, and nothing in this directory imports the main scene.
 */
export { CausalSection, CAUSAL_LAYER_STATUS } from "./CausalSection";
