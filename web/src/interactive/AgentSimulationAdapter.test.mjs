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
  // The frozen `unavailable` token is the availability; the finer machine cause
  // is carried alongside it, never instead of it.
  assert.match(markup, /data-agent-simulation-reason="absent_from_received_ask_event_data"/);
  assert.doesNotMatch(markup, /<button/);
});

test("preserves only generic ordered tool and terminal-error trace facts", () => {
  const markup = render([
    event("lifecycle", 1, { status: "started" }),
    event("tool_call", 2, { call_id: "opaque-1", tool: "cascade", input: { arbitrary: "input" } }),
    event("text", 3, { delta: "A narration is not an action." }),
    event("tool_result", 4, { call_id: "opaque-1", tool: "cascade", ok: true, result: { scene_action: "untrusted" }, elapsed_ms: 12 }),
    // A tool-level failure must never read as a completed call. Without an ok:false row
    // here the summary could report every result as "completed" and stay green.
    event("tool_call", 5, { call_id: "opaque-2", tool: "score_site", input: {} }),
    event("tool_result", 6, { call_id: "opaque-2", tool: "score_site", ok: false, error: { code: "timeout", message: "The site scoring tool did not finish in time." }, elapsed_ms: 20000 }),
    event("error", 7, { status: "failed", error: { code: "unavailable", message: "Configured provider unavailable.", retryable: false } }),
  ]);

  const rows = [...markup.matchAll(/<li[^>]*data-ask-event-type="([^"]+)"[^>]*data-ask-event-seq="([^"]+)"[^>]*>([^<]*)<\/li>/g)];
  assert.deepEqual(rows.map((row) => [row[1], row[2], row[3]]), [
    ["tool_call", "2", "cascade: requested"],
    ["tool_result", "4", "cascade: completed"],
    ["tool_call", "5", "score_site: requested"],
    ["tool_result", "6", "score_site: failed"],
    ["error", "7", "unavailable: Configured provider unavailable."],
  ]);
  assert.doesNotMatch(markup, /scene_action/);
  assert.doesNotMatch(markup, /A narration is not an action/);
});

test("a failed tool result renders as failed, never as completed", () => {
  const markup = render([
    event("tool_call", 1, { call_id: "call-1", tool: "run_cascade", input: {} }),
    event("tool_result", 2, {
      call_id: "call-1",
      tool: "run_cascade",
      ok: false,
      elapsed_ms: 9,
      error: { code: "artifact_unavailable", message: "The cascade artifact is not built." },
    }),
  ]);

  const rows = [...markup.matchAll(/<li[^>]*data-ask-event-seq="([^"]+)"[^>]*>([^<]*)<\/li>/g)];
  assert.deepEqual(rows.map((row) => [row[1], row[2]]), [
    ["1", "run_cascade: requested"],
    ["2", "run_cascade: failed"],
  ]);
  assert.doesNotMatch(markup, /run_cascade: completed/);
});

test("a published simulation tool name is a named simulation action, not a refusal", () => {
  // `run_cascade` is in ToolName in web/src/contracts/copilot-tools.d.ts, so
  // rendering it unavailable would be a wrong claim about the received data.
  const markup = render([
    event("tool_call", 1, { call_id: "call-1", tool: "run_cascade", input: { scenario_id: "s" } }),
  ]);
  assert.match(markup, /data-agent-simulation-capability="simulation_action"[^>]*data-agent-simulation-availability="available"/);
  assert.match(markup, /published simulation tools: run_cascade/);
  // A tool the contract does not publish is still not a simulation action.
  const other = render([event("tool_call", 1, { call_id: "c", tool: "not_a_published_tool", input: {} })]);
  assert.match(other, /data-agent-simulation-capability="simulation_action"[^>]*data-agent-simulation-availability="unavailable"/);
});

test("scene attribution is the result's ArtifactRef provenance, not a refusal", () => {
  const markup = render([
    event("tool_result", 1, {
      call_id: "call-1",
      tool: "run_cascade",
      ok: true,
      elapsed_ms: 12,
      result: {
        provenance: [
          { artifact_id: "cascade_runs", artifact_version: "2026-09-06", source_kind: "simulated", source_ref: "twin/cascade.py" },
        ],
      },
    }),
  ]);
  assert.match(markup, /data-agent-simulation-capability="scene_attribution"[^>]*data-agent-simulation-availability="available"/);
  assert.match(markup, /cascade_runs@2026-09-06/);

  // An incomplete reference is dropped rather than rendered with an invented field.
  const partial = render([
    event("tool_result", 1, {
      call_id: "call-1",
      tool: "run_cascade",
      ok: true,
      elapsed_ms: 12,
      result: { provenance: [{ artifact_id: "cascade_runs", source_kind: "simulated" }] },
    }),
  ]);
  assert.match(partial, /data-agent-simulation-capability="scene_attribution"[^>]*data-agent-simulation-availability="unavailable"/);
  assert.doesNotMatch(partial, /cascade_runs@/);

  // A source_kind outside the frozen ArtifactRef enum is not attribution either.
  const bogus = render([
    event("tool_result", 1, {
      call_id: "call-1",
      tool: "run_cascade",
      ok: true,
      elapsed_ms: 12,
      result: { provenance: [{ artifact_id: "a", artifact_version: "1", source_kind: "invented", source_ref: "r" }] },
    }),
  ]);
  assert.match(bogus, /data-agent-simulation-capability="scene_attribution"[^>]*data-agent-simulation-availability="unavailable"/);
});

