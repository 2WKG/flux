import { createRoot } from "react-dom/client";
import { MapLibreDeckFoundation } from "./MapLibreDeckFoundation";

createRoot(document.getElementById("root")!).render(
  <main>
    <p>Renderer foundation harness. No feature geometry, synthetic-coordinate conversion, or model asset is supplied.</p>
    <MapLibreDeckFoundation adaptation={{ kind: "rejected", reason: "aggregate_only_no_geometry", detail: "No accepted feature geometry was supplied to this harness." }} />
  </main>,
);
