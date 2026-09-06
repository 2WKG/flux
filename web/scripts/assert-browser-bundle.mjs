import { relative, resolve, sep } from "node:path";
import { databasePackagePath } from "./database-packages.mjs";

const DATABASE_PACKAGES = databasePackagePath();
const ANALYTICS_DIRECTORIES = /(?:^|[/\\])(?:models?|pipelines|siting|twin|causal|scoring)(?:[/\\]|$)/i;

function normalized(path) {
  return path.replaceAll("\\", "/");
}

/**
 * Throw when a browser bundle reaches database dependencies or server-side analytics.
 * `metafile.inputs` keys must be relative to `webRoot` (build.mjs sets esbuild's
 * absWorkingDir accordingly); the analytics check runs on that relative path so
 * directory names above the checkout cannot trigger it.
 */
export function assertBrowserBundle(metafile, webRoot) {
  const violations = Object.keys(metafile.inputs).flatMap((input) => {
    const path = normalized(input);
    const outsideWeb = relative(webRoot, resolve(webRoot, input)).startsWith(`..${sep}`);
    const reasons = [];

    if (DATABASE_PACKAGES.test(path)) reasons.push("database dependency");
    if (outsideWeb && ANALYTICS_DIRECTORIES.test(path)) reasons.push("analytical or scoring code");

    return reasons.map((reason) => `${path}: ${reason}`);
  });

  if (violations.length > 0) {
    throw new Error(`Browser bundle boundary violated:\n${violations.join("\n")}`);
  }
}
