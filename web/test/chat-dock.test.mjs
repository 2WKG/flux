// The chat dock's two load-bearing claims are that the context it shows is the context
// the server accepts, and that the context stays editable. Both are asserted here: the
// first against the real `copilot/routes/ask.py` source, the second by typing into a
// real DOM with React attached, which is what caught the reset bug in the first place.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

import { build, stop } from "esbuild";
import { JSDOM } from "jsdom";

const webRoot = path.dirname(new URL("../package.json", import.meta.url).pathname);
const repoRoot = path.dirname(webRoot);
const askSourcePath = path.join(repoRoot, "copilot", "routes", "ask.py");

// React's scheduler posts through a MessageChannel, whose real node ports keep the
// event loop alive forever and hang the runner after the last test. This shim has the
// same contract and settles on the macrotask queue instead.
const realMessageChannel = globalThis.MessageChannel;
globalThis.MessageChannel = class {
  constructor() {
    let handler = null;
    this.port1 = { set onmessage(value) { handler = value; }, get onmessage() { return handler; }, close() { handler = null; } };
    this.port2 = { postMessage: (data) => { setImmediate(() => handler?.({ data })); }, close() {} };
  }
};

const PROBE = `
export { default as React } from "react";
export { act } from "react";
export { createRoot } from "react-dom/client";
export { ChatDock, askHistory } from ${JSON.stringify(path.join(webRoot, "src/chat/ChatDock.tsx"))};
export { ASK_LIMITS, EMPTY_SCENE_CONTEXT, buildAskRequest } from ${JSON.stringify(path.join(webRoot, "src/chat/ask-contract.ts"))};
`;

let probePromise;
function probe() {
  probePromise ??= (async () => {
    const dir = await mkdtemp(path.join(os.tmpdir(), "flux-chat-probe-"));
    const entry = path.join(dir, "probe.tsx");
    const outfile = path.join(dir, "probe.mjs");
    await writeFile(entry, PROBE, "utf8");
    await build({
      entryPoints: [entry],
      outfile,
      bundle: true,
      format: "esm",
      platform: "browser",
      target: "es2020",
      absWorkingDir: webRoot,
      tsconfig: path.join(webRoot, "tsconfig.json"),
      nodePaths: [path.join(webRoot, "node_modules")],
      loader: { ".css": "empty" },
      define: { "process.env.NODE_ENV": '"development"' },
      logLevel: "silent",
    });
    return { outfile, dir };
  })();
  return probePromise;
}

/** A real DOM with React attached, so events go through React's own handlers. */
async function mounted(render) {
  const { outfile } = await probe();
  const dom = new JSDOM("<!doctype html><div id='root'></div>", { url: "http://localhost/" });
  const previous = {};
  // Deliberately minimal: overriding node's own globals (Event, navigator,
  // MutationObserver) wedges the test runner. React only needs the document.
  const globals = {
    window: dom.window,
    document: dom.window.document,
    HTMLElement: dom.window.HTMLElement,
    IS_REACT_ACT_ENVIRONMENT: true,
  };
  for (const [key, value] of Object.entries(globals)) {
    previous[key] = Object.getOwnPropertyDescriptor(globalThis, key);
    Object.defineProperty(globalThis, key, { value, configurable: true, writable: true });
  }
  const api = await import(pathToFileURL(outfile).href);
  const container = dom.window.document.getElementById("root");
  const root = api.createRoot(container);
  const type = (element, value) => {
    const proto = element.tagName === "TEXTAREA" ? dom.window.HTMLTextAreaElement.prototype
      : element.tagName === "SELECT" ? dom.window.HTMLSelectElement.prototype
      : dom.window.HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, "value").set.call(element, value);
    element.dispatchEvent(new dom.window.Event(element.tagName === "SELECT" ? "change" : "input", { bubbles: true }));
  };
  try {
    return await render({
      api,
      dom,
      container,
      render: (element) => api.act(() => { root.render(element); }),
      click: (element) => api.act(() => { element.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true })); }),
      type: (element, value) => api.act(() => { type(element, value); }),
      submit: (form) => api.act(() => { form.dispatchEvent(new dom.window.Event("submit", { bubbles: true, cancelable: true })); }),
      field: (name) => container.querySelector(`[name="${name}"]`),
    });
  } finally {
    await api.act(() => { root.unmount(); });
    for (const key of Object.keys(globals)) {
      if (previous[key]) Object.defineProperty(globalThis, key, previous[key]);
      else delete globalThis[key];
    }
    dom.window.close();
  }
}

