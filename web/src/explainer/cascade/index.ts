/**
 * Integration surface for the explainer page's low-complexity cascade section.
 *
 * `<CascadeSection />` mounts in `web/src/pages/ExplainerPage.tsx` alongside the
 * other teaching sections. It replays the server trace frozen at
 * `data/explainer/toy-cascade-trace.json`; nothing in this directory solves, and
 * nothing here imports the main scene.
 */
export { CASCADE_HEADLINE, CascadeSection, SOLVER_MODULE } from "./CascadeSection";
