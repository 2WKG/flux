import assert from "node:assert/strict";
import { build } from "esbuild";
import { mkdir } from "node:fs/promises";
import test from "node:test";
import { fileURLToPath } from "node:url";

const compiled = new URL("../../../node_modules/.cache/causal-toy.mjs", import.meta.url);
await mkdir(new URL(".", compiled), { recursive: true });
await build({
  entryPoints: [fileURLToPath(new URL("./causalToy.ts", import.meta.url))],
  bundle: true,
  format: "esm",
  platform: "node",
  outfile: fileURLToPath(compiled),
});
const { CAUSAL_MODEL, assertModel, contrast, claimContrasts } = await import(`${compiled.href}?t=${Date.now()}`);

const model = assertModel(CAUSAL_MODEL);

test("conditioning and do() disagree for line_failures, which has parents", () => {
  const many = contrast(model, "line_failures", "many");
  assert.equal(many.confounded, true);
  assert.notEqual(many.observed, many.intervened);
  assert.ok(Math.abs(many.gap) > 1e-9, "the confounder gap must be a real numeric difference");
});

test("conditioning and do() agree for weather_severity, which is a root", () => {
  const severe = contrast(model, "weather_severity", "severe");
  assert.equal(severe.confounded, false);
  assert.equal(severe.observed, severe.intervened);
  assert.equal(severe.gap, 0);
});

test("claimContrasts pin the same split: roots agree, the confounded treatment does not", () => {
  const byId = Object.fromEntries(claimContrasts(model).map((claim) => [claim.id, claim]));
  assert.equal(byId.weather_severity.agrees, true);
  assert.equal(byId.investment.agrees, true);
  assert.equal(byId.line_failures.agrees, false);
  assert.notEqual(byId.line_failures.observedDifference, byId.line_failures.interventionalDifference);
});
