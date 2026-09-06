import type { ReactNode } from "react";

/** Values accepted from the scene/API contract; the inspector never derives one. */
export type AssetStatus =
  | "source_supported"
  | "source_screened"
  | "hypothetical"
  | "synthetic"
  | "unavailable"
  | "request_failed";

export type InspectorArtifactLabel = "source_backed" | "synthetic" | "unavailable";

export type InspectorField = Readonly<{
  label: string;
  value?: string;
  unit?: string;
  status?: "available" | "unavailable";
  uncertainty?: string;
  provenanceId?: string;
}>;

export type InspectorProvenance = Readonly<{
  sourceName: string;
  sourceRef?: string;
  sourceVersion?: string;
  retrievedAt?: string;
  coverage?: string;
  transformation?: string;
}>;

export type InspectorRelationship = Readonly<{
  id: string;
  label: string;
  relationship: string;
  status?: AssetStatus;
}>;

export type InspectorAsset = Readonly<{
  id?: string;
  name?: string;
  kind?: string;
  status: AssetStatus;
  artifactLabel?: InspectorArtifactLabel;
  scenario?: string;
  readiness?: string;
  coverage?: string;
  fields?: readonly InspectorField[];
  provenance?: readonly InspectorProvenance[];
  relationships?: readonly InspectorRelationship[];
  caveats?: readonly string[];
  message?: string;
}>;

export type InspectorProps = Readonly<{
  asset?: InspectorAsset | null;
  onSelectRelationship?: (relationship: InspectorRelationship) => void;
  className?: string;
  title?: ReactNode;
}>;
