import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

const outputDirectory = mkdtempSync(join(tmpdir(), "flux-nav-zoom-"));
process.on("exit", () => rmSync(outputDirectory, { recursive: true, force: true }));
execFileSync(
  process.execPath,
  [
    "./node_modules/typescript/bin/tsc",
    "src/navigation/scale-ladder.ts",
    "src/navigation/semantic-zoom.ts",
    "--target", "ES2022", "--module", "NodeNext", "--moduleResolution", "NodeNext", "--outDir", outputDirectory,
  ],
  { cwd: new URL("../..", import.meta.url), stdio: "inherit" },
);
const { detailLevelForScale, DETAIL_LEVEL_LADDER, RESET_DETAIL_LEVEL } = await import(
  pathToFileURL(join(outputDirectory, "semantic-zoom.js")).href
);

test("detail level is a pure, total function of scale", () => {
  assert.deepEqual(detailLevelForScale("statewide"), {
    scale: "statewide",
    labelDetail: "major_only",
    showFacilityMarkers: false,
    labelDensityCap: 12,
  });
  assert.deepEqual(detailLevelForScale("region"), {
    scale: "region",
    labelDetail: "all",
    showFacilityMarkers: false,
    labelDensityCap: 40,
  });
  assert.deepEqual(detailLevelForScale("facility"), {
    scale: "facility",
    labelDetail: "all",
    showFacilityMarkers: true,
    labelDensityCap: 200,
  });
});

test("detail strictly increases in facility-marker visibility as scale narrows, never decreases", () => {
  const seenMarkers = DETAIL_LEVEL_LADDER.map((level) => level.showFacilityMarkers);
  // Once markers turn on for a narrower scale they must not turn back off at a narrower one still.
  let sawMarkers = false;
  for (const shown of seenMarkers) {
    if (sawMarkers) assert.ok(shown, "facility markers must not disappear at a narrower scale");
    if (shown) sawMarkers = true;
  }
});

test("the reset detail level matches the statewide scale exactly", () => {
  assert.deepEqual(RESET_DETAIL_LEVEL, detailLevelForScale("statewide"));
});

test("calling detailLevelForScale twice with the same scale is deterministic", () => {
  assert.deepEqual(detailLevelForScale("region"), detailLevelForScale("region"));
});
