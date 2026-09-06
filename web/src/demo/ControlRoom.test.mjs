import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { build } from "esbuild";

const demoRoot = new URL("./", import.meta.url);
const compiled = new URL("../../node_modules/.cache/flux-control-room-test.mjs", import.meta.url);
await mkdir(new URL(".", compiled), { recursive: true });
await build({
  stdin: {
    contents: `
      import { createElement } from "react";
      import { renderToStaticMarkup } from "react-dom/server";
      import { ControlRoom, cascadeIsPlayable, topologyIsDisplayable } from "./ControlRoom";
      export { ControlRoom, cascadeIsPlayable, topologyIsDisplayable };
      export const render = (props) => renderToStaticMarkup(createElement(ControlRoom, props));
    `,
    resolveDir: fileURLToPath(demoRoot),
    loader: "tsx",
    sourcefile: "control-room-test-entry.tsx",
  },
  bundle: true,
  format: "esm",
  platform: "node",
  jsx: "automatic",
  packages: "external",
  loader: { ".css": "empty" },
  outfile: fileURLToPath(compiled),
});
const demo = await import(compiled.href);

const texas = {
  id: "texas", label: "Texas", summary: "A supplied synthetic topology status.",
  topology: { label: "synthetic (ACTIVSg2000)", mode: "synthetic", availability: "available", provenance: [{ label: "parent status" }] },
};
const minnesotaAggregate = {
  id: "minnesota", label: "Minnesota", summary: "Regional inventory only.",
  topology: { label: "aggregate regional stress", mode: "aggregate", availability: "available", provenance: [{ label: "accepted aggregate artifact" }] },
};
const scenario = {
  id: "snow", label: "Winter weather context", description: "A parent-provided scenario description.", availability: "available",
  weather: [{ id: "morning", timeLabel: "Morning", condition: "Snow", symbol: "snow", detail: "Parent-supplied weather detail.", availability: "available", provenance: [{ label: "weather artifact" }] }],
  model: { label: "JEPA forecast", availability: "available", provenance: [{ label: "model artifact", detail: "does not name the architecture" }] },
};

test("Minnesota never implies topology without an accepted source-backed model", () => {
  assert.equal(demo.topologyIsDisplayable(minnesotaAggregate), false);
  assert.equal(demo.topologyIsDisplayable({ ...minnesotaAggregate, topology: { ...minnesotaAggregate.topology, mode: "source_backed", accepted: true } }), true);
  assert.equal(demo.topologyIsDisplayable({ ...minnesotaAggregate, topology: { ...minnesotaAggregate.topology, mode: "synthetic", accepted: true } }), false);
});

test("cascade playback requires an available supplied event", () => {
  assert.equal(demo.cascadeIsPlayable({ availability: "available", events: [] }), false);
  assert.equal(demo.cascadeIsPlayable({ availability: "unavailable", events: [{ id: "1", stageLabel: "one", summary: "x", availability: "available" }] }), false);
  assert.equal(demo.cascadeIsPlayable({ availability: "available", events: [{ id: "1", stageLabel: "one", summary: "x", availability: "unavailable" }] }), false);
  assert.equal(demo.cascadeIsPlayable({ availability: "available", events: [{ id: "1", stageLabel: "one", summary: "x", availability: "available" }] }), true);
});

test("the rendered module preserves parent status and withholds an unproven JEPA label", () => {
  const markup = demo.render({
    regions: [texas, minnesotaAggregate], selectedRegionId: "texas", scenarios: [scenario], selectedScenarioId: "snow",
    cascade: { availability: "available", events: [], unavailableMessage: "No event artifact exists." },
    suggestedPrompts: [{ id: "ask", prompt: "What changed?", availability: "unavailable" }],
  });
  assert.match(markup, /data-demo-module="control-room"/);
  assert.match(markup, /synthetic \(ACTIVSg2000\)/);
  assert.match(markup, /data-cascade-playable="false"/);
  assert.match(markup, /Cascade playback unavailable\./);
  assert.doesNotMatch(markup, /JEPA/);
  assert.match(markup, /Prediction model/);
});
