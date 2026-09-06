import { createRoot } from "react-dom/client";
import { AppShell } from "./AppShell";

function Panel({ children }: { children: string }) {
  return <p style={{ margin: 0, lineHeight: 1.5 }}>{children}</p>;
}

createRoot(document.getElementById("root")!).render(
  <AppShell
    title="Shell harness"
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
