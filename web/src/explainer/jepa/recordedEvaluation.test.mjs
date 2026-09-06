import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { build } from "esbuild";
import { mkdir, readFile } from "node:fs/promises";
import test from "node:test";
import { fileURLToPath } from "node:url";

const artifactUrl = new URL("./recorded-evaluation.artifact.json", import.meta.url);
const compiled = new URL("../../../node_modules/.cache/jepa-recorded-evaluation.mjs", import.meta.url);
await mkdir(new URL(".", compiled), { recursive: true });
await build({
  entryPoints: [fileURLToPath(new URL("./recordedEvaluation.ts", import.meta.url))],
  bundle: true,
  format: "esm",
  platform: "node",
  outfile: fileURLToPath(compiled),
});
const { ARTIFACT_PROVENANCE, RECORDED_EVALUATION, assertRecordedEvaluation, metric } = await import(`${compiled.href}?t=${Date.now()}`);
const artifactBytes = await readFile(artifactUrl);
const artifact = JSON.parse(artifactBytes);

test("the vendored artifact bytes match their recorded SHA-256", () => {
  assert.equal(createHash("sha256").update(artifactBytes).digest("hex"), ARTIFACT_PROVENANCE.contentSha256);
});

test("metrics come from the artifact and missing values are refused", () => {
  const holdoutMae = metric("holdout_count_mae");
  assert.equal(holdoutMae, artifact.metrics.holdout_count_mae);
  assert.ok(Number.isFinite(holdoutMae));
  assert.throws(() => metric("missing_metric"), /must not invent one/);
});

test("the render gate rejects an incomplete recorded evaluation", () => {
  assert.equal(assertRecordedEvaluation(RECORDED_EVALUATION), RECORDED_EVALUATION);
  assert.throws(() => assertRecordedEvaluation({ ...RECORDED_EVALUATION, metrics: {} }), /missing metric/);
});
