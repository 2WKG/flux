import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const root = new URL("../src/ask/results/", import.meta.url);

test("result cards bind returned citations and do not derive unsupported actions", async () => {
  const [component, types, harness] = await Promise.all([
    readFile(new URL("ResultCards.tsx", root), "utf8"),
    readFile(new URL("types.ts", root), "utf8"),
    readFile(new URL("harness.tsx", root), "utf8"),
  ]);
  assert.match(component, /item\.doc === doc && item\.page === page/);
  assert.match(component, /href={`#\$\{citationId\(citation\)\}`}/);
  assert.match(component, /No citations were returned with this answer/);
  assert.match(component, /Scene action unavailable/);
  assert.match(component, /Scene action was not applied/);
  assert.match(component, /Source-supported/);
  assert.match(component, /Undo \{action\.label\}/);
  assert.match(component, /Source status:/);
  assert.match(types, /"source_supported"/);
  assert.match(types, /"request_failed"/);
  assert.match(types, /action\.kind === "compare"/);
  assert.doesNotMatch(component + types, /illustrative/);
  assert.match(types, /action\.source === "fixture" && action\.geometry !== "synthetic"/);
  assert.match(harness, /unavailable-harness/);
  assert.match(harness, /empty-harness/);
  assert.match(harness, /failure-harness/);
});
