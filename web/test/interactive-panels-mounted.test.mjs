/**
 * An unmounted panel is invisible to the whole suite: it renders green in its
 * own test file while `npm run build` tree-shakes it out of `dist/`, so no user
 * can reach it. This file closes that hole for the interactive inspectors, in
 * the style of `test/viewport-shell.test.mjs`'s
 * "the built bundle actually ships the shell, the dock, and the derived label".
 *
 * Remove `<InteractivePanels />` from `src/pages/MainPage.tsx` and every
 * assertion below fails.
 */
import assert from "node:assert/strict";
import test from "node:test";

import { readBuiltScripts } from "./built-assets.mjs";

const built = await readBuiltScripts();

test("the built bundle ships the balance and redundancy inspectors", () => {
  for (const marker of [
    "Interactive twin inspectors",
    "Supply and draw",
    "Redundancy inspector",
    "Headroom (server-supplied)",
    "carries no provenance record",
    "Reachability screening",
  ]) {
    assert.ok(built.includes(marker), `built bundle is missing ${marker}`);
  }
});

test("the shipped interactive boundary keeps the /interactive prefix and the POST siting root", () => {
  // The roots are composed from this one constant, so the prefix is what ships.
  assert.ok(built.includes('INTERACTIVE_ROOT_PREFIX = "/interactive"'), "the /interactive prefix is not in the shipped bundle");
  for (const suffix of ["/scenario/edit", "/cascade", "/balance", "/redundancy", "/siting/search"]) {
    assert.ok(built.includes("${INTERACTIVE_ROOT_PREFIX}" + suffix), `the ${suffix} root is not in the shipped bundle`);
  }
  // The balance boundary must not revive its old invented camelCase response.
  // `generationMw` is now legitimately present in the frozen teaching-cascade
  // trace, so this check remains scoped to the balance-only invented fields.
  for (const invented of ["servedLoadMw", "slackMw", "residualMw"]) {
    assert.ok(!built.includes(invented), `the invented balance field ${invented} is back in the bundle`);
  }
  assert.ok(built.includes("Synthetic five-bus teaching network"), "the frozen teaching trace is missing from the bundle");
});
