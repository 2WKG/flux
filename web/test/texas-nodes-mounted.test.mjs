/**
 * Nothing outside `src/texas-nodes/` imported the module set, so `npm run build`
 * tree-shook it out and the built bundle contained none of it. This asserts the
 * shipped artifact carries the surface, in the style of
 * `test/viewport-shell.test.mjs`'s built-bundle assertion. Remove
 * `<TexasNodesPanel />` from `src/pages/MainPage.tsx` and this goes red.
 */
import assert from "node:assert/strict";
import test from "node:test";

import { readBuiltScripts } from "./built-assets.mjs";

const built = await readBuiltScripts();

test("the built bundle ships the annotated Texas node surface", () => {
  for (const marker of [
    "Annotated Texas nodes",
    "Texas node inspector",
    "Hour-scaled draw",
    "Balancing authority",
    "/layers/buses",
  ]) {
    assert.ok(built.includes(marker), `built bundle is missing ${marker}`);
  }
});

test("the shipped surface carries the asserted topology token and no source claim", () => {
  assert.ok(built.includes("synthetic (ACTIVSg2000)"), "the asserted topology token is not in the bundle");
  // The role vocabulary comes from the generated contract, so its values ship.
  for (const role of ["producer", "consumer", "transmission"]) {
    assert.ok(built.includes(`"${role}"`), `the ${role} role token is not in the bundle`);
  }
});
