import { readdir, readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { databasePackageSpecifier } from "./database-packages.mjs";

const webRoot = fileURLToPath(new URL("../", import.meta.url));
// Only browser-shipped code is in scope. Node-side build tooling (scripts/) and the
// local server (server.mjs) legitimately name database packages and paths.
// An explicit directory argument lets the test suite run the guard against fixtures.
const browserRoot = process.argv[2] ? path.resolve(process.argv[2]) : path.join(webRoot, "src");
const sourceExtensions = new Set([".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx"]);

// Import forms: `import x from "pkg"`, `import "pkg"`, `import("pkg")`, `require("pkg")`, `export ... from "pkg"`.
const duckdbDriver = new RegExp(
  `(?:\\bfrom\\s*|\\brequire\\s*\\(\\s*|\\bimport\\s*\\(\\s*|\\bimport\\s+)["'\`]${databasePackageSpecifier()}["'\`]`,
);
const databaseFile = /["'`][^"'`\r\n]*\.(?:duckdb|db)(?:[?#][^"'`\r\n]*)?["'`]/i;
// Anchored to path-shaped identifiers; the bare word `duckdb` alone is not a violation
// (comments, error strings, and identifiers such as `duckdbLike` are legitimate).
const databasePath = /\b(?:duckdb|database|db)[_-]?path\b/i;

/**
 * Remove // and /* *\/ comments while keeping string contents and newlines, so rules
 * neither fire on prose nor lose their line numbers. Quote tracking for ' and " resets
 * at end of line; if a quote is mis-tracked (JSX apostrophes, regex literals), the only
 * effect is that a comment on that line is left in place, never that code is dropped.
 */
export function stripComments(source) {
  let out = "";
  let quote = null;
  for (let i = 0; i < source.length; ) {
    const ch = source[i];
    const next = source[i + 1];
    if (quote) {
      if (ch === "\\") { out += ch + (next ?? ""); i += 2; continue; }
      if (ch === quote || (ch === "\n" && quote !== "`")) quote = null;
      out += ch; i += 1; continue;
    }
    if (ch === '"' || ch === "'" || ch === "`") { quote = ch; out += ch; i += 1; continue; }
    if (ch === "/" && next === "/") {
      while (i < source.length && source[i] !== "\n") i += 1;
      continue;
    }
    if (ch === "/" && next === "*") {
      const end = source.indexOf("*/", i + 2);
      const comment = source.slice(i, end === -1 ? source.length : end + 2);
      out += comment.replace(/[^\n]/g, "");
      i += comment.length;
      continue;
    }
    out += ch; i += 1;
  }
  return out;
}

async function sourceFiles(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const nested = await Promise.all(entries.map(async (entry) => {
    const file = path.join(directory, entry.name);
    if (entry.isDirectory()) return ["node_modules", "dist"].includes(entry.name) ? [] : sourceFiles(file);
    return sourceExtensions.has(path.extname(entry.name)) ? [file] : [];
  }));
  return nested.flat(Infinity);
}

const checks = [
  [duckdbDriver, "imports a DuckDB driver"],
  [databaseFile, "references a database file"],
  [databasePath, "receives a database path"],
];

const violations = [];
for (const file of await sourceFiles(browserRoot)) {
  const source = stripComments(await readFile(file, "utf8"));
  for (const [pattern, message] of checks) {
    const match = source.match(pattern);
    if (match) violations.push(`${path.relative(browserRoot, file)}:${source.slice(0, match.index).split("\n").length} ${message}`);
  }
}

if (violations.length) {
  console.error("Browser code must use the API and must not access DuckDB directly:\n" + violations.join("\n"));
  process.exitCode = 1;
}
