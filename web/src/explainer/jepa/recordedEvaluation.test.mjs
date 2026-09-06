import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdir, readFile } from "node:fs/promises";
import test from "node:test";
import { fileURLToPath } from "node:url";

import { build } from "esbuild";

const compiled = new URL("../../../node_modules/.cache/jepa-recorded-evaluation.mjs", import.meta.url);
await mkdir(new URL(".", compiled), { recursive: true });
await build({
  entryPoints: [fileURLToPath(new URL("./recordedEvaluation.ts", import.meta.url))],
  bundle: true,
  format: "esm",
  platform: "node",
  outfile: fileURLToPath(compiled),
});
const { ARTIFACT_PROVENANCE, RECORDED_EVALUATION, assertRecordedEvaluation } = await import(`${compiled.href}?t=${Date.now()}`);

test("the vendored JEPA result is integrity-pinned and refuses an incomplete evaluation", async () => {
  const bytes = await readFile(new URL("./recorded-evaluation.artifact.json", import.meta.url));
  assert.equal(createHash("sha256").update(bytes).digest("hex"), ARTIFACT_PROVENANCE.contentSha256);
  assert.equal(assertRecordedEvaluation(RECORDED_EVALUATION), RECORDED_EVALUATION);
  assert.throws(
    () => assertRecordedEvaluation({ ...RECORDED_EVALUATION, metrics: {} }),
    /missing metric/,
  );
});
