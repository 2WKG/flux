import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { builtScriptNames } from "../../test/built-assets.mjs";

const marker = "Follow a five-bus cascade, one equation at a time.";
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
