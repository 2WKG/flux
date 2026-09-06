import { createRoot } from "react-dom/client";
import { useState } from "react";
import { LayerControls, type LayerDescriptor } from "./LayerControls";
import "../styles.css";

const evidence = {
  source: "Synthetic harness fixture",
  vintage: "Static harness snapshot",
  coverage: "No geographic coverage",
  transformation: "None; supplied directly by this harness",
  uncertainty: "Not a live source or a scene result",
  syntheticTopologyCaveat: "Synthetic topology is only a harness disclosure; it does not represent Minnesota or Texas.",
};

export const harnessLayers: readonly LayerDescriptor[] = [
  { id: "topology", label: "Synthetic topology disclosure", category: "topology", sourceStatus: "synthetic", evidenceClass: "fixture", evidence, visibility: { enabled: true } },
  { id: "facilities", label: "Facility layer", category: "facilities", sourceStatus: "unavailable", evidenceClass: "unavailable", visibility: { enabled: false, reason: "No facility artifact was supplied to this harness; build one before requesting this layer." } },
  { id: "flows", label: "Flow layer", category: "flows", sourceStatus: "source_supported", evidenceClass: "observed", evidence, visibility: { enabled: true } },
  { id: "screened", label: "Screened corridor layer", category: "flows", sourceStatus: "source_screened", evidenceClass: "proxy", evidence, visibility: { enabled: true } },
  { id: "alternative", label: "Alternative corridor", category: "proposals", sourceStatus: "hypothetical", evidenceClass: "modeled", evidence, visibility: { enabled: true } },
  // No evidence and no producer reason: the failed request keeps its own label and the
  // panel refuses by name rather than inventing a reason or downgrading it to Unavailable.
  { id: "events", label: "Event layer", category: "events", sourceStatus: "request_failed", evidenceClass: "unavailable", visibility: { enabled: true } },
  { id: "proposals", label: "Malformed proposal layer", category: "proposals", sourceStatus: "source_supported", evidenceClass: "malformed", evidence: {} as LayerDescriptor["evidence"], visibility: { enabled: true } },
  { id: "provenance", label: "Wrong-type provenance layer", category: "provenance", sourceStatus: "source_screened", evidenceClass: "malformed", evidence: { ...evidence, vintage: 2026 } as unknown as LayerDescriptor["evidence"], visibility: { enabled: true } },
  { id: "unknown", label: "Unrecognized-status layer", category: "provenance", sourceStatus: "source_backed", evidenceClass: "observed", evidence, visibility: { enabled: true } },
];

function Harness() {
  const [visible, setVisible] = useState<readonly string[]>(["topology", "events"]);
  return (
    <main>
      <p className="harness-banner">
        Synthetic contract harness — no live source, geographic coverage, scene, or filtering effect.
      </p>
      <LayerControls layers={harnessLayers} visibleLayerIds={visible} onVisibleLayerIdsChange={setVisible} />
      <output aria-live="polite">Requested visible layers: {visible.join(", ") || "none"}</output>
    </main>
  );
}

// Guarded so the fixture list above can be imported by the node-side render test without
// attempting to mount; in the browser this is always taken.
if (typeof document !== "undefined") {
  const container = document.getElementById("root");
  if (container) createRoot(container).render(<Harness />);
}
