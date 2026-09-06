// The wire test. Before this file the adapter rendered correctly and was called
// by nothing: deleting it left the suite green, which is indistinguishable from
// the component not existing.
//
// It proves two different things, so a mount cannot be faked by a comment:
// the module is a real input of the composed page's build graph, and the page's
// server-rendered markup carries the adapter's own machine attribute.
import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

import { build } from "esbuild";

const webRoot = path.dirname(new URL("../../package.json", import.meta.url).pathname);
const mainPagePath = path.join(webRoot, "src/pages/MainPage.tsx");
const adapterInput = "src/interactive/AgentSimulationAdapter.tsx";

async function bundleMainPage() {
  const directory = await mkdtemp(path.join(os.tmpdir(), "flux-452-mount-"));
  const entry = path.join(directory, "entry.tsx");
  const output = path.join(directory, "entry.mjs");
  await writeFile(entry, `
    import { renderToStaticMarkup } from "react-dom/server";
    import { App } from ${JSON.stringify(mainPagePath)};
    export const markup = renderToStaticMarkup(<App />);
  `, "utf8");
  const result = await build({
    entryPoints: [entry],
    outfile: output,
    bundle: true,
    format: "esm",
    platform: "node",
    target: "node20",
    absWorkingDir: webRoot,
    nodePaths: [path.join(webRoot, "node_modules")],
    tsconfig: path.join(webRoot, "tsconfig.json"),
    loader: { ".json": "json" },
    metafile: true,
    banner: { js: 'import { createRequire as __createRequire } from "node:module"; const require = __createRequire(import.meta.url);' },
    logLevel: "silent",
  });
  return { directory, output, metafile: result.metafile };
}

const bundled = await bundleMainPage();

test("the composed page's build graph really contains the adapter module", () => {
  const inputs = Object.keys(bundled.metafile.inputs).map((input) => input.replaceAll("\\", "/"));
  assert.ok(
    inputs.some((input) => input.endsWith(adapterInput)),
    `MainPage does not import ${adapterInput}; the adapter is unreachable code`,
  );
});

test("the composed page renders the adapter's own machine surface", async () => {
  try {
    const { markup } = await import(`${pathToFileURL(bundled.output).href}?t=${Date.now()}`);
    assert.match(markup, /data-agent-simulation-adapter="ask-v1"/);
    for (const capability of ["simulation_action", "provider", "scene_attribution", "reversal"]) {
      assert.match(markup, new RegExp(`data-agent-simulation-capability="${capability}"`));
    }
    // With no stream yet there is no contract evidence, so every capability is
    // the frozen unavailable token -- not a plausible "available".
    assert.doesNotMatch(markup, /data-agent-simulation-availability="available"/);
  } finally {
    await rm(bundled.directory, { recursive: true, force: true });
  }
});
