import { createRoot } from "react-dom/client";
import { useState } from "react";
import { Inspector, type InspectorAsset, type InspectorRelationship } from "./Inspector";

const sourceBacked: InspectorAsset = {
  id: "server:asset:example", name: "Server-described asset", kind: "Facility", status: "source_supported", artifactLabel: "source_backed", scenario: "Unavailable", readiness: "Server status supplied", coverage: "Server supplied coverage",
  fields: [{ label: "Capacity", value: "Server supplied", unit: "MW", uncertainty: "Uncertainty supplied by server", provenanceId: "capacity_mw" }],
  provenance: [{ sourceName: "Server source", sourceVersion: "Version supplied by server", coverage: "Coverage supplied by server", sourceRef: "server://provenance/example" }],
  relationships: [{ id: "relation:unavailable", label: "Related detail unavailable", relationship: "Relationship supplied by server", status: "unavailable" }],
  caveats: ["Harness values exercise presentation only; they are not an asset claim."],
};
const unavailable: InspectorAsset = { status: "unavailable", artifactLabel: "unavailable", message: "Fixture: source detail is explicitly unavailable." };
const requestFailed: InspectorAsset = { status: "request_failed", artifactLabel: "unavailable", message: "Fixture: the source request failed and no result was inferred." };
const mismatched = { id: "unsafe:input", name: "Must not render", kind: "Facility", status: "source_supported", artifactLabel: "synthetic", fields: [{ label: "Must not render", value: "42", unit: "MW" }] } as unknown as InspectorAsset;
const malformed = { status: "source_supported", artifactLabel: "source_backed", fields: "not an array" } as unknown as InspectorAsset;
const unsafeFailure = { id: "unsafe:failure", name: "Must not render", status: "request_failed", artifactLabel: "unavailable", fields: [{ label: "Must not render", value: "42", unit: "MW" }], message: "Fixture: the source request failed and no result was inferred." } as unknown as InspectorAsset;

function Harness() {
  const [asset, setAsset] = useState<InspectorAsset | null>(sourceBacked);
  const [selection, setSelection] = useState("No relationship selected");
  const choose = (next: InspectorAsset | null) => { setAsset(next); setSelection("No relationship selected"); };
  const selectRelationship = (relationship: InspectorRelationship) => setSelection(`Selected relationship: ${relationship.id}`);
  return <main style={{ maxWidth: 540, margin: "24px auto", padding: 12 }}>
    <h1>Inspector browser harness</h1>
    <p>Fixture-only states for UI verification. No network request is made.</p>
    <p><button onClick={() => choose(sourceBacked)}>Source-backed fixture</button>{" "}<button onClick={() => choose(unavailable)}>Unavailable fixture</button>{" "}<button onClick={() => choose(requestFailed)}>Request-failed fixture</button>{" "}<button onClick={() => choose(unsafeFailure)}>Unsafe failure fixture</button>{" "}<button onClick={() => choose(mismatched)}>Mismatched fixture</button>{" "}<button onClick={() => choose(malformed)}>Malformed fixture</button>{" "}<button onClick={() => choose(null)}>Empty fixture</button></p>
    <p role="status">{selection}</p>
    <Inspector asset={asset} onSelectRelationship={selectRelationship} />
  </main>;
}
createRoot(document.getElementById("root")!).render(<Harness />);
