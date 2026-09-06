import assert from "node:assert/strict";
import { build } from "esbuild";
import { mkdir } from "node:fs/promises";
import test from "node:test";
import { fileURLToPath } from "node:url";

const compiled = new URL("../../../node_modules/.cache/jepa-embedding-schematic.mjs", import.meta.url);
await mkdir(new URL(".", compiled), { recursive: true });
await build({
  entryPoints: [fileURLToPath(new URL("./embeddingSchematic.ts", import.meta.url))],
  bundle: true,
  format: "esm",
  platform: "node",
  outfile: fileURLToPath(compiled),
});
const { runSchematicTraining, SCHEMATIC_WINDOWS, SCHEMATIC_HYPERPARAMETERS, SCHEMATIC_DISCLAIMER } = await import(
  `${compiled.href}?t=${Date.now()}`
);

test("the schematic is deterministic, so the animation is a replay and not a random process", () => {
  const first = runSchematicTraining();
  const second = runSchematicTraining();
  assert.deepEqual(first, second);
  assert.equal(first.length, SCHEMATIC_HYPERPARAMETERS.epochs + 1);
  assert.equal(first[0].epoch, 0);
});

test("the predictor closes the embedding gap it starts with", () => {
  const frames = runSchematicTraining();
  const start = frames[0].embeddingLoss;
  const end = frames.at(-1).embeddingLoss;
  assert.ok(start > 0.1, `untrained schematic must show a visible gap, saw ${start}`);
  assert.ok(end < start / 50, `trained schematic must converge, saw ${start} then ${end}`);
  assert.ok(frames.every((frame) => Number.isFinite(frame.embeddingLoss) && frame.embeddingLoss >= 0));
});

test("the target encoder is an EMA that starts at the context embedding and never overshoots", () => {
  const frames = runSchematicTraining();
  for (const [index, entry] of frames[0].predictions.entries()) {
    const window = SCHEMATIC_WINDOWS[index];
    // One EMA step has already been applied when frame 0 is emitted, so the
    // target sits strictly between the context embedding and the true future.
    const travelled = Math.hypot(entry.emaTarget.x - window.context.x, entry.emaTarget.y - window.context.y);
    const total = Math.hypot(window.future.x - window.context.x, window.future.y - window.context.y);
    assert.ok(travelled > 0, "the EMA target must have moved off the context embedding");
    assert.ok(travelled < total, "the EMA target must not reach or pass the true future in one step");
  }
  const last = frames.at(-1).predictions;
  for (const [index, entry] of last.entries()) {
    const window = SCHEMATIC_WINDOWS[index];
    assert.ok(
      Math.hypot(entry.emaTarget.x - window.future.x, entry.emaTarget.y - window.future.y) < 1e-3,
      "the EMA target must converge onto the true future embedding",
    );
  }
});

test("every frame carries a caption and the schematic is labelled as an illustration", () => {
  const frames = runSchematicTraining();
  assert.ok(frames.every((frame) => typeof frame.caption === "string" && frame.caption.length > 0));
  assert.match(SCHEMATIC_DISCLAIMER, /not model output/i);
  assert.match(SCHEMATIC_DISCLAIMER, /schematic/i);
});

test("a nonsensical epoch count is refused rather than silently coerced", () => {
  assert.throws(() => runSchematicTraining(0), /positive integer/);
  assert.throws(() => runSchematicTraining(2.5), /positive integer/);
});
