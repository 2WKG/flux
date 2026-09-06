import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { build } from "esbuild";

const root = new URL("../", import.meta.url);
const compiled = new URL("../../node_modules/.cache/flux-mn-control-room.mjs", import.meta.url);
await mkdir(new URL(".", compiled), { recursive: true });
await build({
  stdin: {
    contents: `
      import { createElement } from "react";
      import { renderToStaticMarkup } from "react-dom/server";
      import { MinnesotaControlRoom } from "./minnesota/MinnesotaControlRoom";
      export const render = (props) => renderToStaticMarkup(createElement(MinnesotaControlRoom, props));
    `,
    resolveDir: fileURLToPath(root), loader: "tsx", sourcefile: "mn-control-room-test.tsx",
  },
  bundle: true, format: "esm", platform: "node", jsx: "automatic", packages: "external", loader: { ".css": "empty" },
  outfile: fileURLToPath(compiled),
});
const room = await import(compiled.href);

/** Visible text, tags stripped and whitespace collapsed, for one markup fragment. */
function visibleText(markup) {
  return markup
    .replace(/<[^>]*>/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/\s+/g, " ")
    .trim();
}

function aggregateSceneText(markup) {
  const match = /<section aria-label="Aggregate scene">([\s\S]*?)<section aria-label="Unavailable inspection">/.exec(markup);
  assert.ok(match, "the aggregate scene section is not rendered");
  return visibleText(match[1]);
}

/**
 * The complete text the aggregate scene is allowed to show, spelled out.
 *
 * The previous guarantee here was `doesNotMatch(/synthetic five-bus|ACTIVSg2000/i)`
 * -- a two-string denylist, which a named substation, a bus-to-bus line, a
 * fabricated flow and a real coordinate pair all walk straight past. Gate 0 §2
 * is a property ("no geometry, no topology, no facility points, no
 * allocation"), so the assertion is an allowlist: anything this scene renders
 * that is not on this list fails, whatever it is called.
 */
const AGGREGATE_SCENE_ALLOWED_TEXT = [
  "Aggregate mode",
  "The accepted manifest supports provenance and coverage display only.",
  "MISO balancing-authority values are not Minnesota demand and are not allocated to counties or service areas.",
  "Unavailable",
  "No server read contract currently supplies a Minnesota aggregate result, geometry, feature inspection, or model output.",
  "Reset view",
].join(" ");

/**
 * Second, weaker net over the whole page: the shapes a Gate-0 violation takes
 * regardless of wording. These would also catch a violation introduced outside
 * the aggregate scene, where the allowlist above does not reach.
 */
const FORBIDDEN_SHAPES = [
  [/-?\d{1,3}\.\d+\s*,\s*-?\d{1,3}\.\d+/, "a coordinate pair"],
  [/\b\d+(?:\.\d+)?\s*(?:kV|MW|MVA|MWh|GW|GWh|kW|MVAr)\b/i, "an electrical quantity with a unit"],
  [/\b(?:MN[-_ ])?(?:BUS|LINE|FEEDER|XFMR|SUB|SUBSTATION)[-_ ]?\d+\b/i, "a bus, line or substation identifier"],
  [/\b(?:substation|transformer|feeder|transmission line)\b/i, "a named facility class"],
  [/synthetic five-bus|ACTIVSg2000/i, "a synthetic network fixture"],
];

test("the route shell is aggregate-only and names the missing server contract", () => {
  const markup = room.render({ search: "", location: { pathname: "/minnesota", hash: "" } });
  assert.match(markup, /data-scene-mode="aggregate"/);
  assert.match(markup, /Minnesota aggregate baseline/);
  assert.match(markup, /mn:aggregate:manifest:v1/);
  assert.match(markup, /No server read contract currently supplies a Minnesota aggregate result/);
  assert.match(markup, /Compare baseline/);
  assert.match(markup, /Inspect feature unavailable/);
});

test("the aggregate scene renders only the text it is allowed to render", () => {
  const markup = room.render({ search: "", location: { pathname: "/minnesota", hash: "" } });
  assert.equal(
    aggregateSceneText(markup),
    AGGREGATE_SCENE_ALLOWED_TEXT,
    "the aggregate scene renders text that is not on the Gate-0 allowlist",
  );
  const page = visibleText(markup);
  for (const [shape, description] of FORBIDDEN_SHAPES) {
    const found = shape.exec(page);
    assert.equal(found, null, `the Minnesota route renders ${description}: ${found?.[0]}`);
  }
});

test("the shareable link names the server's scene id, the artifact and its digest", () => {
  const markup = room.render({ search: "", location: { pathname: "/minnesota", hash: "" } });
  assert.match(markup, /<code>scene:mn:baseline:v1<\/code>/);
  assert.match(markup, /<code>mn:baseline:v1<\/code>/);
  assert.match(markup, /<code>sha256:f287a1dfbafddff8bd9f0ec989d488ad6743609280b19338eca048c3d5858e05<\/code>/);
  // The run revision a reviewer can copy carries every one of those fields.
  const revision = /data-run-revision="([^"]*)"/.exec(markup)?.[1];
  assert.ok(revision, "no run revision is rendered");
  for (const field of ["mn=v1", "mode=aggregate", "scene=scene%3Amn%3Abaseline%3Av1", "artifact=mn%3Aaggregate%3Amanifest%3Av1", "hash=sha256%3Af287a1df"]) {
    assert.ok(revision.includes(field), `the run revision omits ${field}: ${revision}`);
  }
  // A browser-invented scene id is exactly what this replaces.
  assert.doesNotMatch(markup, /mn:coverage:aggregate/);
});

test("an invalid bookmark remains an explicit failure instead of being silently reset", () => {
  const markup = room.render({ search: "?mn=v2", location: { pathname: "/minnesota", hash: "" } });
  assert.match(markup, /data-request-state="version_mismatch"/);
  assert.match(markup, /bookmark is incomplete or repeats a state field/);
  assert.match(markup, /Reset view/);
});
