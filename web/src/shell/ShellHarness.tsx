/**
 * Isolated shell harness. It is not part of the shipped demo bundle: build it
 * with `npm run build:harness`, which points `scripts/build.mjs` at this entry
 * and writes to `dist-harness/`. `web/test/shell-harness.test.mjs` builds it the
 * same way and asserts it stays out of the demo bundle.
 */
import { createRoot } from "react-dom/client";
import { AppShell } from "./AppShell";

function Panel({ children }: { children: string }) {
  return <p style={{ margin: 0, lineHeight: 1.5 }}>{children}</p>;
}

createRoot(document.getElementById("root")!).render(
  <AppShell
    title="Isolated shell harness"
    source={{
      status: "synthetic",
      label: "Synthetic harness · no geography or live API",
      detail: "Panel content is supplied by slots; this page asserts no facility or scenario identity.",
    }}
    viewport={<div data-testid="viewport" style={{ alignItems: "center", display: "grid", height: "100%", justifyItems: "center" }}>Viewport slot</div>}
    controls={<button type="button">Control slot</button>}
    inspector={<Panel>Inspector slot</Panel>}
    timeline={<Panel>Timeline slot</Panel>}
    comparison={<Panel>Comparison slot</Panel>}
    chat={<Panel>Chat slot</Panel>}
  />,
);
