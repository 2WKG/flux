import { FailureState } from "../failure-states/FailureState";
import { Inspector } from "../inspector/Inspector";
import type { InspectorAsset, InspectorField, InspectorProvenance } from "../inspector/types";
import { STATUS_COPY } from "../source-truth";
import { texasNodeLabels, texasNodeStyle } from "./scene";
import type { NormalizedTexasNode, TexasNodeAdaptation } from "./types";
import type { Scale } from "../navigation/scale-ladder";

function field(label: string, value: string | undefined, unit: string | undefined, provenanceId: string): InspectorField {
  return { label, value, unit, status: value === undefined ? "unavailable" : "available", provenanceId };
}

function provenance(node: NormalizedTexasNode): readonly InspectorProvenance[] {
  return Object.entries(node.fieldProvenance).map(([fieldName, truthLabel]) => ({
    sourceName: truthLabel,
    transformation: fieldName,
  }));
}

/** Build an inspector view entirely from normalized server fields and field evidence. */
export function texasNodeInspectorAsset(node: NormalizedTexasNode): InspectorAsset {
  const draw = node.hourDraw.availability === "available" ? String(node.hourDraw.mw) : undefined;
  return {
    id: node.id,
    name: node.name ?? "Node identity unavailable",
    kind: `Texas ${node.role} node`,
    status: node.truth.status,
    artifactLabel: node.truth.status,
    topology: node.truth.topology ?? undefined,
    message: `${STATUS_COPY[node.truth.status]} location evidence. Every field below names the server-supplied evidence field.`,
    fields: [
      field("Longitude", String(node.longitude), "°", "lon"),
      field("Latitude", String(node.latitude), "°", "lat"),
      field("Base voltage", String(node.baseKv), "kV", "base_kv"),
      field("Role", node.role, undefined, "role"),
      field("Hour-scaled draw", draw, "MW", "draw_mw"),
      field("Scenario", node.hourDraw.scenarioId, undefined, "draw_mw"),
      field("Scenario hour", String(node.hourDraw.hour), undefined, "draw_mw"),
      field("Generation capability", String(node.generationCapacityMw), "MW", "generation_capacity_mw"),
      field("County", node.county ?? undefined, undefined, "county_name"),
      field("Balancing authority", node.ba ?? undefined, undefined, "ba_code"),
      field("Critical facilities", node.criticalFacilities.map((facility) => `${facility.name} (${facility.bindingMethod})`).join(", ") || undefined, undefined, "critical_loads"),
    ],
    provenance: provenance(node),
    caveats: node.hourDraw.availability === "unavailable"
      ? [`${node.hourDraw.reason}: the server did not provide draw MW for scenario ${node.hourDraw.scenarioId}, hour ${node.hourDraw.hour}.`]
      : [],
  };
}

/**
 * Every node carries its own truth label, and the asserted topology token when
 * the server supplied one. `CLAUDE.md` requires ACTIVSg2000 to be labelled in
 * user-visible results, and this marker previously rendered no truth label at
 * all: the token could vanish from the whole surface with a green suite.
 */
export function TexasNodeMarker({ node, scale }: Readonly<{ node: NormalizedTexasNode; scale: Scale }>) {
  const style = texasNodeStyle(node);
  const labels = texasNodeLabels(node, scale);
  return <article
    aria-label={`${node.name ?? node.id} node`}
    data-role={node.role}
    data-voltage-class={style.voltageClass}
    data-truth-status={node.truth.status}
    data-topology={node.truth.topology ?? ""}
  >
    <span aria-hidden="true" data-glyph={style.glyph} style={{ borderWidth: style.strokeWidth }} />
    <strong>{node.name ?? node.id}</strong>
    <span>{node.baseKv} kV · {node.role}</span>
    <p data-truth-label>
      {STATUS_COPY[node.truth.status]}{node.truth.topology ? ` · ${node.truth.topology}` : ""}
    </p>
    <ul>{labels.map((label) => <li key={label.key}>{label.text}</li>)}</ul>
  </article>;
}

export function TexasNodeInspector({ node }: Readonly<{ node: NormalizedTexasNode }>) {
  return <Inspector title="Texas node inspector" asset={texasNodeInspectorAsset(node)} />;
}

/** An endpoint failure remains a shared failure-state surface, never an empty map. */
export function TexasNodesFailure({ adaptation }: Readonly<{ adaptation: TexasNodeAdaptation }>) {
  if (adaptation.kind === "ready") return null;
  return <FailureState state={{ kind: adaptation.status === "unavailable" ? "unavailable" : "failed", message: adaptation.message, code: "texas_node_adapter" }} />;
}
