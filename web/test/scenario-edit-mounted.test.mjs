/**
 * The scenario edit panel had no importer, so `npm run build` tree-shook it out
 * of `dist/` and no user could reach it -- invisible to the suite, because an
 * unmounted panel still renders green in its own test file. This closes that
 * hole, in the style of `test/viewport-shell.test.mjs`'s built-bundle assertion.
 * Remove `<ScenarioEditContainer />` from `src/pages/MainPage.tsx` and it fails.
 */
import assert from "node:assert/strict";
import test from "node:test";

import { readBuiltScripts } from "./built-assets.mjs";

const built = await readBuiltScripts();

test("the built bundle ships the scenario edit composer", () => {
  for (const marker of [
    "Scenario edit composer",
    "Hypothetical scenario edits",
    "Ordered scenario operations",
    "Submit to the scenario edit service",
    "No stable scenario edit endpoint is mounted",
  ]) {
    assert.ok(built.includes(marker), `built bundle is missing ${marker}`);
  }
});

test("the shipped composer submits through the interactive boundary, not its own fetch", () => {
  assert.ok(built.includes("${INTERACTIVE_ROOT_PREFIX}/scenario/edit"), "the scenario edit root is not in the bundle");
  // The container must not open a transport of its own beside the shared client.
  assert.ok(!/ScenarioEditContainer[\s\S]{0,4000}?\bfetch\(/.test(built), "the container issues a bare fetch");
});
