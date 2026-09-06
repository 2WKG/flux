import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdtemp, mkdir, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

import { assertBrowserBundle } from "../scripts/assert-browser-bundle.mjs";

const webRoot = path.dirname(fileURLToPath(new URL("../package.json", import.meta.url)));
const buildScript = path.join(webRoot, "scripts", "build.mjs");

const inputs = (...paths) => ({ inputs: Object.fromEntries(paths.map((item) => [item, {}])) });

test("database packages are rejected by segment, including scoped and suffixed DuckDB packages", () => {
  for (const input of [
    "node_modules/duckdb/lib/duckdb.js",
    "node_modules/@duckdb/duckdb-wasm/dist/duckdb-browser.mjs",
    "node_modules/@duckdb/node-api/lib/index.js",
    "node_modules/duckdb-async/dist/duckdb-async.js",
    "node_modules/pg/lib/index.js",
    "node_modules\\better-sqlite3\\lib\\index.js",
  ]) {
    assert.throws(() => assertBrowserBundle(inputs(input), webRoot), /database dependency/, input);
  }
  for (const input of [
    "node_modules/postgres-array/index.js",
    "node_modules/react/index.js",
    "src/main.tsx",
    // A file merely *named* like a database package, inside an unrelated dependency:
    // deck.gl -> fast-xml-parser -> is-unsafe ships a DOM-free string predicate here.
    "node_modules/is-unsafe/src/contexts/sql.js",
    "src/contexts/sql.js",
  ]) {
    assertBrowserBundle(inputs(input), webRoot);
  }

  // The real package by that name is still rejected.
  assert.throws(() => assertBrowserBundle(inputs("node_modules/sql.js/dist/sql-wasm.js"), webRoot), /database dependency/);
});

test("analytics directories are judged on the web-relative input path, not the absolute one", () => {
  assert.throws(() => assertBrowserBundle(inputs("../model/probe.ts"), webRoot), /analytical or scoring code/);
  assert.throws(() => assertBrowserBundle(inputs("../pipelines/probe.ts"), webRoot), /analytical or scoring code/);
  assertBrowserBundle(inputs("../copilot/x.ts", "../data/demo/bundle.json"), webRoot);
  // A checkout under a parent directory named like an analytics area must not trip the guard.
  assertBrowserBundle(inputs("src/main.tsx", "../data/demo/bundle.json"), "/home/ci/models/flux/web");
});

// Plain try/finally rather than explicit resource management: gate/web runs Node 22.
async function withScratch(run) {
  const dir = await mkdtemp(path.join(os.tmpdir(), "flux-bundle-boundary-"));
  try {
    await run(dir);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

function runBuild(entry, dist, cwd) {
  return spawnSync(process.execPath, [buildScript], {
    cwd,
    encoding: "utf8",
    env: { ...process.env, FLUX_WEB_ENTRY: entry, FLUX_WEB_DIST: dist },
  });
}

test("build.mjs fails on a pipelines/ import even when invoked from a foreign cwd", () => withScratch(async (dir) => {
  // Relative to this cwd the probe is `pipelines/probe.ts`, which without absWorkingDir
  // resolves *inside* web/ and used to slip past the outside-web check.
  await mkdir(path.join(dir, "pipelines"));
  await writeFile(path.join(dir, "pipelines", "probe.ts"), "export const probe = 1;\n");
  await writeFile(path.join(dir, "entry.ts"), 'import { probe } from "./pipelines/probe.ts";\nconsole.log(probe);\n');
  const dist = path.join(dir, "dist");

  const result = runBuild(path.join(dir, "entry.ts"), dist, dir);
  assert.equal(result.status, 1, `expected the boundary to fail the build\n${result.stdout}${result.stderr}`);
  assert.match(result.stderr, /Browser bundle boundary violated/);
  assert.match(result.stderr, /pipelines\/probe\.ts: analytical or scoring code/);
  assert.equal(existsSync(path.join(dist, "assets", "app.js")), false, "a violating bundle must not be left on disk");
}));

test("build.mjs still produces a bundle for the shipped entry point", () => withScratch(async (dir) => {
  const dist = path.join(dir, "dist");
  const result = runBuild(path.join(webRoot, "src", "main.tsx"), dist, dir);
  assert.equal(result.status, 0, result.stderr);
  assert.ok(existsSync(path.join(dist, "assets", "app.js")));
  assert.ok(existsSync(path.join(dist, "index.html")));
}));
