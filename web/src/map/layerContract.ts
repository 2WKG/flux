import type { Feature, FeatureCollection, Geometry, GeoJsonProperties } from "geojson";

export type AttributeDescriptor = Readonly<{
  unit: string | null;
  source: string;
}>;

export type LayerArtifact = Readonly<{
  artifact_id: string;
  artifact_version: string;
  source_kind: string;
}>;

export type ServerLayerPayload = Readonly<{
  status: "ok";
  data: Readonly<{
    layer: string;
    crs: string;
    attributes: Readonly<Record<string, AttributeDescriptor>>;
    feature_collection: FeatureCollection<Geometry, GeoJsonProperties>;
    scenario_id?: string;
  }>;
  meta: Readonly<{
    artifacts: readonly LayerArtifact[];
  }>;
}>;

export type LayerPresentation = Readonly<{
  layer: string;
  crs: string;
  scenario: string | null;
  attributes: Readonly<Record<string, AttributeDescriptor>>;
  sourceClasses: readonly string[];
  featureCollection: FeatureCollection<Geometry, GeoJsonProperties>;
}>;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isAttributeDescriptor(value: unknown): value is AttributeDescriptor {
  return (
    isRecord(value) &&
    (typeof value.unit === "string" || value.unit === null) &&
    typeof value.source === "string"
  );
}

function parseAttributes(value: unknown): Record<string, AttributeDescriptor> | null {
  if (!isRecord(value)) {
    return null;
  }

  const attributes: Record<string, AttributeDescriptor> = {};
  for (const [field, descriptor] of Object.entries(value)) {
    if (!isAttributeDescriptor(descriptor)) {
      return null;
    }
    attributes[field] = descriptor;
  }
  return attributes;
}

function scenarioFromFeatures(featureCollection: FeatureCollection<Geometry, GeoJsonProperties>): string | null {
  return featureCollection.features
    .map((feature) => feature.properties?.scenario_id)
    .find((scenario): scenario is string => typeof scenario === "string") ?? null;
}

function bareLayerPresentation(payload: Record<string, unknown>): LayerPresentation | null {
  if (!isFeatureCollection(payload) || typeof payload.layer !== "string") {
    return null;
  }
  const crs = payload.crs;
  const provenance = payload.provenance;
  if (
    !isRecord(crs) ||
    !isRecord(crs.properties) ||
    typeof crs.properties.name !== "string" ||
    !isRecord(provenance) ||
    !Array.isArray(provenance.source_kinds)
  ) {
    return null;
  }
  const attributes = parseAttributes(payload.attributes);
  if (!attributes) {
    return null;
  }
  const sourceClasses: string[] = [];
  for (const sourceKind of provenance.source_kinds) {
    if (sourceKind === null) {
      continue;
    }
    if (typeof sourceKind !== "string") {
      return null;
    }
    if (!sourceClasses.includes(sourceKind)) {
      sourceClasses.push(sourceKind);
    }
  }

  return {
    layer: payload.layer,
    crs: crs.properties.name,
    scenario: scenarioFromFeatures(payload),
    attributes,
    sourceClasses,
    featureCollection: payload,
  };
}

function isFeatureCollection(value: unknown): value is FeatureCollection<
  Geometry,
  GeoJsonProperties
> {
  return (
    isRecord(value) &&
    value.type === "FeatureCollection" &&
    Array.isArray(value.features)
  );
}

/**
 * Accept only a declared server layer: the legacy success envelope or the
 * documented bare GeoJSON route response. Rendering never synthesizes
 * geometry, values, source classes, or scenario information from client state.
 */
export function toLayerPresentation(payload: unknown): LayerPresentation | null {
  if (!isRecord(payload)) {
    return null;
  }

  if (isFeatureCollection(payload)) {
    return bareLayerPresentation(payload);
  }

  if (payload.status !== "ok" || !isRecord(payload.data)) {
    return null;
  }

  const { data, meta } = payload;
  if (
    typeof data.layer !== "string" ||
    typeof data.crs !== "string" ||
    !isFeatureCollection(data.feature_collection) ||
    !isRecord(meta) ||
    !Array.isArray(meta.artifacts)
  ) {
    return null;
  }

  const attributes = parseAttributes(data.attributes);
  if (!attributes) {
    return null;
  }

  const sourceClasses = [...new Set(
    meta.artifacts.flatMap((artifact) =>
      isRecord(artifact) && typeof artifact.source_kind === "string"
        ? [artifact.source_kind]
        : [],
    ),
  )];
  return {
    layer: data.layer,
    crs: data.crs,
    scenario: typeof data.scenario_id === "string" ? data.scenario_id : scenarioFromFeatures(data.feature_collection),
    attributes,
    sourceClasses,
    featureCollection: data.feature_collection,
  };
}

export function featureProperties(
  feature: Feature<Geometry, GeoJsonProperties> | undefined,
): readonly [string, string][] {
  if (!feature?.properties) {
    return [];
  }
  return Object.entries(feature.properties).flatMap(([key, value]) => {
    if (value === null || typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
      return [[key, String(value)]];
    }
    return [];
  });
}
