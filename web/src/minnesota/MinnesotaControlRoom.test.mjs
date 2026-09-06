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
  bundle: true, format: "esm", platform: "node", jsx: "automatic", packages: "external",
  outfile: fileURLToPath(compiled),
});
const room = await import(compiled.href);

test("the route shell is aggregate-only and names the missing server contract", () => {
  const markup = room.render({ search: "", location: { pathname: "/minnesota", hash: "" } });
  assert.match(markup, /data-scene-mode="aggregate"/);
  assert.match(markup, /Minnesota aggregate baseline/);
  assert.match(markup, /mn:aggregate:manifest:v1/);
  assert.match(markup, /No server read contract currently supplies a Minnesota aggregate result/);
  assert.match(markup, /Inspect feature unavailable/);
  assert.doesNotMatch(markup, /synthetic five-bus|ACTIVSg2000/i);
});

test("an invalid bookmark remains an explicit failure instead of being silently reset", () => {
  const markup = room.render({ search: "?mn=v2", location: { pathname: "/minnesota", hash: "" } });
  assert.match(markup, /data-request-state="version_mismatch"/);
  assert.match(markup, /bookmark is incomplete or repeats a state field/);
  assert.match(markup, /Reset view/);
});
