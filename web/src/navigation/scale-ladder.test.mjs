import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

const outputDirectory = mkdtempSync(join(tmpdir(), "flux-nav-scale-"));
process.on("exit", () => rmSync(outputDirectory, { recursive: true, force: true }));
// Run tsc's entrypoint through this Node binary rather than ./node_modules/.bin/tsc:
// that shim is POSIX-only, so spawning it fails with ENOENT on a Windows checkout.
execFileSync(
  process.execPath,
  ["./node_modules/typescript/bin/tsc", "src/navigation/scale-ladder.ts", "--target", "ES2022", "--module", "NodeNext", "--moduleResolution", "NodeNext", "--outDir", outputDirectory],
  { cwd: new URL("../..", import.meta.url), stdio: "inherit" },
);
const {
  SCALE_LADDER,
  RESET_SCALE,
  isScale,
  scaleIndex,
  parentScale,
  childScale,
  zoomInScale,
  zoomOutScale,
  isNarrowerThan,
} = await import(pathToFileURL(join(outputDirectory, "scale-ladder.js")).href);

test("the ladder is statewide, region, facility, in that order, and RESET_SCALE is statewide", () => {
  assert.deepEqual(SCALE_LADDER, ["statewide", "region", "facility"]);
  assert.equal(RESET_SCALE, "statewide");
});

test("isScale accepts only ladder members", () => {
  assert.ok(isScale("statewide"));
  assert.ok(isScale("region"));
  assert.ok(isScale("facility"));
  assert.ok(!isScale("county"));
  assert.ok(!isScale(""));
  assert.ok(!isScale(null));
  assert.ok(!isScale(42));
});

test("parentScale/childScale walk one step and stop at the ends", () => {
  assert.equal(parentScale("statewide"), null);
  assert.equal(parentScale("region"), "statewide");
  assert.equal(parentScale("facility"), "region");

  assert.equal(childScale("facility"), null);
  assert.equal(childScale("region"), "facility");
  assert.equal(childScale("statewide"), "region");
});

test("zoomInScale/zoomOutScale clamp instead of wrapping", () => {
  assert.equal(zoomInScale("statewide"), "region");
  assert.equal(zoomInScale("region"), "facility");
  assert.equal(zoomInScale("facility"), "facility");

  assert.equal(zoomOutScale("facility"), "region");
  assert.equal(zoomOutScale("region"), "statewide");
  assert.equal(zoomOutScale("statewide"), "statewide");
});

test("isNarrowerThan reflects ladder order, not string order", () => {
  assert.ok(isNarrowerThan("facility", "region"));
  assert.ok(isNarrowerThan("region", "statewide"));
  assert.ok(!isNarrowerThan("statewide", "region"));
  assert.ok(!isNarrowerThan("region", "region"));
  assert.equal(scaleIndex("statewide"), 0);
  assert.equal(scaleIndex("facility"), 2);
});
