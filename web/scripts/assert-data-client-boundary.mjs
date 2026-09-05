import { readdirSync, readFileSync } from "node:fs";
import { dirname, extname, join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";

/**
 * Browser code never opens DuckDB or any other local analytical store
 * (spec 00 §4.1: the frontend reads the HTTP API only). The whole of `web/src`
 * is scanned — test files included, since a test that imports a database
 * driver would still pull it into the browser package.
 *
 * `master` also carries `scripts/check-browser-boundary.mjs` (#101/#109), which
 * matches driver *import* forms across `web/src`. This guard is the stricter,
 * token-level check (any `duckdb`/`sqlite` identifier or `.duckdb` path). When
 * both exist, `npm run lint` should run both rather than fork either.
 */
const FORBIDDEN_CLIENT_TOKENS = [
  { description: "DuckDB dependency or identifier", pattern: /\bduckdb\b/i },
  { description: "DuckDB database path", pattern: /(?:\.duckdb\b|data[/\\]duck\b)/i },
  { description: "embedded SQL database dependency", pattern: /\b(?:sqlite|sql\.js|wa-sqlite|alasql)\b/i },
];
const SOURCE_EXTENSIONS = new Set([".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"]);
const SKIPPED_DIRECTORIES = new Set(["node_modules", "dist"]);
/**
 * Files allowed to spell the forbidden tokens: only the guard's own test, which
 * writes them into a temp fixture to prove the guard fires. Paths are relative
 * to the scanned directory.
 */
const SELF_TEST_FILES = new Set(["data/client-boundary.test.mjs"]);

function sourceFiles(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) return SKIPPED_DIRECTORIES.has(entry.name) ? [] : sourceFiles(path);
    return entry.isFile() && SOURCE_EXTENSIONS.has(extname(entry.name)) ? [path] : [];
  });
}

/** Throw when browser code gains a local analytical fallback. Returns the scanned file count. */
export function assertDataClientBoundary(directory) {
  const files = sourceFiles(directory).filter(
    (path) => !SELF_TEST_FILES.has(relative(directory, path).split(sep).join("/")),
  );
  const violations = files.flatMap((path) => {
    const source = readFileSync(path, "utf8");
    return FORBIDDEN_CLIENT_TOKENS
      .filter(({ pattern }) => pattern.test(source))
      .map(({ description }) => `${path}: ${description}`);
  });
  if (violations.length > 0) {
    throw new Error(`web/src must stay HTTP-only (no local database):\n${violations.join("\n")}`);
  }
  return files.length;
}

const thisFile = fileURLToPath(import.meta.url);
if (process.argv[1] && thisFile === process.argv[1]) {
  const directory = process.argv[2] ?? join(dirname(thisFile), "..", "src");
  try {
    const scanned = assertDataClientBoundary(directory);
    console.log(`browser boundary: ${scanned} source files under ${directory} are HTTP-only`);
  } catch (error) {
    console.error(error instanceof Error ? error.message : String(error));
    process.exitCode = 1;
  }
}
