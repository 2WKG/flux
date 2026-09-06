import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { build } from "esbuild";

const demoRoot = new URL("./", import.meta.url);
const compiled = new URL("../../node_modules/.cache/flux-primary-demo-test.mjs", import.meta.url);
await mkdir(new URL(".", compiled), { recursive: true });
await build({
  stdin: {
    contents: `
      import { createElement } from "react";
      import { renderToStaticMarkup } from "react-dom/server";
      import { PrimaryDemo } from "./PrimaryDemo";
      import { resolveSceneEvents } from "./TexasModelStage";
      import { historicalForecastFromPayload, texasModelSceneFromPayload } from "./runtime";
      export { resolveSceneEvents, historicalForecastFromPayload, texasModelSceneFromPayload };
      export const render = (props) => renderToStaticMarkup(createElement(PrimaryDemo, props));
    `,
    resolveDir: fileURLToPath(demoRoot), loader: "tsx", sourcefile: "primary-demo-test-entry.tsx",
  },
  bundle: true, format: "esm", platform: "node", jsx: "automatic", packages: "external",
  loader: { ".css": "empty" }, outfile: fileURLToPath(compiled),
});
const demo = await import(compiled.href);

const controlRoom = {
  regions: [{ id: "texas", label: "Texas", summary: "x", topology: { label: "synthetic (ACTIVSg2000)", mode: "synthetic", availability: "available" }}],
  selectedRegionId: "texas",
  scenarios: [{ id: "uri", label: "Uri", description: "x", availability: "unavailable", weather: [] }],
  suggestedPrompts: [],
};

test("primary runtime defaults to source inventory and keeps legacy fixture out of rendered markup", () => {
  const markup = demo.render({ controlRoom, spatialStage: "source inventory", legacyFixture: "five bus fixture" });
  assert.match(markup, /data-demo-runtime="primary"/);
  assert.match(markup, /source inventory/);
  assert.match(markup, /Show legacy synthetic fixture/);
  assert.doesNotMatch(markup, /five bus fixture/);
  assert.match(markup, /Texas grid model/);
});

test("model event resolution never guesses an ID match", () => {
  const result = demo.resolveSceneEvents({
    availability: "available", topologyLabel: "synthetic (ACTIVSg2000)", synthetic: true, elementIds: ["line:7"],
    cascade: { runId: "run", availability: "available", playbackQualified: true, reasons: [], events: [
      { elementId: "line:7", kind: "line", stage: 1, cause: "forced" },
      { elementId: "line:8", kind: "line", stage: 1, cause: "forced" },
    ] },
  });
  assert.deepEqual(result.resolved.map((event) => event.elementId), ["line:7"]);
  assert.deepEqual(result.notLocated.map((event) => event.elementId), ["line:8"]);
});

test("historical forecast adapter reads nested data.forecast and validates supplied county scope", () => {
  const forecast = demo.historicalForecastFromPayload({
    status: "available", data: {
      status: "experimental", model_version: "numpy-jepa-count-v1", scope: { observed_county_fips: ["48453"] },
      forecast: { county_fips: "48453", county_name: "Travis", context_end_utc: "2024-10-11T12:15:00Z", horizon_minutes: 360, actual_customers_out: [8], predicted_customers_out: [7.751] },
    },
  });
  assert.equal(forecast.availability, "available");
  assert.equal(forecast.countyName, "Travis");
  assert.equal(forecast.horizonMinutes, 360);
  const unavailable = demo.historicalForecastFromPayload({ status: "available", data: { status: "experimental", scope: { observed_county_fips: [] }, forecast: { county_fips: "48453" } } });
  assert.equal(unavailable.availability, "unavailable");
});

test("model adapter keeps only server-resolved canonical IDs and preserves unresolved IDs", () => {
  const scene = demo.texasModelSceneFromPayload({
    status: "partial", reason: "one or more requested synthetic elements could not be resolved",
    data: { topology: { label: "synthetic (ACTIVSg2000)", synthetic: true, solver: "pandapower.rundcpp" }, capabilities: { selected_component_failure: true }, elements: [
      { element_id: "line:973", resolved: true }, { element_id: "impedance/nope", resolved: false },
    ] },
  }, { message: "Request through the configured backend." });
  assert.equal(scene.availability, "partial");
  assert.deepEqual(scene.elementIds, ["line:973"]);
  assert.deepEqual(scene.unresolvedElementIds, ["impedance/nope"]);
  assert.equal(scene.action.availability, "available");
});
