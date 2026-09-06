import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { readdir, readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import test from "node:test";

const guard = fileURLToPath(new URL("../scripts/check-browser-boundary.mjs", import.meta.url));
const fixtures = new URL("./fixtures/browser-boundary/", import.meta.url);
const webRoot = new URL("../", import.meta.url);

function runGuard(directory) {
  const result = spawnSync(process.execPath, [guard, fileURLToPath(directory)], { encoding: "utf8" });
  const reported = result.stderr
    .split("\n")
    .filter((line) => /^\S+:\d+ /.test(line))
    .map((line) => {
      const [, file, lineNumber, message] = line.match(/^(\S+):(\d+) (.*)$/);
      return { file, line: Number(lineNumber), message };
    });
  return { ...result, reported };
}

// One fixture per detection path, so removing or loosening any rule turns exactly
// that row red. The clean fixtures pin the false-positive class the review found.
const expectedViolations = [
  { file: "async-import.ts", line: 1, message: "imports a DuckDB driver" },
  { file: "database-file.ts", line: 1, message: "references a database file" },
  { file: "database-path.ts", line: 1, message: "receives a database path" },
  { file: "default-import.ts", line: 1, message: "imports a DuckDB driver" },
  { file: "dynamic-import.mjs", line: 1, message: "imports a DuckDB driver" },
  { file: "node-api-import.ts", line: 1, message: "imports a DuckDB driver" },
  { file: "reexport-sqlite.ts", line: 1, message: "imports a DuckDB driver" },
  { file: "require-driver.cjs", line: 1, message: "imports a DuckDB driver" },
  { file: "side-effect-import.ts", line: 2, message: "imports a DuckDB driver" },
  { file: "wasm-import.ts", line: 1, message: "imports a DuckDB driver" },
];

test("every violation fixture is reported once, by the rule that owns it", async () => {
  const files = (await readdir(new URL("violations/", fixtures))).sort();
  assert.deepEqual(files, expectedViolations.map((item) => item.file), "fixture set drifted from the expectation table");

  const result = runGuard(new URL("violations/", fixtures));
  assert.equal(result.status, 1, result.stderr);
  assert.match(result.stderr, /Browser code must use the API and must not access DuckDB directly/);
  assert.deepEqual(result.reported, expectedViolations);
});

test("comments, identifiers, and API calls that mention databases are not violations", async () => {
  const files = await readdir(new URL("clean/", fixtures));
  assert.ok(files.length >= 3, "clean fixtures missing");
  const result = runGuard(new URL("clean/", fixtures));
  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.stderr, "");
});

test("the shipped browser source passes the guard", () => {
  const result = runGuard(new URL("src/", webRoot));
  assert.equal(result.status, 0, result.stderr);
});

test("npm run build cannot skip the guard", async () => {
  const pkg = JSON.parse(await readFile(new URL("package.json", webRoot), "utf8"));
  assert.match(pkg.scripts.lint, /check-browser-boundary\.mjs/);
  assert.match(pkg.scripts.build, /^npm run lint && /, "build must start with the lint guard");
});
