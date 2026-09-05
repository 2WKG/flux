import assert from "node:assert/strict";
import { execFileSync, spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { assertDataClientBoundary } from "../../scripts/assert-data-client-boundary.mjs";

const webRoot = fileURLToPath(new URL("../..", import.meta.url));
const srcDirectory = join(webRoot, "src");
const guardScript = join(webRoot, "scripts", "assert-data-client-boundary.mjs");

function withFixture(files, run) {
  const directory = mkdtempSync(join(tmpdir(), "flux-data-boundary-"));
  try {
    for (const [name, source] of Object.entries(files)) {
      mkdirSync(join(directory, name, ".."), { recursive: true });
      writeFileSync(join(directory, name), source);
    }
    return run(directory);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
}

test("the whole browser source tree contains no local database or analytical fallback", () => {
  const scanned = assertDataClientBoundary(srcDirectory);
  // Sanity: the scan must actually reach beyond src/data (main.tsx lives at the root of src).
  assert.ok(scanned >= 5, `expected to scan the src tree, scanned ${scanned}`);
});

test("boundary guard rejects a local database import and database path", () => {
  withFixture(
    { "bad.ts": 'import Database from "duckdb";\nconst path = "data/duck/grid.duckdb";\n' },
    (directory) => assert.throws(() => assertDataClientBoundary(directory), /DuckDB dependency or identifier/),
  );
});

test("boundary guard scans test files too", () => {
  withFixture(
    { "data/zz-bad.test.mjs": 'import duckdb from "duckdb";\n' },
    (directory) => assert.throws(() => assertDataClientBoundary(directory), /zz-bad\.test\.mjs: DuckDB dependency/),
  );
});

test("boundary guard rejects a DuckDB import at the root of src (main.tsx), via the CLI", () => {
  withFixture(
    {
      "main.tsx": 'import duckdb from "duckdb";\nexport const db = duckdb;\n',
      "data/client.ts": "export const ok = true;\n",
    },
    (directory) => {
      const result = spawnSync(process.execPath, [guardScript, directory], { encoding: "utf8" });
      assert.equal(result.status, 1, result.stdout + result.stderr);
      assert.match(result.stderr, /main\.tsx: DuckDB dependency or identifier/);
    },
  );
});

test("boundary guard CLI defaults to web/src and passes on the clean tree", () => {
  const output = execFileSync(process.execPath, [guardScript], { cwd: webRoot, encoding: "utf8" });
  assert.match(output, /browser boundary: \d+ source files under .*src are HTTP-only/);
});
