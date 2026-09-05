import assert from "node:assert/strict";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { assertDataClientBoundary } from "../../scripts/assert-data-client-boundary.mjs";

const dataDirectory = new URL("./", import.meta.url).pathname;

test("browser data client contains no local database or analytical fallback", () => {
  assert.doesNotThrow(() => assertDataClientBoundary(dataDirectory));
});

test("boundary guard rejects a local database import and database path", () => {
  const directory = mkdtempSync(join(tmpdir(), "flux-data-boundary-"));
  try {
    writeFileSync(join(directory, "bad.ts"), 'import Database from "duckdb";\nconst path = "data/duck/grid.duckdb";\n');
    assert.throws(() => assertDataClientBoundary(directory), /DuckDB dependency or identifier/);
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});
