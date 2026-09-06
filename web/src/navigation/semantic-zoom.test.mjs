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

function level(scale) {
  const resolution = detailLevelForScale(scale);
  assert.equal(resolution.kind, "detail_level", JSON.stringify(resolution));
  return resolution.level;
}

test("detail level resolves for every scale on the ladder", () => {
  assert.deepEqual(level("statewide"), {
    scale: "statewide",
    labelDetail: "major_only",
    showFacilityMarkers: false,
    labelDensityCap: 12,
  });
  assert.deepEqual(level("region"), {
    scale: "region",
    labelDetail: "all",
    showFacilityMarkers: false,
    labelDensityCap: 40,
  });
  assert.deepEqual(level("facility"), {
    scale: "facility",
    labelDetail: "all",
    showFacilityMarkers: true,
    labelDensityCap: 200,
  });
});

test("an unknown scale is refused by name -- never answered with a fabricated level", () => {
  // The real callers are a URL hash, a stored preference, and another module's
  // message; none is type-checked at runtime. Substituting the statewide level
  // for any of them would invent a detail budget for a scale that does not exist.
  for (const notAScale of ["", "STATEWIDE", "county", "nation", "statewide ", null, undefined, 0, {}, ["region"]]) {
    const resolution = detailLevelForScale(notAScale);
    assert.equal(resolution.kind, "rejected", `${JSON.stringify(notAScale)} must be refused, not resolved`);
    assert.equal(resolution.reason, "unknown_scale", JSON.stringify(notAScale));
    assert.ok(resolution.detail.length > 0, "a refusal must carry operator-facing detail");
    assert.equal(resolution.level, undefined, "a refusal must carry no level at all");
  }
});

test("no refusal is silently swapped for the statewide level", () => {
  const refused = detailLevelForScale("nation");
  assert.notDeepEqual(refused, { kind: "detail_level", level: RESET_DETAIL_LEVEL });
  assert.notDeepEqual(refused.level, RESET_DETAIL_LEVEL);
});

test("detail strictly increases in facility-marker visibility as scale narrows, never decreases", () => {
  const seenMarkers = DETAIL_LEVEL_LADDER.map((entry) => entry.showFacilityMarkers);
  // Once markers turn on for a narrower scale they must not turn back off at a narrower one still.
  let sawMarkers = false;
  for (const shown of seenMarkers) {
    if (sawMarkers) assert.ok(shown, "facility markers must not disappear at a narrower scale");
    if (shown) sawMarkers = true;
  }
});

test("the reset detail level matches the statewide scale exactly", () => {
  assert.deepEqual(RESET_DETAIL_LEVEL, level("statewide"));
});

test("calling detailLevelForScale twice with the same scale is deterministic", () => {
  assert.deepEqual(detailLevelForScale("region"), detailLevelForScale("region"));
});
