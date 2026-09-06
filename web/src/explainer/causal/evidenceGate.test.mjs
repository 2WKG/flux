import assert from "node:assert/strict";
import { build } from "esbuild";
import { mkdir } from "node:fs/promises";
import test from "node:test";
import { fileURLToPath } from "node:url";

const compiled = new URL("../../../node_modules/.cache/causal-evidence-gate.mjs", import.meta.url);
await mkdir(new URL(".", compiled), { recursive: true });
await build({
  entryPoints: [fileURLToPath(new URL("./evidenceGate.ts", import.meta.url))],
  bundle: true,
  format: "esm",
  platform: "node",
  outfile: fileURLToPath(compiled),
});
const {
  causalQuery,
  EXPLAINER_REGISTRY,
  SECTION_EFFECT_REQUEST,
  FIXTURE_NOT_ESTIMABLE,
} = await import(`${compiled.href}?t=${Date.now()}`);

function hasEffectNumber(response) {
  return "answerNumbers" in response || "effect" in response || Boolean(response.answerNumbers?.effect);
}

test("the empty explainer registry returns artifact_unavailable with no effect", () => {
  assert.deepEqual(EXPLAINER_REGISTRY, []);
  const response = causalQuery(SECTION_EFFECT_REQUEST, EXPLAINER_REGISTRY);
  assert.equal(response.status, "unavailable");
  assert.equal(response.unavailable.code, "artifact_unavailable");
  assert.equal(hasEffectNumber(response), false);
});

test("an interface fixture is refused and never yields an effect number", () => {
  const response = causalQuery(SECTION_EFFECT_REQUEST, [
    {
      request: SECTION_EFFECT_REQUEST,
      artifact: { classification: "interface_fixture" },
    },
  ]);
  assert.equal(response.status, "unavailable");
  assert.equal(response.unavailable.code, "insufficient_evidence");
  assert.match(response.unavailable.message, new RegExp(FIXTURE_NOT_ESTIMABLE));
  assert.equal(hasEffectNumber(response), false);
});
