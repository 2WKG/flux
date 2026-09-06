import assert from "node:assert/strict";
import { build } from "esbuild";
import { mkdir } from "node:fs/promises";
import test from "node:test";
import { fileURLToPath } from "node:url";

const compiled = new URL("../../node_modules/.cache/toy-cascade.mjs", import.meta.url);
await mkdir(new URL(".", compiled), { recursive: true });
await build({ entryPoints: [fileURLToPath(new URL("./toyCascade.ts", import.meta.url))], bundle: true, format: "esm", platform: "node", outfile: fileURLToPath(compiled) });
const { runToyCascade, solveToyDc, TOY_LINES } = await import(`${compiled.href}?t=${Date.now()}`);

test("the toy DC solve balances specified injections and exposes a thermal utilization", () => {
  const solved = solveToyDc(new Set(TOY_LINES.map((line) => line.id)));
  assert.equal(Object.values(solved.injections).reduce((sum, value) => sum + value, 0), 0);
  assert.equal(solved.actions.length, 0);
  assert.ok(solved.lines.every((line) => Number.isFinite(line.flowMw) && Number.isFinite(line.utilizationPct)));
});

test("the seeded outage cascades through an overloaded line and reports island load shedding", () => {
  const stages = runToyCascade();
  assert.equal(stages[1].trippedLineId, "hub-east");
  assert.equal(stages[1].nextTripLineId, "east-south");
  assert.equal(stages[2].trippedLineId, "east-south");
  assert.ok(stages[2].balanceActions.some((action) => action.busId === "east" && action.kind === "shed_load" && action.mw === 70));
  assert.ok(stages[2].balanceActions.some((action) => action.kind === "curtail_generation"));
  assert.equal(stages.at(-1).nextTripLineId, null);
});
