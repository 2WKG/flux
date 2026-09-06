import { createRoot } from "react-dom/client";
import { useState } from "react";
import { LayerControls, type LayerDescriptor } from "./LayerControls";

const evidence = {
  source: "Synthetic harness fixture",
  vintage: "Static harness snapshot",
  coverage: "No geographic coverage",
  transformation: "None; supplied directly by this harness",
  uncertainty: "Not a live source or a scene result",
  syntheticTopologyCaveat: "Synthetic topology is only a harness disclosure; it does not represent Minnesota or Texas.",
};

const layers: readonly LayerDescriptor[] = [
  { id: "topology", label: "Synthetic topology disclosure", category: "topology", sourceStatus: "synthetic", evidenceClass: "fixture", evidence, visibility: { enabled: true } },
  { id: "facilities", label: "Facility layer", category: "facilities", sourceStatus: "unavailable", evidenceClass: "unavailable", evidence, visibility: { enabled: false, reason: "No facility artifact was supplied to this harness." } },
  { id: "flows", label: "Flow layer", category: "flows", sourceStatus: "source_supported", evidenceClass: "observed", visibility: { enabled: true } },
  { id: "events", label: "Event layer", category: "events", sourceStatus: "request_failed", evidenceClass: "unavailable", evidence, visibility: { enabled: false, reason: "The harness request failed; no event artifact is available." } },
  { id: "proposals", label: "Malformed proposal layer", category: "proposals", sourceStatus: "source_supported", evidenceClass: "malformed", evidence: {} as LayerDescriptor["evidence"], visibility: { enabled: true } },
  { id: "provenance", label: "Wrong-type provenance layer", category: "provenance", sourceStatus: "source_screened", evidenceClass: "malformed", evidence: { ...evidence, vintage: 2026 } as unknown as LayerDescriptor["evidence"], visibility: { enabled: true } },
];

function Harness() {
  const [visible, setVisible] = useState<readonly string[]>(["topology"]);
  return <main><p className="harness-banner">Synthetic contract harness — no live source, geographic coverage, scene, or filtering effect.</p><LayerControls layers={layers} visibleLayerIds={visible} onVisibleLayerIdsChange={setVisible} /><output aria-live="polite">Requested visible layers: {visible.join(", ") || "none"}</output></main>;
}

createRoot(document.getElementById("root")!).render(<Harness />);
