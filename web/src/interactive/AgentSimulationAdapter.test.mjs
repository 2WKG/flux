// The adapter is a deliberately narrow SSR seam: its only input is the
// already-ordered generic `/ask` event list. These checks keep an eventual
// transport integration from treating a tool name or arbitrary result object
// as a simulation action, provider, scene attribution, or undo operation.
import assert from "node:assert/strict";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

import { build } from "esbuild";

const webRoot = path.dirname(new URL("../../package.json", import.meta.url).pathname);
const adapterPath = path.join(webRoot, "src/interactive/AgentSimulationAdapter.tsx");

async function adapter() {
  const directory = await mkdtemp(path.join(os.tmpdir(), "flux-452-agent-adapter-"));
  const entry = path.join(directory, "entry.tsx");
  const output = path.join(directory, "entry.mjs");
  await writeFile(entry, `
    import { renderToStaticMarkup } from "react-dom/server";
    import { AgentSimulationAdapter } from ${JSON.stringify(adapterPath)};
    export const render = (events) => renderToStaticMarkup(<AgentSimulationAdapter events={events} />);
  `, "utf8");
  await build({
    entryPoints: [entry],
    outfile: output,
    bundle: true,
    format: "esm",
    platform: "node",
    target: "node20",
    absWorkingDir: webRoot,
    nodePaths: [path.join(webRoot, "node_modules")],
    tsconfig: path.join(webRoot, "tsconfig.json"),
    banner: { js: 'import { createRequire as __createRequire } from "node:module"; const require = __createRequire(import.meta.url);' },
    logLevel: "silent",
  });
  try {
    return await import(pathToFileURL(output).href);
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
}

const { render } = await adapter();
const event = (type, seq, fields = {}) => ({ id: String(seq), v: 1, seq, type, ...fields });

test("all absent simulation capabilities render as typed unavailable states", () => {
  const markup = render([]);
  for (const capability of ["simulation_action", "provider", "scene_attribution", "reversal"]) {
    assert.match(markup, new RegExp(`data-agent-simulation-capability="${capability}"`));
    assert.match(markup, new RegExp(`data-agent-simulation-capability="${capability}"[^>]*data-agent-simulation-availability="unavailable"`));
  }
  assert.match(markup, /absent_from_received_ask_event_data/);
  assert.match(markup, /No explicit simulation action is present/);
  assert.match(markup, /No provider identity is present/);
  assert.match(markup, /No scene attribution is present/);
  assert.match(markup, /No reversal capability is present/);
  assert.doesNotMatch(markup, /<button/);
});

test("preserves only generic ordered tool and terminal-error trace facts", () => {
  const markup = render([
    event("lifecycle", 1, { status: "started" }),
    event("tool_call", 2, { call_id: "opaque-1", tool: "cascade", input: { arbitrary: "input" } }),
    event("text", 3, { delta: "A narration is not an action." }),
    event("tool_result", 4, { call_id: "opaque-1", tool: "cascade", ok: true, result: { scene_action: "untrusted" }, elapsed_ms: 12 }),
    event("error", 5, { status: "failed", error: { code: "unavailable", message: "Configured provider unavailable.", retryable: false } }),
  ]);

  const rows = [...markup.matchAll(/<li[^>]*data-ask-event-type="([^"]+)"[^>]*data-ask-event-seq="([^"]+)"[^>]*>([^<]*)<\/li>/g)];
  assert.deepEqual(rows.map((row) => [row[1], row[2], row[3]]), [
    ["tool_call", "2", "cascade: requested"],
    ["tool_result", "4", "cascade: completed"],
    ["error", "5", "unavailable: Configured provider unavailable."],
  ]);
  assert.doesNotMatch(markup, /scene_action/);
  assert.doesNotMatch(markup, /A narration is not an action/);
});
