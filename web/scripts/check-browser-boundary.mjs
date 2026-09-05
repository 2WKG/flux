import { readdir, readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const webRoot = fileURLToPath(new URL("../", import.meta.url));
const thisFile = fileURLToPath(import.meta.url);
const sourceExtensions = new Set([".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"]);
const duckdbDriver = /(?:from\s*|require\s*\(|import\s*\()["'](?:duckdb|duckdb-async|node-duckdb|@duckdb\/duckdb-wasm)["']/;
const databaseFile = /["'`][^"'`\r\n]*\.(?:duckdb|db)(?:[?#][^"'`\r\n]*)?["'`]/i;
const databasePath = /\b(?:duckdb(?:[_-]?path)?|(?:database|db)[_-]?path)\b/i;

async function sourceFiles(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const nested = await Promise.all(entries.map(async (entry) => {
    const file = path.join(directory, entry.name);
    if (entry.isDirectory()) return ["node_modules", "dist"].includes(entry.name) ? [] : sourceFiles(file);
    return sourceExtensions.has(path.extname(entry.name)) ? [file] : [];
  }));
  return nested.flat(Infinity);
}

const violations = [];
for (const file of await sourceFiles(webRoot)) {
  if (file === thisFile) continue;
  const source = await readFile(file, "utf8");
  const checks = [
    [duckdbDriver, "imports a DuckDB driver"],
    [databaseFile, "references a database file"],
    [databasePath, "receives a database path"],
  ];
  for (const [pattern, message] of checks) {
    const match = source.match(pattern);
    if (match) violations.push(`${path.relative(webRoot, file)}:${source.slice(0, match.index).split("\n").length} ${message}`);
  }
}

if (violations.length) {
  console.error("Browser code must use the API and must not access DuckDB directly:\n" + violations.join("\n"));
  process.exitCode = 1;
}
