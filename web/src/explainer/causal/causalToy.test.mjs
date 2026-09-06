import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { build } from "esbuild";

const compiled = new URL("../../../node_modules/.cache/causal-toy.mjs", import.meta.url);
await mkdir(new URL(".", compiled), { recursive: true });
await build({
  entryPoints: [fileURLToPath(new URL("./causalToy.ts", import.meta.url))],
  bundle: true,
  format: "esm",
  platform: "node",
  outfile: fileURLToPath(compiled),
});
const { CAUSAL_MODEL, contrast } = await import(`${compiled.href}?t=${Date.now()}`);

test("conditioning is distinct from the intervention test when the selected node has parents", () => {
  const lineFailures = contrast(CAUSAL_MODEL, "line_failures", "many");
  assert.notEqual(lineFailures.observed, lineFailures.intervened);
  assert.equal(lineFailures.confounded, true);

  const weather = contrast(CAUSAL_MODEL, "weather_severity", "severe");
  assert.equal(weather.observed, weather.intervened);
  assert.equal(weather.confounded, false);
});
