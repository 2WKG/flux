import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { fileURLToPath } from "node:url";

const cssPath = fileURLToPath(new URL("./MinnesotaControlRoom.css", import.meta.url));
const componentPath = fileURLToPath(new URL("./MinnesotaControlRoom.tsx", import.meta.url));
const [css, component] = await Promise.all([
  readFile(cssPath, "utf8"),
  readFile(componentPath, "utf8"),
]);

test("Minnesota controls retain native keyboard semantics with a high-visibility focus state", () => {
  assert.match(component, /import "\.\/MinnesotaControlRoom\.css";/);
  assert.match(component, /<button type="button" onClick=\{reset\}>Reset to baseline<\/button>/);
  assert.match(component, /<button type="button" onClick=\{copyBookmark\}>Copy shareable baseline link<\/button>/);
  assert.match(component, /<button type="button" disabled aria-disabled="true">Inspect feature unavailable<\/button>/);
  assert.match(css, /\.minnesota-control-room :focus-visible \{/);
  assert.match(css, /outline: \.25rem solid var\(--mn-focus\);/);
  assert.doesNotMatch(css, /outline:\s*none/);
});

test("Minnesota control-room styling is scoped, scalable, and honors reduced motion", () => {
  assert.match(css, /^\.minnesota-control-room \{/m);
  assert.match(css, /font: 400 clamp\(1rem,/);
  assert.match(css, /font-size: clamp\(1\.75rem,/);
  assert.match(css, /overflow-wrap: anywhere;/);
  assert.match(css, /button:disabled,[\s\S]*?cursor: not-allowed;/);
  assert.match(css, /@media \(prefers-reduced-motion: reduce\)/);
  assert.match(css, /animation-duration: \.01ms !important;/);
  assert.match(css, /transition-duration: \.01ms !important;/);
  assert.match(css, /@media \(forced-colors: active\)/);
});
