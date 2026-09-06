import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";

const webRoot = path.dirname(new URL("../../package.json", import.meta.url).pathname);
const componentPath = path.join(webRoot, "src/minnesota/MinnesotaVisualHierarchy.tsx");
const cssPath = path.join(webRoot, "src/minnesota/MinnesotaVisualHierarchy.css");

test("the frame forwards its caller-owned truth token to the shared vocabulary owner", async () => {
  const component = await readFile(componentPath, "utf8");
  assert.match(component, /readonly truthStatus: AssetStatus/);
  assert.match(component, /data-truth-label=\{truthStatus\}/);
  assert.match(component, /\{STATUS_COPY\[truthStatus\]\}/);
  assert.match(component, /readonly children: ReactNode/);
  assert.doesNotMatch(component, /fetch\(|XMLHttpRequest|navigator\.sendBeacon/);
});

test("the local polish preserves reduced-motion and forced-colors accommodations", async () => {
  const css = await readFile(cssPath, "utf8");
  assert.match(css, /@media \(prefers-reduced-motion: reduce\)/);
  assert.match(css, /transition-duration: \.01ms !important/);
  assert.match(css, /@media \(forced-colors: active\)/);
  assert.match(css, /\.mn-visual-hierarchy/);
});