/** Parse the field names the merged server model actually accepts. */
async function askContextFields() {
  const source = await readFile(askSourcePath, "utf8");
  const block = source.slice(source.indexOf("class AskContext(BaseModel):"), source.indexOf("class AskHistoryMessage(BaseModel):"));
  assert.ok(block.includes('extra="forbid"'), "AskContext must still forbid extra fields for this test to mean anything");
  return { block, fields: [...block.matchAll(/^ {4}(\w+): /gm)].map((match) => match[1]) };
}

test("the dock's scene context is exactly the server's AskContext, field for field", async () => {
  const { fields } = await askContextFields();
  await mounted(async ({ api }) => {
    assert.deepEqual(Object.keys(api.EMPTY_SCENE_CONTEXT).sort(), [...fields].sort());
    assert.equal(fields.length, 6);
  });
});

test("the request the dock hands its caller is the exact POST /ask body the server bounds", async () => {
  const source = await readFile(askSourcePath, "utf8");
  await mounted(async ({ api }) => {
    // Bounds mirrored from copilot/routes/ask.py, checked against that source.
    assert.match(source, /hour: int \| None = Field\(default=None, ge=0, le=167\)/);
    assert.equal(api.ASK_LIMITS.hourMin, 0);
    assert.equal(api.ASK_LIMITS.hourMax, 167);
    assert.match(source, /unit_mw not in \{300, 1000\}/);
    assert.deepEqual([...api.ASK_LIMITS.unitMwChoices], [300, 1000]);
    assert.match(source, /question: Annotated\[str, Field\(min_length=1, max_length=2_000\)\]/);
    assert.equal(api.ASK_LIMITS.questionMax, 2_000);
    assert.match(source, /list\[AskHistoryMessage\], Field\(max_length=6\)/);
    assert.equal(api.ASK_LIMITS.historyMax, 6);
    assert.match(source, /content: Annotated\[str, Field\(min_length=1, max_length=4_000\)\]/);
    assert.equal(api.ASK_LIMITS.historyContentMax, 4_000);
    assert.match(source, /attempt_id: Annotated\[str, Field\(min_length=16, max_length=128\)\]/);
    assert.match(source, /_ATTEMPT_ID_RE = re\.compile\(r"\^\[A-Za-z0-9_-\]\{16,128\}\$"\)/);
    assert.match(source, /max_length=128/);
    assert.equal(api.ASK_LIMITS.idMax, 128);
  });

  await mounted(async ({ api, render, type, submit, container }) => {
    const sent = [];
    await render(api.React.createElement(api.ChatDock, {
      context: { ...api.EMPTY_SCENE_CONTEXT, scenario_id: "cold-2027", hour: 42, unit_mw: 300 },
      contextRevision: "r1",
      attemptId: "attempt_0123456789abcdef",
      sourceLabel: "Fixture", sourceStatus: "synthetic", status: "idle",
      onSend: (request) => sent.push(request),
    }));
    await type(container.querySelector("textarea"), "Which corridor is worst at hour 42?");
    await submit(container.querySelector("form"));

    assert.equal(sent.length, 1);
    const body = sent[0];
    // Exactly the keys AskRequest declares — extra="forbid" makes anything else a 422.
    assert.deepEqual(Object.keys(body).sort(), ["attempt_id", "context", "history", "question"]);
    assert.equal(body.attempt_id, "attempt_0123456789abcdef");
    assert.equal(body.question, "Which corridor is worst at hour 42?");
    assert.deepEqual(body.history, []);
    const { fields } = await askContextFields();
    for (const key of Object.keys(body.context)) assert.ok(fields.includes(key), `context key ${key} is not an AskContext field`);
    assert.deepEqual(body.context, { scenario_id: "cold-2027", hour: 42, unit_mw: 300 });
  });
});

