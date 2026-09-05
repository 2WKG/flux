import { readdirSync, readFileSync } from "node:fs";
import { dirname, extname, join } from "node:path";
import { fileURLToPath } from "node:url";

const FORBIDDEN_CLIENT_TOKENS = [
  { description: "DuckDB dependency or identifier", pattern: /\bduckdb\b/i },
  { description: "DuckDB database path", pattern: /(?:\.duckdb\b|data[/\\]duck\b)/i },
  { description: "embedded SQL database dependency", pattern: /\b(?:sqlite|sql\.js|wa-sqlite|alasql)\b/i },
];

function sourceFiles(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) return sourceFiles(path);
    return entry.isFile() && [".ts", ".tsx", ".js", ".mjs"].includes(extname(entry.name)) &&
      !entry.name.includes(".test.") ? [path] : [];
  });
}

/** Throw when browser data-client code gains a local analytical fallback. */
export function assertDataClientBoundary(directory) {
  const violations = sourceFiles(directory).flatMap((path) => {
    const source = readFileSync(path, "utf8");
    return FORBIDDEN_CLIENT_TOKENS
      .filter(({ pattern }) => pattern.test(source))
      .map(({ description }) => `${path}: ${description}`);
  });
  if (violations.length > 0) {
    throw new Error(`web/src/data must stay HTTP-only:\n${violations.join("\n")}`);
  }
}

const thisFile = fileURLToPath(import.meta.url);
if (process.argv[1] && thisFile === process.argv[1]) {
  assertDataClientBoundary(join(dirname(thisFile), "..", "src", "data"));
}
