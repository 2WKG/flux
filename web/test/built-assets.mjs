import { readdir, readFile } from "node:fs/promises";

/**
 * The built browser bundle is no longer one file: `scripts/build.mjs` splits the
 * page entries into chunks beside `assets/app.js` (2WKG-478). A test that asks
 * "does the shipped bundle contain X" therefore has to read the entry *and* its
 * chunks, or it will pass for the wrong reason once a page moves into a chunk.
 */
const assets = new URL("../dist/assets/", import.meta.url);

/** Every emitted script, entry first, as `assets/`-relative names. */
export async function builtScriptNames() {
  const names = (await readdir(assets)).filter((name) => name.endsWith(".js"));
  return names.sort((left, right) => Number(right === "app.js") - Number(left === "app.js"));
}

/** The whole emitted bundle as one string. */
export async function readBuiltScripts() {
  const names = await builtScriptNames();
  const sources = await Promise.all(names.map((name) => readFile(new URL(name, assets), "utf8")));
  return sources.join("\n");
}
