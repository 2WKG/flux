// The explainer's two structural boundaries: it pulls no 3D renderer into its
// chunk, and it carries no solver of its own -- the arithmetic it shows was
// solved by `twin/toy_cascade.py` and frozen into the committed artifact.
//
// The "one lazy chunk" property is owned by `web/test/routing.test.mjs`, which
// pins the same marker for both pages; it is deliberately not re-asserted here.
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const forbiddenImports = /(?:from\s*|import\s*\()["'](?:deck\.gl|@deck\.gl\/|maplibre-gl|react-map-gl)/;
// The shapes a browser-side DC solve needs. None may reappear on this page.
const solverShapes = [
  /solveLinearSystem|solveToyDc|runToyCascade/,
  /Gauss|augmented\s*\[/,
  /connectedComponents|balanceComponents/,
];

test("the explainer page mounts JEPA and does not deny its recorded evaluation", async () => {
  const pageSource = await readFile(new URL("./ExplainerPage.tsx", import.meta.url), "utf8");
  assert.match(pageSource, /import \{ JepaSection \} from "\.\.\/explainer\/jepa";/);
  assert.match(pageSource, /<JepaSection \/>/);
  assert.doesNotMatch(pageSource, /This page does not present a prediction from it\.|No prediction from it reaches any page here\./);
});

test("the explainer cascade section imports no 3D renderer and carries no solver of its own", async () => {
  const pageSource = await readFile(new URL("../explainer/cascade/CascadeSection.tsx", import.meta.url), "utf8");
  const traceSource = await readFile(new URL("../explainer/cascade/toyCascadeTrace.ts", import.meta.url), "utf8");
  assert.doesNotMatch(pageSource, forbiddenImports);
  assert.doesNotMatch(traceSource, forbiddenImports);
  for (const shape of solverShapes) {
    assert.doesNotMatch(pageSource, shape, `the page reintroduced a browser solve: ${shape}`);
    assert.doesNotMatch(traceSource, shape, `the trace module reintroduced a browser solve: ${shape}`);
  }
});

test("the route table's truth note names the same server module the page credits", async () => {
  const [pageSource, routerSource] = await Promise.all([
    readFile(new URL("../explainer/cascade/CascadeSection.tsx", import.meta.url), "utf8"),
    readFile(new URL("../router/index.ts", import.meta.url), "utf8"),
  ]);
  const declared = pageSource.match(/export const SOLVER_MODULE =\s*"([^"]+)"/);
  assert.ok(declared, "the cascade section must name the module that produced its trace");
  const explainerEntry = routerSource.slice(
    routerSource.indexOf('id: "explainer"'),
    routerSource.indexOf('id: "minnesota"'),
  );
  assert.ok(
    explainerEntry.includes(declared[1]),
    `the explainer truthNote does not name ${declared[1]}, so the legend and the page disagree`,
  );
  assert.doesNotMatch(
    explainerEntry,
    /no model runs in this build/,
    "the truthNote still claims no model runs, but the page replays a solved cascade",
  );
});

test("the committed trace is the artifact the server route serves", async () => {
  const [trace, routeSource] = await Promise.all([
    readFile(new URL("../../../data/explainer/toy-cascade-trace.json", import.meta.url), "utf8"),
    readFile(new URL("../../../copilot/routes/explainer.py", import.meta.url), "utf8"),
  ]);
  const parsed = JSON.parse(trace);
  assert.equal(parsed.networkProvenance, "synthetic_five_bus_teaching_network");
  assert.ok(parsed.stages.length > 1, "the frozen trace has no cascade to replay");
  assert.ok(
    routeSource.includes("data/explainer/toy-cascade-trace.json"),
    "the read route no longer serves the artifact the page replays",
  );
});
