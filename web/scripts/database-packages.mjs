// Single source of truth for the database packages that must never reach the
// browser. Both boundary guards consume it: check-browser-boundary.mjs scans
// import specifiers in web/src before the build, assert-browser-bundle.mjs
// inspects esbuild's metafile inputs after it.

export const DATABASE_PACKAGE_SCOPES = ["@duckdb"];
export const DATABASE_PACKAGE_NAMES = [
  "duckdb", "duckdb-async", "node-duckdb",
  "sqlite3", "better-sqlite3", "sql.js", "wa-sqlite",
  "pg", "postgres", "postgresql",
  "prisma", "typeorm", "sequelize", "knex",
];

const escape = (text) => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** Matches a bare or sub-path import specifier of a database package, e.g. "duckdb", "@duckdb/node-api", "pg/lib". */
export function databasePackageSpecifier() {
  const scoped = DATABASE_PACKAGE_SCOPES.map((scope) => `${escape(scope)}\\/[^"'\`/]+`);
  const names = DATABASE_PACKAGE_NAMES.map(escape);
  return `(?:${[...scoped, ...names].join("|")})(?:\\/[^"'\`]*)?`;
}

/** Matches a metafile input path whose segments name a database package, e.g. node_modules/@duckdb/duckdb-wasm/x.js. */
export function databasePackagePath() {
  const scoped = DATABASE_PACKAGE_SCOPES.map((scope) => `${escape(scope)}[/\\\\][^/\\\\]+`);
  const names = DATABASE_PACKAGE_NAMES.map(escape);
  return new RegExp(`(?:^|[/\\\\])(?:${[...scoped, ...names].join("|")})(?:[/\\\\]|$)`, "i");
}
