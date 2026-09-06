// The PR body claims an isolated shell harness. That claim is only reproducible if the
// harness actually compiles, and it is only safe if it never rides along in the demo
// bundle. Both halves are asserted here against real esbuild builds.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

const webRoot = path.dirname(new URL("../package.json", import.meta.url).pathname);

function run(args, env) {
  return new Promise((resolve, reject) => {
    const child = spawn("node", args, { cwd: webRoot, env: { ...process.env, ...env } });
    let output = "";
    child.stdout.on("data", (chunk) => { output += chunk; });
    child.stderr.on("data", (chunk) => { output += chunk; });
    child.on("error", reject);
    child.on("close", (code) => (code === 0 ? resolve(output) : reject(new Error(output))));
  });
}

async function bundle(entry) {
  const dist = await mkdtemp(path.join(os.tmpdir(), "flux-shell-build-"));
  await run(["scripts/build.mjs"], { FLUX_WEB_ENTRY: entry, FLUX_WEB_DIST: dist });
  const js = await readFile(path.join(dist, "assets", "app.js"), "utf8");
  await rm(dist, { recursive: true, force: true });
  return js;
}

test("the isolated shell harness compiles as its own entry", async () => {
  const harness = await bundle("src/shell/ShellHarness.tsx");
  assert.match(harness, /Isolated shell harness/);
  assert.match(harness, /Viewport slot/);
  assert.match(harness, /Synthetic harness/);
  // The harness asserts no geography or product data of its own.
  assert.doesNotMatch(harness, /\bfetch\s*\(/);
});

test("the harness is not shipped in the demo bundle", async () => {
  const demo = await bundle("src/main.tsx");
  assert.doesNotMatch(demo, /Isolated shell harness/, "the demo bundle must not contain the harness entry");
  assert.doesNotMatch(demo, /Viewport slot/);
  assert.match(demo, /Synthetic five-bus fixture/, "the demo bundle is still the source-labelled app");
});
