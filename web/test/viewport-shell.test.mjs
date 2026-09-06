import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const sourceUrl = new URL("../src/main.tsx", import.meta.url);
const stylesUrl = new URL("../src/styles.css", import.meta.url);
const bundleUrl = new URL("../dist/assets/app.js", import.meta.url);

async function shellFiles() {
  return Promise.all([readFile(sourceUrl, "utf8"), readFile(stylesUrl, "utf8")]);
}

/** Read one CSS rule body by exact selector, so an assertion cannot pass on a
 *  coincidental match somewhere else in the sheet. */
function ruleBody(styles, selector) {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = styles.match(new RegExp(`(?:^|\\n)\\s*${escaped}\\s*\\{([^}]*)\\}`));
  return match === null ? null : match[1];
}

test("the scene keeps the largest column and the inspector has a bounded one", async () => {
  const [source, styles] = await shellFiles();

  assert.match(source, /className="workspace viewport-shell"/);
  assert.match(source, /className="map scene-viewport"/);
  assert.match(source, /className="inspector"/);
  const workspace = ruleBody(styles, ".workspace");
  assert.ok(workspace, ".workspace rule is missing");
  // The scene column is free to grow; the inspector is capped, so the viewport
  // stays primary instead of the panels squeezing it.
  assert.match(workspace, /grid-template-columns:\s*minmax\(0, 1fr\) minmax\(280px, 360px\)/);
  assert.match(ruleBody(styles, ".scene-viewport"), /min-height:\s*clamp\(500px, 64vh, 700px\)/);
});

test("each surrounding panel has a deliberate compact state at demo widths", async () => {
  const [, styles] = await shellFiles();

  // Laptop and narrow breakpoints must both restate the layout, not just exist.
  for (const width of ["1180px", "980px"]) {
    const query = styles.match(new RegExp(`@media \\(max-width: ${width}\\)\\s*\\{([\\s\\S]*?)\\n\\}`));
    assert.ok(query, `no @media (max-width: ${width}) block`);
    assert.match(query[1], /\.(workspace|inspector|scene-viewport|timeline|card)\b/);
  }
});

test("the chat dock is collapsed by default and expands to an explicit unavailable state", async () => {
  const [source, styles] = await shellFiles();

  // Pin the dock's own state, not any useState(false) in the file: `detail`
  // already used that call long before this dock existed.
  assert.match(source, /const \[chatOpen, setChatOpen\] = useState\(false\)/);
  assert.match(source, /aria-expanded=\{chatOpen\}/);
  assert.match(source, /aria-controls="chat-dock-body"/);
  assert.match(source, /Unavailable in static preview/);
  assert.match(source, /no Copilot endpoint, model result, or Minnesota artifact/);
  assert.ok(ruleBody(styles, ".chat-dock.collapsed"), ".chat-dock.collapsed rule is missing");
  assert.ok(ruleBody(styles, ".chat-dock.expanded"), ".chat-dock.expanded rule is missing");
});

test("the chat dock never floats over the inspector", async () => {
  const [, styles] = await shellFiles();

  // Regression guard: as `position: fixed; right; bottom`, the dock parked over
  // the inspector column and hid the headline unmet-demand figure while the page
  // was scrolled. It belongs in flow, where the JSX already places it.
  const dock = ruleBody(styles, ".chat-dock");
  assert.ok(dock, ".chat-dock rule is missing");
  assert.doesNotMatch(dock, /position:\s*fixed/);
  assert.doesNotMatch(dock, /position:\s*absolute/);
  for (const [selector, body] of Object.entries({
    ".chat-dock": dock,
    ".chat-dock.collapsed": ruleBody(styles, ".chat-dock.collapsed"),
    ".chat-dock.expanded": ruleBody(styles, ".chat-dock.expanded"),
  })) {
    assert.ok(body !== null, `${selector} rule is missing`);
    // Anchored to a declaration start so `margin-top` is not mistaken for `top`.
    assert.doesNotMatch(body, /(?:^|;)\s*(?:top|bottom|left|right)\s*:/, `${selector} still offsets a floating dock`);
  }
  // The overlay is the only element allowed to cover the page.
  const fixedSelectors = [...styles.matchAll(/(?:^|\n)\s*([^{\n]+)\{[^}]*position:\s*fixed/g)].map(
    (match) => match[1].trim(),
  );
  assert.deepEqual(fixedSelectors, [".overlay"]);
});

test("the built bundle actually ships the shell and the dock", async () => {
  // Guards against a shell that only exists in source: `npm run build` runs first
  // in the CI web gate, so dist/ is present here.
  const bundle = await readFile(bundleUrl, "utf8");

  for (const marker of [
    "workspace viewport-shell",
    "map scene-viewport",
    "Unavailable in static preview",
  ]) {
    assert.ok(bundle.includes(marker), `built bundle is missing ${marker}`);
  }
});
