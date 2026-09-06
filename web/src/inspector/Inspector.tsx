import { useId, type CSSProperties } from "react";
import type { AssetStatus, InspectorAsset, InspectorField, InspectorProps } from "./types";

export type { AssetStatus, InspectorArtifactLabel, InspectorAsset, InspectorField, InspectorProps, InspectorProvenance, InspectorRelationship } from "./types";

const statusText: Record<AssetStatus, string> = {
  source_supported: "Source supported",
  source_screened: "Source screened",
  hypothetical: "Hypothetical",
  synthetic: "Synthetic",
  unavailable: "Unavailable",
  request_failed: "Request failed",
};

const statusExplanation: Record<AssetStatus, string> = {
  source_supported: "The server supplied this status. Review the provenance before relying on a field.",
  source_screened: "The server supplied a screening status. It is not a final approval or operational conclusion.",
  hypothetical: "This is a hypothetical artifact. It does not establish a real-world condition or outcome.",
  synthetic: "This artifact is synthetic. It must not be read as a real facility, corridor, or operating grid.",
  unavailable: "Source detail is unavailable. The inspector does not substitute an identity, metric, or location.",
  request_failed: "The source request failed. No result has been inferred from the failure.",
};

const expectedArtifactLabel: Record<AssetStatus, "source_backed" | "synthetic" | "unavailable"> = {
  source_supported: "source_backed", source_screened: "source_backed", hypothetical: "source_backed",
  synthetic: "synthetic", unavailable: "unavailable", request_failed: "unavailable",
};

function isAssetStatus(value: unknown): value is AssetStatus {
  return typeof value === "string" && value in statusText;
}

function unavailableInput(message: string): InspectorAsset {
  return { status: "unavailable", artifactLabel: "unavailable", message };
}

