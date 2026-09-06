import { createRoot } from "react-dom/client";
import { MapLibreDeckFoundation } from "./MapLibreDeckFoundation";

createRoot(document.getElementById("root")!).render(
  <main>
    <p>Renderer foundation harness. No feature geometry, synthetic-coordinate conversion, or model asset is supplied.</p>
    <MapLibreDeckFoundation adaptation={{
      kind: "topology_scene",
      nodes: [{ id: "synthetic-node", name: "Synthetic test node", position: [-94.2, 46.2], truthLabel: "synthetic" }],
      provenance: { layer: "harness", crs: "EPSG:4326", sourceNames: [], fixtureBatchIds: ["synthetic-harness"], topology: "synthetic harness" },
    }} />
  </main>,
);
