import { createRoot } from "react-dom/client";
import { MapLibreDeckFoundation } from "./MapLibreDeckFoundation";
import { sceneViewFor } from "./scene-view";

/**
 * Manual harness. It feeds a synthetic ACTIVSg2000-shaped adaptation through
 * the same seam the app uses, so the refusal is visible by eye: the node sits
 * at central-Minnesota coordinates and must still produce zero feature layers.
 */
const syntheticScene = sceneViewFor({
  kind: "topology_scene",
  nodes: [{ id: "synthetic-node", name: "Synthetic test node", position: [-94.2, 46.2], truthLabel: "synthetic" }],
  provenance: { layer: "harness", crs: "EPSG:4326", sourceNames: [], fixtureBatchIds: ["synthetic-harness"], topology: "synthetic (ACTIVSg2000)" },
});

createRoot(document.getElementById("root")!).render(
  <main>
    <p>Renderer foundation harness. No feature geometry, synthetic-coordinate conversion, or model asset is supplied.</p>
    <MapLibreDeckFoundation view={syntheticScene} />
  </main>,
);
