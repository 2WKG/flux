import type { Feature, FeatureCollection, Geometry, GeoJsonProperties } from "geojson";

export type AttributeDescriptor = Readonly<{
  unit: string;
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
    typeof value.unit === "string" &&
    typeof value.source === "string"
  );
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
 * Accept only a successful, declared server layer. Rendering never synthesizes
 * geometry, values, source classes, or scenario information from client state.
 */
export function toLayerPresentation(payload: unknown): LayerPresentation | null {
  if (!isRecord(payload) || payload.status !== "ok" || !isRecord(payload.data)) {
    return null;
  }

  const { data, meta } = payload;
  if (
    typeof data.layer !== "string" ||
    typeof data.crs !== "string" ||
    !isRecord(data.attributes) ||
    !isFeatureCollection(data.feature_collection) ||
    !isRecord(meta) ||
    !Array.isArray(meta.artifacts)
  ) {
    return null;
  }

  const attributes: Record<string, AttributeDescriptor> = {};
  for (const [field, value] of Object.entries(data.attributes)) {
    if (!isAttributeDescriptor(value)) {
      return null;
    }
    attributes[field] = value;
  }

  const sourceClasses = [...new Set(
    meta.artifacts.flatMap((artifact) =>
      isRecord(artifact) && typeof artifact.source_kind === "string"
        ? [artifact.source_kind]
        : [],
    ),
  )];
  const featureScenario = data.feature_collection.features
    .map((feature) => feature.properties?.scenario_id)
    .find((scenario): scenario is string => typeof scenario === "string");

  return {
    layer: data.layer,
    crs: data.crs,
    scenario: typeof data.scenario_id === "string" ? data.scenario_id : featureScenario ?? null,
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