test("provider and reversal stay unavailable: the v1 contract publishes neither", () => {
  const markup = render([
    event("tool_result", 1, {
      call_id: "call-1",
      tool: "run_cascade",
      ok: true,
      elapsed_ms: 12,
      result: { provenance: [{ artifact_id: "a", artifact_version: "1", source_kind: "simulated", source_ref: "r" }] },
    }),
  ]);
  for (const capability of ["provider", "reversal"]) {
    assert.match(markup, new RegExp(`data-agent-simulation-capability="${capability}"[^>]*data-agent-simulation-availability="unavailable"`));
  }
});

test("reads only a complete attributed additive scene action", () => {
  const markup = render([
    event("tool_call", 1, { call_id: "cascade-call", tool: "cascade", input: {} }),
    event("tool_result", 2, {
      call_id: "cascade-call",
      tool: "cascade",
      ok: true,
      elapsed_ms: 12,
      result: {
        scene_action: {
          action_id: "action-7",
          kind: "cascade",
          tool_call_id: "cascade-call",
          cascade_id: "cascade-1",
          reversible: true,
          status: "available",
        },
      },
    }),
  ]);

  assert.match(markup, /data-agent-simulation-capability="simulation_action"[^>]*data-agent-simulation-availability="available"/);
  assert.match(markup, /data-agent-scene-action="cascade"/);
  assert.match(markup, /data-agent-scene-action-id="action-7"/);
  assert.match(markup, /data-agent-scene-action-tool-call-id="cascade-call"/);
  assert.match(markup, /data-agent-scene-action-reversible="true"/);
  assert.match(markup, /Cascade id: cascade-1/);
  assert.match(markup, /No reversal operation is wired here/);
});

test("does not substitute an edit hash for an available cascade identity", () => {
  const markup = render([
    event("tool_result", 1, {
      call_id: "cascade-call",
      tool: "cascade",
      ok: true,
      elapsed_ms: 12,
      result: {
        scene_action: {
          action_id: "action-without-run",
          kind: "cascade",
          tool_call_id: "cascade-call",
          edit_hash: "an-edit-is-not-a-run",
          reversible: true,
          status: "available",
        },
      },
    }),
  ]);

  assert.match(markup, /data-agent-simulation-capability="simulation_action"[^>]*data-agent-simulation-availability="unavailable"/);
  assert.match(markup, /data-agent-scene-action="cascade"[^>]*data-agent-scene-action-status="unavailable"/);
  assert.match(markup, /no stable cascade_id, so it cannot be applied/);
  // The refusal carries no identifier at all: an edit hash on a refused cascade card is
  // the very substitution this guard exists to prevent.
  assert.doesNotMatch(markup, /an-edit-is-not-a-run/);
  assert.doesNotMatch(markup, /Edit hash:/);
  assert.doesNotMatch(markup, /Cascade id:/);
});

test("applies the same identity rule to scenario_edit, not only to cascade", () => {
  const markup = render([
    event("tool_result", 1, {
      call_id: "edit-call",
      tool: "scenario_edit",
      ok: true,
      elapsed_ms: 12,
      result: {
        scene_action: {
          action_id: "edit-without-hash",
          kind: "scenario_edit",
          tool_call_id: "edit-call",
          cascade_id: "a-run-is-not-an-edit",
          reversible: true,
          status: "available",
        },
      },
    }),
  ]);

  assert.match(markup, /data-agent-simulation-capability="simulation_action"[^>]*data-agent-simulation-availability="unavailable"/);
  assert.match(markup, /data-agent-scene-action="scenario_edit"[^>]*data-agent-scene-action-status="unavailable"/);
  assert.match(markup, /no stable edit_hash, so it cannot be applied/);
  assert.doesNotMatch(markup, /a-run-is-not-an-edit/);

  // The probe can tell the two states apart: with its own identity the same action is available.
  const complete = render([
    event("tool_result", 1, {
      call_id: "edit-call",
      tool: "scenario_edit",
      ok: true,
      elapsed_ms: 12,
      result: {
        scene_action: {
          action_id: "edit-with-hash",
          kind: "scenario_edit",
          tool_call_id: "edit-call",
          edit_hash: "edit-abc",
          reversible: true,
          status: "available",
        },
      },
    }),
  ]);
  assert.match(complete, /data-agent-scene-action="scenario_edit"[^>]*data-agent-scene-action-status="available"/);
  assert.match(complete, /Edit hash: edit-abc/);
});

test("rejects absent or invalid scene actions without inferring a capability", () => {
  const markup = render([
    event("tool_result", 1, {
      call_id: "cascade-call",
      tool: "cascade",
      ok: true,
      elapsed_ms: 12,
      result: { scene_action: { action_id: "action-7", kind: "cascade", tool_call_id: "other-call", reversible: true, status: "available" } },
    }),
    event("tool_result", 2, {
      call_id: "edit-call",
      tool: "scenario_edit",
      ok: true,
      elapsed_ms: 12,
      result: { scene_action: { action_id: "action-8", kind: "scenario_edit", tool_call_id: "edit-call", reversible: false, status: "available" } },
    }),
  ]);

  assert.match(markup, /data-agent-simulation-capability="simulation_action"[^>]*data-agent-simulation-availability="unavailable"/);
  assert.doesNotMatch(markup, /data-agent-scene-action=/);
  assert.doesNotMatch(markup, /action-7|action-8/);
});
