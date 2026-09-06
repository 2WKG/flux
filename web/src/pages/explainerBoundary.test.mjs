import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { builtScriptNames } from "../../test/built-assets.mjs";

const marker = "How the math works: follow a five-bus cascade, one equation at a time.";
const forbiddenImports = /(?:from\s*|import\s*\()["'](?:deck\.gl|@deck\.gl\/|maplibre-gl|react-map-gl)/;

test("the explainer teaching module has no 3D-rendering import and remains a lazy chunk", async () => {
  const pageSource = await readFile(new URL("./ExplainerPage.tsx", import.meta.url), "utf8");
  const cascadeSource = await readFile(new URL("./toyCascade.ts", import.meta.url), "utf8");
  assert.doesNotMatch(pageSource, forbiddenImports);
  assert.doesNotMatch(cascadeSource, forbiddenImports);

  const names = await builtScriptNames();
  const chunks = new Map(await Promise.all(names.map(async (name) => [
    name,
    await readFile(new URL(`../../dist/assets/${name}`, import.meta.url), "utf8"),
  ])));
  assert.ok(!chunks.get("app.js").includes(marker), "entry bundle eagerly contains the explainer");
  const carrying = names.filter((name) => chunks.get(name).includes(marker));
  assert.equal(carrying.length, 1, "explainer teaching code must have exactly one lazy chunk");
});

test("ExplainerPage mounts CausalSection and the causal METHOD row is no longer experimental", async () => {
  const pageSource = await readFile(new URL("./ExplainerPage.tsx", import.meta.url), "utf8");
  assert.match(pageSource, /import \{ CausalSection \} from ["']\.\.\/explainer\/causal["']/);
  assert.match(pageSource, /<CausalSection\s*\/>/);
  const method = pageSource.match(/\["The causal layer",\s*"([^"]+)"\]/);
  assert.ok(method, "the causal METHOD row is missing");
  assert.match(method[1], /Implemented and evidence-gated/);
  assert.match(method[1], /illustrative/i);
  assert.match(method[1], /causal_query/);
  assert.match(method[1], /unavailable without a registered artifact/);
  assert.doesNotMatch(method[1], /Experimental/);
  assert.doesNotMatch(method[1], /does not calculate or display a causal estimate/);
});

test("the causal section stays 2D and cannot present a numeric causal_query effect", async () => {
  const section = await readFile(new URL("../explainer/causal/CausalSection.tsx", import.meta.url), "utf8");
  const toy = await readFile(new URL("../explainer/causal/causalToy.ts", import.meta.url), "utf8");
  const gate = await readFile(new URL("../explainer/causal/evidenceGate.ts", import.meta.url), "utf8");
  assert.doesNotMatch(section, forbiddenImports);
  assert.doesNotMatch(toy, forbiddenImports);
  assert.doesNotMatch(gate, forbiddenImports);
  assert.match(gate, /EXPLAINER_REGISTRY:\s*readonly RegisteredArtifact\[\]\s*=\s*\[\s*\]/);
  assert.match(section, /causalQuery\(SECTION_EFFECT_REQUEST\)/);
  assert.match(section, /response\.status === "available"/);
  assert.match(section, /kind:\s*"unavailable"/);
});