function unavailableResponse(status: "unavailable" | "request_failed", message?: unknown): InspectorAsset {
  return { status, artifactLabel: "unavailable", message: typeof message === "string" ? message : statusExplanation[status] };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function stringsOnly(value: Record<string, unknown>, keys: readonly string[]): boolean {
  return keys.every((key) => value[key] === undefined || typeof value[key] === "string");
}

function hasSafeDetailShape(candidate: Record<string, unknown>): boolean {
  if (!stringsOnly(candidate, ["id", "name", "kind", "scenario", "readiness", "coverage", "message"])) return false;
  const fields = candidate.fields;
  const provenance = candidate.provenance;
  const relationships = candidate.relationships;
  const caveats = candidate.caveats;
  return (fields === undefined || Array.isArray(fields) && fields.every((field) => isRecord(field) && typeof field.label === "string" && stringsOnly(field, ["value", "unit", "status", "uncertainty", "provenanceId"])))
    && (provenance === undefined || Array.isArray(provenance) && provenance.every((source) => isRecord(source) && typeof source.sourceName === "string" && stringsOnly(source, ["sourceRef", "sourceVersion", "retrievedAt", "coverage", "transformation"])))
    && (relationships === undefined || Array.isArray(relationships) && relationships.every((relationship) => isRecord(relationship) && typeof relationship.id === "string" && typeof relationship.label === "string" && typeof relationship.relationship === "string" && stringsOnly(relationship, ["status"])))
    && (caveats === undefined || Array.isArray(caveats) && caveats.every((caveat) => typeof caveat === "string"));
}

/** Runtime boundary for values supplied by a scene adapter or HTTP response. */
export function normalizeInspectorAsset(asset: unknown): InspectorAsset {
  if (!isRecord(asset)) return unavailableInput("No server asset was supplied.");
  const candidate = asset as InspectorAsset;
  if (!isAssetStatus(candidate.status)) return unavailableInput("Asset status is missing or not recognized.");
  if (candidate.artifactLabel !== expectedArtifactLabel[candidate.status]) {
    return unavailableInput("Asset status and artifact label do not agree; source detail is withheld.");
  }
  if (candidate.status === "unavailable" || candidate.status === "request_failed") {
    return unavailableResponse(candidate.status, candidate.message);
  }
  if (!hasSafeDetailShape(asset)) return unavailableInput("Asset detail is malformed; source detail is withheld.");
  return candidate;
}

function displayedField(field: InspectorField): string {
  if (field.status === "unavailable" || field.value === undefined || field.value === "") return "Unavailable";
  return field.unit ? `${field.value} ${field.unit}` : field.value;
}

function FieldList({ fields }: { fields: readonly InspectorField[] }) {
  if (fields.length === 0) return <p style={styles.empty}>No server-asserted fields are available.</p>;
  return <dl style={styles.list}>
    {fields.map((field) => <div key={`${field.label}-${field.provenanceId ?? ""}`} style={styles.row}>
      <dt style={styles.term}>{field.label}</dt>
      <dd style={styles.definition}>
        <span>{displayedField(field)}</span>
        {field.uncertainty && <small style={styles.note}>Uncertainty: {field.uncertainty}</small>}
        {field.provenanceId && <small style={styles.note}>Source field: {field.provenanceId}</small>}
      </dd>
    </div>)}
  </dl>;
}

/**
 * A source-neutral side-panel. It accepts only asserted scene/API data and keeps
 * unavailable, failed, and synthetic states distinct for the shell that hosts it.
 */
export function Inspector({ asset, onSelectRelationship, className, title = "Inspector" }: InspectorProps) {
  const descriptionId = useId();
  if (!asset) return <aside className={className} aria-label="Inspector" style={styles.panel}>
    <h2 style={styles.title}>{title}</h2>
    <p style={styles.empty}>No asset selected. Select a server-described facility, substation, corridor, generation asset, or load to inspect it.</p>
  </aside>;

  const safeAsset = normalizeInspectorAsset(asset);
  const provenance = safeAsset.provenance ?? [];
  const fields = safeAsset.fields ?? [];
  const relationships = safeAsset.relationships ?? [];
  const caveats = safeAsset.caveats ?? [];
  return <aside className={className} aria-labelledby={descriptionId} style={styles.panel}>
    <header style={styles.header}>
      <div>
        <p style={styles.kicker}>{title}</p>
        <h2 id={descriptionId} style={styles.title}>{safeAsset.name ?? "Identity unavailable"}</h2>
        <p style={styles.identity}>{safeAsset.kind ?? "Asset type unavailable"}{safeAsset.id ? ` · ${safeAsset.id}` : ""}</p>
      </div>
      <span style={styles.badge}>{statusText[safeAsset.status]}</span>
    </header>

    <p style={styles.disclosure}>{safeAsset.message ?? statusExplanation[safeAsset.status]}</p>
    <dl style={styles.summary}>
      <div><dt>Status</dt><dd>{statusText[safeAsset.status]}</dd></div>
      <div><dt>Artifact</dt><dd>{safeAsset.artifactLabel}</dd></div>
      <div><dt>Scenario</dt><dd>{safeAsset.scenario ?? "Unavailable"}</dd></div>
      <div><dt>Readiness</dt><dd>{safeAsset.readiness ?? "Unavailable"}</dd></div>
      <div><dt>Coverage</dt><dd>{safeAsset.coverage ?? "Unavailable"}</dd></div>
    </dl>

    <section aria-label="Fields" style={styles.section}><h3 style={styles.heading}>Fields, units, and uncertainty</h3><FieldList fields={fields} /></section>
    <section aria-label="Provenance" style={styles.section}>
      <h3 style={styles.heading}>Provenance</h3>
      {provenance.length === 0 ? <p style={styles.empty}>Provenance unavailable.</p> : <ul style={styles.cards}>
        {provenance.map((source, index) => <li key={`${source.sourceName}-${index}`} style={styles.card}>
          <strong>{source.sourceName}</strong>
          <span>{source.sourceVersion ?? "Version unavailable"}</span>
          <span>{source.coverage ?? "Coverage unavailable"}</span>
          {source.transformation && <span>Transformation: {source.transformation}</span>}
          {source.sourceRef && <code style={styles.code}>{source.sourceRef}</code>}
          {source.retrievedAt && <span>Retrieved: {source.retrievedAt}</span>}
        </li>)}
      </ul>}
    </section>
    <section aria-label="Related assets" style={styles.section}>
      <h3 style={styles.heading}>Related assets</h3>
      {relationships.length === 0 ? <p style={styles.empty}>No server-asserted relationships are available.</p> : <ul style={styles.relationships}>
        {relationships.map((relationship) => <li key={relationship.id}>
          <button type="button" onClick={() => onSelectRelationship?.(relationship)} style={styles.relationshipButton}>
            <span><strong>{relationship.label}</strong><small>{relationship.relationship}</small></span>
            <span>{relationship.status && isAssetStatus(relationship.status) ? statusText[relationship.status] : "Status unavailable"}</span>
          </button>
        </li>)}
      </ul>}
    </section>
    {caveats.length > 0 && <section aria-label="Caveats" style={styles.section}><h3 style={styles.heading}>Caveats</h3><ul style={styles.caveats}>{caveats.map((caveat) => <li key={caveat}>{caveat}</li>)}</ul></section>}
  </aside>;
}

const styles: Record<string, CSSProperties> = {
  panel: { background: "#0b1d2e", color: "#edf5ff", border: "1px solid #315673", borderRadius: 12, padding: 18, fontFamily: "system-ui, sans-serif", maxWidth: 480 },
  header: { display: "flex", justifyContent: "space-between", gap: 12, alignItems: "start" },
  kicker: { margin: 0, color: "#72d9ff", fontSize: 12, fontWeight: 700, letterSpacing: ".08em", textTransform: "uppercase" },
  title: { margin: "5px 0", fontSize: 22 }, identity: { margin: 0, color: "#9eb5c8", fontSize: 14 },
  badge: { border: "1px solid #72d9ff", borderRadius: 999, color: "#dceeff", padding: "4px 8px", fontSize: 12, whiteSpace: "nowrap" },
  disclosure: { borderLeft: "3px solid #72d9ff", color: "#c9d8e5", lineHeight: 1.45, margin: "16px 0", paddingLeft: 10 },
  summary: { display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 8, margin: "0 0 16px" },
  section: { borderTop: "1px solid #23405a", marginTop: 16, paddingTop: 14 }, heading: { fontSize: 14, margin: "0 0 10px" },
  list: { margin: 0 }, row: { display: "grid", gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1.4fr)", gap: 10, padding: "7px 0", borderTop: "1px solid #183249" },
  term: { color: "#9eb5c8" }, definition: { margin: 0, overflowWrap: "anywhere" }, note: { color: "#9eb5c8", display: "block", marginTop: 3 },
  empty: { color: "#9eb5c8", lineHeight: 1.45 }, cards: { display: "grid", gap: 8, listStyle: "none", margin: 0, padding: 0 },
  card: { background: "#10283b", borderRadius: 8, display: "grid", gap: 3, padding: 10, color: "#c9d8e5", fontSize: 13 }, code: { overflowWrap: "anywhere", color: "#8be2ff" },
  relationships: { display: "grid", gap: 8, listStyle: "none", margin: 0, padding: 0 }, relationshipButton: { width: "100%", alignItems: "center", background: "#10283b", border: "1px solid #315673", borderRadius: 8, color: "inherit", cursor: "pointer", display: "flex", font: "inherit", justifyContent: "space-between", gap: 8, padding: 10, textAlign: "left" },
  caveats: { color: "#c9d8e5", margin: 0, paddingLeft: 20, lineHeight: 1.45 },
};
