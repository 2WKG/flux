import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

const outputDirectory = mkdtempSync(join(tmpdir(), "flux-perf-lod-"));
process.on("exit", () => rmSync(outputDirectory, { recursive: true, force: true }));
execFileSync(
  process.execPath,
  ["./node_modules/typescript/bin/tsc", "src/performance/lod-selection.ts", "--target", "ES2022", "--module", "NodeNext", "--moduleResolution", "NodeNext", "--outDir", outputDirectory],
  { cwd: new URL("../..", import.meta.url), stdio: "inherit" },
);
const { selectLod, DEFAULT_LOD_THRESHOLDS } = await import(pathToFileURL(join(outputDirectory, "lod-selection.js")).href);

test("near, mid, and far distances select lod0, lod1, lod2 respectively", () => {
  assert.equal(selectLod(0, 1).lod, "lod0");
  assert.equal(selectLod(150, 1).lod, "lod0");
  assert.equal(selectLod(150.1, 1).lod, "lod1");
  assert.equal(selectLod(1500, 1).lod, "lod1");
  assert.equal(selectLod(1500.1, 1).lod, "lod2");
  assert.equal(selectLod(1_000_000, 1).lod, "lod2");
});

test("selection is deterministic: identical inputs always select the identical level", () => {
  for (let i = 0; i < 20; i++) {
    assert.equal(selectLod(400, 2).lod, "lod1");
  }
});

test("a larger scale reads as closer: the same raw distance can select a nearer LOD", () => {
  const farAway = selectLod(600, 1);
  const scaledUp = selectLod(600, 10); // effective distance 60 -> lod0
  assert.equal(farAway.lod, "lod1");
  assert.equal(scaledUp.lod, "lod0");
  assert.equal(scaledUp.effectiveDistanceMeters, 60);
});

test("negative distance is clamped to zero rather than rejected", () => {
  const result = selectLod(-50, 1);
  assert.equal(result.kind, "selected");
  assert.equal(result.effectiveDistanceMeters, 0);
  assert.equal(result.lod, "lod0");
});

test("a non-finite distance or a non-positive scale is a named rejection", () => {
  for (const distance of [NaN, Infinity, -Infinity]) {
    const result = selectLod(distance, 1);
    assert.equal(result.kind, "rejected");
    assert.equal(result.reason, "non_finite_distance");
  }
  for (const scale of [0, -1, NaN, Infinity]) {
    const result = selectLod(100, scale);
    assert.equal(result.kind, "rejected");
    assert.equal(result.reason, "non_positive_scale");
  }
});

test("custom thresholds are honoured over the defaults", () => {
  const thresholds = { lod0MaxDistanceMeters: 10, lod1MaxDistanceMeters: 20 };
  assert.equal(selectLod(15, 1, thresholds).lod, "lod1");
  assert.equal(selectLod(15, 1, DEFAULT_LOD_THRESHOLDS).lod, "lod0");
});
