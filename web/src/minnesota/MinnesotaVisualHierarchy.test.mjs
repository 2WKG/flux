import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

import { build } from "esbuild";

const webRoot = path.dirname(new URL("../../package.json", import.meta.url).pathname);
const componentPath = path.join(webRoot, "src/minnesota/MinnesotaVisualHierarchy.tsx");
const labelsPath = path.join(webRoot, "src/labels.ts");
const cssPath = path.join(webRoot, "src/minnesota/MinnesotaVisualHierarchy.css");

async function moduleUnderTest() {
  const directory = await mkdtemp(path.join(os.tmpdir(), "flux-398-mn-polish-"));
  const entry = path.join(directory, "entry.tsx");
  const outfile = path.join(directory, "entry.mjs");
  await writeFile(entry, `
    import { renderToStaticMarkup } from "react-dom/server";
    import { MinnesotaVisualHierarchy } from ${JSON.stringify(componentPath)};
    export { MinnesotaVisualHierarchy };
    export function render(status) {
      return renderToStaticMarkup(<MinnesotaVisualHierarchy
        truthStatus={status}
        truthNote="The artifact names this evidence boundary."
        eyebrow="Minnesota / aggregate evidence"
        title="Accepted aggregate coverage"
        summary="No topology or model result is asserted by this frame."
      ><p>Host-delivered content</p></MinnesotaVisualHierarchy>);
    }
  `, "utf8");
  await build({
    entryPoints: [entry], outfile, bundle: true, format: "esm", platform: "node", target: "node20",
    absWorkingDir: webRoot, nodePaths: [path.join(webRoot, "node_modules")],
    tsconfig: path.join(webRoot, "tsconfig.json"), loader: { ".css": "empty" }, logLevel: "silent",
    banner: { js: 'import { createRequire as __createRequire } from "node:module"; const require = __createRequire(import.meta.url);' },
  });
  const loaded = await import(pathToFileURL(outfile).href);
  await rm(directory, { recursive: true, force: true });
  return loaded;
}

test("the frame renders caller-supplied truth vocabulary and never invents a result", async () => {
  const { render } = await moduleUnderTest();
  const html = render("unavailable");
  assert.match(html, /data-mn-visual-hierarchy="true"/);
  assert.match(html, /data-truth-label="unavailable"/);
  assert.match(html, />Unavailable</);
  assert.match(html, /Host-delivered content/);
  assert.match(html, /No topology or model result is asserted by this frame/);
});

test("every frozen status is accepted through the caller-owned truth prop", async () => {
  const { ASSET_STATUS_TOKENS } = await import(pathToFileURL(labelsPath).href);
  const { render } = await moduleUnderTest();
  for (const status of ASSET_STATUS_TOKENS) {
    assert.match(render(status), new RegExp(`data-truth-label="${status}"`));
  }
});

test("the local polish preserves reduced-motion and forced-colors accommodations", async () => {
  const css = await readFile(cssPath, "utf8");
  assert.match(css, /@media \(prefers-reduced-motion: reduce\)/);
  assert.match(css, /transition-duration: \.01ms !important/);
  assert.match(css, /@media \(forced-colors: active\)/);
  assert.match(css, /\.mn-visual-hierarchy/);
});
