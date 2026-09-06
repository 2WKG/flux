import type { InspectorAsset } from "./types";

/**
 * Fixture-only assets. They exercise presentation and the fail-closed boundary;
 * none of them asserts a real facility, corridor, or grid. Shared by the browser
 * harness and by browser-harness.test.mjs so both drive the same inputs.
 */
export const sourceBacked: InspectorAsset = {
  id: "server:asset:example", name: "Server-described asset", kind: "Facility", status: "source_supported", artifactLabel: "source_supported", scenario: "Unavailable", readiness: "Server status supplied", coverage: "Server supplied coverage",
  fields: [{ label: "Capacity", value: "Server supplied", unit: "MW", uncertainty: "Uncertainty supplied by server", provenanceId: "capacity_mw" }],
  provenance: [{ sourceName: "Server source", sourceVersion: "Version supplied by server", coverage: "Coverage supplied by server", sourceRef: "server://provenance/example" }],
  relationships: [{ id: "relation:unavailable", label: "Related detail unavailable", relationship: "Relationship supplied by server", status: "unavailable" }],
  caveats: ["Harness values exercise presentation only; they are not an asset claim."],
};

export const sourceScreened: InspectorAsset = {
  id: "server:asset:screened", name: "Screened asset", kind: "Corridor", status: "source_screened", artifactLabel: "source_screened", readiness: "Server status supplied",
};

/** A compared alternative: labelled "Hypothetical", never "source_backed". */
export const hypothetical: InspectorAsset = {
  id: "server:asset:alternative", name: "Compared alternative", kind: "Facility", status: "hypothetical", artifactLabel: "hypothetical", scenario: "Server supplied scenario",
};

/** Source-neutral is not unlabelled: the synthetic topology is named, not hidden. */
export const synthetic: InspectorAsset = {
  id: "server:asset:synthetic", name: "Synthetic artifact", kind: "Generation asset", status: "synthetic", artifactLabel: "synthetic", topology: "synthetic (ACTIVSg2000)",
};

export const unavailable: InspectorAsset = { status: "unavailable", artifactLabel: "unavailable", message: "Fixture: source detail is explicitly unavailable." };
export const requestFailed: InspectorAsset = { status: "request_failed", artifactLabel: "request_failed", message: "Fixture: the source request failed and no result was inferred." };
export const mismatched = { id: "unsafe:input", name: "Must not render", kind: "Facility", status: "source_supported", artifactLabel: "synthetic", fields: [{ label: "Must not render", value: "42", unit: "MW" }] } as unknown as InspectorAsset;
export const malformed = { status: "source_supported", artifactLabel: "source_supported", fields: "not an array" } as unknown as InspectorAsset;
export const unsafeFailure = { id: "unsafe:failure", name: "Must not render", status: "request_failed", artifactLabel: "request_failed", fields: [{ label: "Must not render", value: "42", unit: "MW" }], message: "Fixture: the source request failed and no result was inferred." } as unknown as InspectorAsset;
