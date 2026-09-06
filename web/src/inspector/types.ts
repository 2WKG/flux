import type { ReactNode } from "react";
import type { AssetStatus } from "../labels";

/** Values accepted from the scene/API contract; the inspector never derives one. */
export type { AssetStatus };

/**
 * The artifact label the server asserts alongside the status. It is drawn from
 * the same six-token IA vocabulary: the panel shows one primary label, so the
 * two must agree, and a disagreement fails closed rather than picking a winner.
 */
export type InspectorArtifactLabel = AssetStatus;

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
  /** Server-asserted topology, e.g. the IA's `synthetic (ACTIVSg2000)`. */
  topology?: string;
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
