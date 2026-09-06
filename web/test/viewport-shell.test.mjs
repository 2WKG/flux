// Render the routed page without a browser. The primary scene is a bundled
// synthetic fixture, so SSR must retain that explicit provenance rather than
// inventing a loading or source-backed result.
import assert from "node:assert/strict";
import { build } from "esbuild";
import { mkdir } from "node:fs/promises";
import test from "node:test";
import { fileURLToPath } from "node:url";

const webRoot = new URL("../", import.meta.url);
const compiled = new URL("../node_modules/.cache/flux-main-page-render.mjs", import.meta.url);
await mkdir(new URL(".", compiled), { recursive: true });
await build({
  stdin: {
    contents: `
      import { createElement } from "react";
      import { renderToStaticMarkup } from "react-dom/server";
      import { App, ChatDockView, chatReducer } from "./src/pages/MainPage";
      export { ChatDockView, chatReducer };
      export const renderApp = () => renderToStaticMarkup(createElement(App));
      export const renderDock = (props) => renderToStaticMarkup(createElement(ChatDockView, props));
    `,
    resolveDir: fileURLToPath(webRoot),
    loader: "tsx",
    sourcefile: "main-page-render-entry.tsx",
  },
  bundle: true,
  format: "esm",
  platform: "node",
  jsx: "automatic",
  packages: "external",
  loader: { ".css": "empty" },
  outfile: fileURLToPath(compiled),
});
const shell = await import(compiled.href);

test("the main route retains the bundled synthetic scene and its provenance", () => {
  const markup = shell.renderApp();
  assert.match(markup, /SYSTEM RESILIENCE \/ SCENARIO EXPLORER/);
  assert.match(markup, /Where does 300 MW cut the most unmet demand\?/);
  assert.match(markup, /no runtime request, and no claim about a real grid/);
  assert.match(markup, /data-source-status="synthetic"/);
  assert.match(markup, /Synthetic five-bus preview · not Minnesota data/);
});

test("the chat dock stays collapsed until a user opens its explicit unavailable state", () => {
  const collapsed = shell.renderDock({ open: false, onToggle: () => {} });
  assert.match(collapsed, /class="chat-dock collapsed"/);
  assert.match(collapsed, /aria-expanded="false"/);
  assert.match(collapsed, /id="chat-dock-body"[^>]*hidden/);

  let open = false;
  const onToggle = () => { open = shell.chatReducer(open, "toggle"); };
  const dock = shell.ChatDockView({ open, onToggle });
  const button = findByProp(dock, "className", "chat-toggle");
  assert.equal(typeof button?.props.onClick, "function");
  button.props.onClick();
  assert.equal(open, true);

  const expanded = shell.renderDock({ open, onToggle });
  assert.match(expanded, /class="chat-dock expanded"/);
  assert.match(expanded, /no Copilot endpoint, model result, or Minnesota artifact to query/);
});

function findByProp(node, prop, value) {
  if (!node || typeof node !== "object") return null;
  if (Array.isArray(node)) return node.map((child) => findByProp(child, prop, value)).find(Boolean) ?? null;
  if (node.props?.[prop] === value) return node;
  return findByProp(node.props?.children, prop, value);
}