test("a second field can be typed: the draft resets on a new revision, never on context identity", async () => {
  await mounted(async ({ api, render, click, type, container, field }) => {
    // A realistic parent: it echoes every onContextChange straight back as a NEW object,
    // which is exactly what made the old identity-keyed reset unusable.
    let observed = null;
    let publish = null;
    // One stable component type, so a re-render is a re-render and not a remount.
    const Parent = ({ revision }) => {
      const [context, setContext] = api.React.useState(api.EMPTY_SCENE_CONTEXT);
      observed = context;
      publish = setContext;
      return api.React.createElement(api.ChatDock, {
        context, contextRevision: revision, attemptId: "attempt_0123456789abcdef",
        sourceLabel: "Fixture", sourceStatus: "synthetic", status: "idle",
        onContextChange: setContext,
      });
    };
    const draw = (revision) => render(api.React.createElement(Parent, { revision }));
    await draw("r1");
    await click(container.querySelector("[aria-expanded]"));

    // Type character by character, the way a keyboard does.
    const target = "cold-2027";
    for (let index = 1; index <= target.length; index += 1) {
      await type(field("scenario_id"), target.slice(0, index));
    }
    assert.equal(field("scenario_id").value, target, "each keystroke must survive the parent's echoed context");
    assert.equal(observed.scenario_id, target);

    // A second field must be typeable after the first one was edited.
    const site = "site-mn-014";
    for (let index = 1; index <= site.length; index += 1) {
      await type(field("selected_site_id"), site.slice(0, index));
    }
    assert.equal(field("selected_site_id").value, site, "a second field must be typeable too");
    assert.equal(field("scenario_id").value, target, "editing a second field must not wipe the first");

    // A new producer revision, with the producer's own context, refreshes the draft.
    await api.act(() => { publish(api.EMPTY_SCENE_CONTEXT); });
    assert.equal(field("scenario_id").value, target, "a producer context change alone must not discard the edit");
    await draw("r2");
    assert.equal(field("scenario_id").value, "", "a new contextRevision must refresh the draft");
    assert.equal(field("selected_site_id").value, "");
  });
});

test("done is a state of its own, and the error notice shows the server's code, message, and request id", async () => {
  await mounted(async ({ api, render, container }) => {
    const base = {
      context: api.EMPTY_SCENE_CONTEXT, contextRevision: "r1", attemptId: "attempt_0123456789abcdef",
      sourceLabel: "Fixture", sourceStatus: "synthetic",
    };
    await render(api.React.createElement(api.ChatDock, { ...base, status: "idle" }));
    const idle = container.textContent;
    assert.ok(idle.includes("Ready"));
    assert.ok(!idle.includes("Answer complete"));

    await render(api.React.createElement(api.ChatDock, { ...base, status: "done" }));
    const done = container.textContent;
    assert.ok(done.includes("Answer complete"), "done must be visibly distinct from idle");
    assert.notEqual(done, idle);

    await render(api.React.createElement(api.ChatDock, {
      ...base, status: "error",
      error: { code: "upstream_error", message: "The provider did not answer.", requestId: "req_01J8ZZ" },
    }));
    const failed = container.querySelector('[role="alert"]').textContent;
    assert.ok(failed.includes("upstream_error"), "the server error.code must be shown");
    assert.ok(failed.includes("The provider did not answer."), "the server message must be shown");
    assert.ok(failed.includes("req_01J8ZZ"), "the request id must be shown");

    await render(api.React.createElement(api.ChatDock, {
      ...base, status: "error",
      error: { code: "unavailable", message: "A required artifact is not built.", requestId: "req_01J900" },
    }));
    const unavailable = container.querySelector('[role="alert"]').textContent;
    assert.ok(unavailable.includes("Unavailable"), "error.code unavailable renders the Unavailable label");
    assert.ok(/next step/i.test(unavailable), "the IA requires a named next step for unavailable");
    assert.ok(unavailable.includes("req_01J900"));

    // `unavailable` is an SSE error code, never a chat status.
    const source = await readFile(new URL("../src/chat/ChatDock.tsx", import.meta.url), "utf8");
    assert.match(source, /export type ChatStatus = "idle" \| "streaming" \| "done" \| "error" \| "cancelled";/);
  });
});

