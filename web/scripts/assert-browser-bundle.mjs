import { relative, resolve, sep } from "node:path";

const DATABASE_PACKAGES = /(?:^|[/\\])(?:duckdb|sqlite3|better-sqlite3|sql\.js|wa-sqlite|pg|postgres|postgresql|prisma|typeorm|sequelize|knex)(?:[/\\]|$)/i;
const ANALYTICS_DIRECTORIES = /(?:^|[/\\])(?:models?|pipelines|siting|twin|causal|scoring)(?:[/\\]|$)/i;

function normalized(path) {
  return path.replaceAll("\\", "/");
}

/** Throw when a browser bundle reaches database dependencies or server-side analytics. */
export function assertBrowserBundle(metafile, webRoot) {
  const violations = Object.keys(metafile.inputs).flatMap((input) => {
    const path = normalized(input);
    const resolved = normalized(resolve(webRoot, input));
    const outsideWeb = relative(webRoot, resolve(webRoot, input)).startsWith(`..${sep}`);
    const reasons = [];

    if (DATABASE_PACKAGES.test(path)) reasons.push("database dependency");
    if (outsideWeb && ANALYTICS_DIRECTORIES.test(resolved)) reasons.push("analytical or scoring code");

    return reasons.map((reason) => `${path}: ${reason}`);
  });

  if (violations.length > 0) {
    throw new Error(`Browser bundle boundary violated:\n${violations.join("\n")}`);
  }
}
