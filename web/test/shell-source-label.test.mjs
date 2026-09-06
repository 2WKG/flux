// The shell's whole claim is that it labels the data it is given. These tests render
// the real mounted app (and the shell directly) with react-dom/server and assert the
// rendered markup, so mislabelling the checked-in synthetic fixture, or collapsing the
// status vocabulary to one string, fails instead of passing silently.
import assert from "node:assert/strict";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

import { build } from "esbuild";

const webRoot = path.dirname(new URL("../package.json", import.meta.url).pathname);
const fixtureUrl = new URL("../../data/demo/bundle.json", import.meta.url);

/** Bundle a TSX entry for node and import it, so a server render exercises the real source. */
async function serverRender(source) {
  const dir = await mkdtemp(path.join(os.tmpdir(), "flux-shell-ssr-"));
  const entry = path.join(dir, "entry.tsx");
  const outfile = path.join(dir, "entry.mjs");
  await (await import("node:fs/promises")).writeFile(entry, source, "utf8");
  await build({
    entryPoints: [entry],
    outfile,
    bundle: true,
    format: "esm",
    platform: "node",
    target: "node20",
    absWorkingDir: webRoot,
    // The entry lives in a scratch directory, so point resolution at web/node_modules.
    nodePaths: [path.join(webRoot, "node_modules")],
    tsconfig: path.join(webRoot, "tsconfig.json"),
    loader: { ".css": "empty" },
    // react-dom/server is CJS and dynamically requires node builtins; give the ESM
    // output a real `require` so those resolve instead of throwing.
    banner: { js: 'import { createRequire as __createRequire } from "node:module"; const require = __createRequire(import.meta.url);' },
    logLevel: "silent",
  });
  const module = await import(pathToFileURL(outfile).href);
  return { html: module.html, cleanup: () => rm(dir, { recursive: true, force: true }) };
}

const APP_ENTRY = `
import { renderToStaticMarkup } from "react-dom/server";
import { App } from ${JSON.stringify(path.join(webRoot, "src/main.tsx"))};
export const html = renderToStaticMarkup(<App />);
`;

test("the mounted app labels the checked-in fixture Synthetic and never claims source support", async () => {
  const { html, cleanup } = await serverRender(APP_ENTRY);
  try {
    const fixture = JSON.parse(await readFile(fixtureUrl, "utf8"));

    assert.match(html, /<main[^>]*data-source-status="synthetic"/, "the shell must carry the synthetic status");
    assert.ok(html.includes("Synthetic"), "the rendered source pill must read Synthetic");
    // The fixture is a five-bus synthetic input; whatever synthetic artifact it names
    // must be the one the disclosure shows, so a relabel cannot go unnoticed.
    assert.ok(html.includes(fixture.execution.provenance.artifactId), "the shown artifact id must come from the fixture");
    assert.ok(html.includes(fixture.fixtureHash), "the shown hash must come from the fixture");

    for (const forbidden of ["Source-supported", "Source supported", "Source-screened", "Source screened", "Hypothetical"]) {
      assert.ok(!html.includes(forbidden), `synthetic fixture must never render "${forbidden}"`);
    }
    for (const forbidden of ["source_supported", "source_screened", "hypothetical", "unavailable", "request_failed"]) {
      assert.ok(!html.includes(`data-source-status="${forbidden}"`), `must not carry status ${forbidden}`);
    }
  } finally {
    await cleanup();
  }
});

const SHELL_ENTRY = (props) => `
import { renderToStaticMarkup } from "react-dom/server";
import { AppShell } from ${JSON.stringify(path.join(webRoot, "src/shell/AppShell.tsx"))};
export const html = renderToStaticMarkup(<AppShell {...${props}} />);
`;

test("each of the six IA statuses renders its own distinct label copy", async () => {
  const cases = {
    source_supported: "Source-supported",
    source_screened: "Source-screened",
    hypothetical: "Hypothetical",
    synthetic: "Synthetic",
    unavailable: "Unavailable",
    request_failed: "Request failed",
  };
  const seen = new Map();
  for (const [status, copy] of Object.entries(cases)) {
    const props = JSON.stringify({
      source: { status, label: `label for ${status}`, detail: `detail for ${status}` },
      viewport: "viewport",
    });
    const { html, cleanup } = await serverRender(SHELL_ENTRY(props));
    try {
      assert.ok(html.includes(copy), `status ${status} must render "${copy}"`);
      assert.ok(html.includes(`detail for ${status}`), `status ${status} must render its detail`);
      // A short-circuited copy table would render one string for every status.
      assert.equal(seen.has(copy), false, `"${copy}" was already rendered for ${seen.get(copy)}`);
      seen.set(copy, status);
    } finally {
      await cleanup();
    }
  }
  assert.equal(seen.size, 6);
});

test("unavailable and request_failed refuse to render without their required accompanying copy", async () => {
  for (const status of ["unavailable", "request_failed"]) {
    const props = JSON.stringify({ source: { status, label: `label for ${status}` }, viewport: "viewport" });
    await assert.rejects(
      async () => {
        const { cleanup } = await serverRender(SHELL_ENTRY(props));
        await cleanup();
      },
      (error) => /requires a detail/.test(String(error?.message ?? error)),
      `${status} without detail must not render a bare pill`,
    );
  }
});

test("the stylesheet carries no rules for chrome the shell replaced", async () => {
  const styles = await readFile(new URL("../src/styles.css", import.meta.url), "utf8");
  for (const selector of ["nav {", ".brand", ".live", ".workspace", "header {"]) {
    assert.ok(!styles.includes(selector), `styles.css still carries an orphaned "${selector}" rule`);
  }
  const shellStyles = await readFile(new URL("../src/shell/app-shell.css", import.meta.url), "utf8");
  assert.ok(!shellStyles.includes(".flux-shell__empty"), "app-shell.css still carries the unused .flux-shell__empty rule");
});