test("the dock refuses to build a body the server would reject", async () => {
  await mounted(async ({ api }) => {
    const base = { attemptId: "attempt_0123456789abcdef", context: api.EMPTY_SCENE_CONTEXT, history: [] };
    assert.equal(api.buildAskRequest({ ...base, question: "ok" }).ok, true);

    const long = api.buildAskRequest({ ...base, question: "x".repeat(2_001) });
    assert.equal(long.ok, false);
    assert.ok(long.problems.some((problem) => problem.includes("2000")));

    const shortAttempt = api.buildAskRequest({ ...base, attemptId: "too-short", question: "ok" });
    assert.equal(shortAttempt.ok, false);

    const history = Array.from({ length: 7 }, () => ({ role: "user", content: "hi" }));
    assert.equal(api.buildAskRequest({ ...base, question: "ok", history }).ok, false);
    // askHistory() is what the dock actually posts, and it keeps the last six.
    assert.equal(api.askHistory(history.map((message, index) => ({ ...message, id: String(index) }))).length, 6);

    const longTurn = api.buildAskRequest({ ...base, question: "ok", history: [{ role: "user", content: "x".repeat(4_001) }] });
    assert.equal(longTurn.ok, false);

    const longId = api.buildAskRequest({ ...base, question: "ok", context: { ...api.EMPTY_SCENE_CONTEXT, scenario_id: "s".repeat(129) } });
    assert.equal(longId.ok, false);

    assert.equal(api.buildAskRequest({ ...base, question: "ok", context: { ...api.EMPTY_SCENE_CONTEXT, hour: 168 } }).ok, false);
    assert.equal(api.buildAskRequest({ ...base, question: "ok", context: { ...api.EMPTY_SCENE_CONTEXT, unit_mw: 500 } }).ok, false);
  });
});

function run(args, env) {
  return new Promise((resolve, reject) => {
    const child = spawn("node", args, { cwd: webRoot, env: { ...process.env, ...env } });
    let output = "";
    child.stdout.on("data", (chunk) => { output += chunk; });
    child.stderr.on("data", (chunk) => { output += chunk; });
    child.on("error", reject);
    child.on("close", (code) => (code === 0 ? resolve(output) : reject(new Error(output))));
  });
}

test("the standalone chat harness compiles as its own entry", async () => {
  const dist = await mkdtemp(path.join(os.tmpdir(), "flux-chat-harness-"));
  try {
    await run(["scripts/build.mjs"], { FLUX_WEB_ENTRY: "src/chat/harness.tsx", FLUX_WEB_DIST: dist });
    const app = await readFile(path.join(dist, "assets", "app.js"), "utf8");
    assert.match(app, /Standalone UI fixture/);
    assert.match(app, /Answer complete/);
    assert.doesNotMatch(app, /\bfetch\s*\(/, "the harness reaches no server");
  } finally {
    await rm(dist, { recursive: true, force: true });
  }
});

test.after(async () => {
  const built = await probePromise;
  if (built) await rm(built.dir, { recursive: true, force: true });
  // esbuild keeps a service process alive; without this the runner never exits.
  stop();
  globalThis.MessageChannel = realMessageChannel;
});
