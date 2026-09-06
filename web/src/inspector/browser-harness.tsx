import { createRoot } from "react-dom/client";
import { useState } from "react";
import { Inspector, type InspectorAsset, type InspectorRelationship } from "./Inspector";
import { hypothetical, malformed, mismatched, requestFailed, sourceBacked, sourceScreened, synthetic, unavailable, unsafeFailure } from "./fixtures";

function Harness() {
  const [asset, setAsset] = useState<InspectorAsset | null>(sourceBacked);
  const [selection, setSelection] = useState("No relationship selected");
  const choose = (next: InspectorAsset | null) => { setAsset(next); setSelection("No relationship selected"); };
  const selectRelationship = (relationship: InspectorRelationship) => setSelection(`Selected relationship: ${relationship.id}`);
  return <main style={{ maxWidth: 540, margin: "24px auto", padding: 12 }}>
    <h1>Inspector browser harness</h1>
    <p>Fixture-only states for UI verification. No network request is made.</p>
    <p><button onClick={() => choose(sourceBacked)}>Source-supported fixture</button>{" "}<button onClick={() => choose(sourceScreened)}>Source-screened fixture</button>{" "}<button onClick={() => choose(hypothetical)}>Hypothetical fixture</button>{" "}<button onClick={() => choose(synthetic)}>Synthetic fixture</button>{" "}<button onClick={() => choose(unavailable)}>Unavailable fixture</button>{" "}<button onClick={() => choose(requestFailed)}>Request-failed fixture</button>{" "}<button onClick={() => choose(unsafeFailure)}>Unsafe failure fixture</button>{" "}<button onClick={() => choose(mismatched)}>Mismatched fixture</button>{" "}<button onClick={() => choose(malformed)}>Malformed fixture</button>{" "}<button onClick={() => choose(null)}>Empty fixture</button></p>
    <p role="status">{selection}</p>
    <Inspector asset={asset} onSelectRelationship={selectRelationship} />
  </main>;
}
createRoot(document.getElementById("root")!).render(<Harness />);
