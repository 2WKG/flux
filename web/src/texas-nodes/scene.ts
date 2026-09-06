import { detailLevelForScale } from "../navigation/semantic-zoom";
import type { Scale } from "../navigation/scale-ladder";
import type { NormalizedTexasNode, TexasNodeRole } from "./types";

export type TexasNodeGlyph = "triangle" | "square" | "diamond" | "circle";
export type TexasVoltageClass = "extra_high" | "high" | "subtransmission" | "distribution";

export type TexasNodeStyle = Readonly<{
  glyph: TexasNodeGlyph;
  voltageClass: TexasVoltageClass;
  /** A visual voltage semantic, not a flow, loading, or calculated electrical value. */
  strokeWidth: number;
}>;

const ROLE_GLYPH: Readonly<Record<TexasNodeRole, TexasNodeGlyph>> = {
  producer: "triangle",
  consumer: "square",
  both: "diamond",
  transmission: "circle",
};

export function texasNodeStyle(node: Pick<NormalizedTexasNode, "role" | "baseKv">): TexasNodeStyle {
  if (node.baseKv >= 500) return { glyph: ROLE_GLYPH[node.role], voltageClass: "extra_high", strokeWidth: 4 };
  if (node.baseKv >= 230) return { glyph: ROLE_GLYPH[node.role], voltageClass: "high", strokeWidth: 3 };
  if (node.baseKv >= 115) return { glyph: ROLE_GLYPH[node.role], voltageClass: "subtransmission", strokeWidth: 2 };
  return { glyph: ROLE_GLYPH[node.role], voltageClass: "distribution", strokeWidth: 1 };
}

export type TexasNodeLabel = Readonly<{ key: string; text: string }>;

/**
 * Label selection only controls visibility by semantic zoom. It does not rank
 * nodes, compute a label value, or substitute a missing server field.
 */
export function texasNodeLabels(node: NormalizedTexasNode, scale: Scale): readonly TexasNodeLabel[] {
  const detail = detailLevelForScale(scale);
  if (detail.kind === "rejected" || detail.level.labelDetail === "none") return [];
  const labels: TexasNodeLabel[] = [{ key: "role", text: node.role }];
  if (node.name) labels.unshift({ key: "name", text: node.name });
  if (detail.level.labelDetail === "all") {
    labels.push({ key: "voltage", text: `${node.baseKv} kV` });
    if (node.hourDraw.availability === "available") labels.push({ key: "draw", text: `${node.hourDraw.mw} MW draw` });
    else labels.push({ key: "draw", text: `Draw unavailable for ${node.hourDraw.scenarioId}, hour ${node.hourDraw.hour}` });
    if (node.generationCapacityMw !== null) labels.push({ key: "capability", text: `${node.generationCapacityMw} MW capability` });
    if (node.county) labels.push({ key: "county", text: node.county });
    if (node.ba) labels.push({ key: "ba", text: node.ba });
    for (const facility of node.criticalFacilities) labels.push({ key: `critical-${facility.id}`, text: facility.name });
  }
  return labels;
}
