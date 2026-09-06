import { useId } from "react";
import "./layer-controls.css";

/** Values frozen for source-truth UI. Unknown input fails closed as unavailable. */
export const SOURCE_STATUSES = [
  "source_supported",
  "source_screened",
  "hypothetical",
  "synthetic",
  "unavailable",
  "request_failed",
] as const;

export type SourceStatus = (typeof SOURCE_STATUSES)[number];
export type LayerCategory = "topology" | "facilities" | "flows" | "events" | "proposals" | "provenance";
export type EvidenceClass = "observed" | "proxy" | "modeled" | "fixture" | "stale" | "malformed" | "unavailable";

export interface LayerEvidence {
  readonly source: string;
  readonly vintage: string;
  readonly coverage: string;
  readonly transformation: string;
  readonly uncertainty: string;
  readonly syntheticTopologyCaveat?: string;
}

/**
 * A parent-owned declaration of one server or fixture layer. Visibility is only a
 * request: this component never claims that a scene accepted or rendered it.
 */
export interface LayerDescriptor {
  readonly id: string;
  readonly label: string;
  readonly category: LayerCategory;
  readonly sourceStatus: unknown;
  readonly evidenceClass: EvidenceClass;
  readonly evidence?: LayerEvidence;
  /** A parent must provide this to permit a visibility request. */
  readonly visibility: { readonly enabled: true } | { readonly enabled: false; readonly reason: string };
}

export interface LayerControlsProps {
  readonly layers: readonly LayerDescriptor[];
  readonly visibleLayerIds: readonly string[];
  readonly onVisibleLayerIdsChange: (ids: readonly string[]) => void;
  readonly heading?: string;
}

const statusCopy: Record<SourceStatus, string> = {
  source_supported: "Source supported",
  source_screened: "Source screened",
  hypothetical: "Hypothetical",
  synthetic: "Synthetic",
  unavailable: "Unavailable",
  request_failed: "Request failed",
};

/** Visible marks keep a status recognizable when colour is unavailable. */
const statusGlyph: Record<SourceStatus, string> = {
  source_supported: "✓",
  source_screened: "≈",
  hypothetical: "?",
  synthetic: "◇",
  unavailable: "×",
  request_failed: "!",
};

const categoryCopy: Record<LayerCategory, string> = {
  topology: "Topology",
  facilities: "Facilities",
  flows: "Flows",
  events: "Events",
  proposals: "Proposals",
  provenance: "Provenance",
};

export function sourceStatusOf(value: unknown): SourceStatus | null {
  return typeof value === "string" && (SOURCE_STATUSES as readonly string[]).includes(value) ? value as SourceStatus : null;
}

function evidenceOf(value: unknown): LayerEvidence | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return null;
  const candidate = value as Record<string, unknown>;
  const required = ["source", "vintage", "coverage", "transformation", "uncertainty"] as const;
  if (required.some((key) => typeof candidate[key] !== "string" || candidate[key].trim() === "")) return null;
  if (candidate.syntheticTopologyCaveat !== undefined &&
    (typeof candidate.syntheticTopologyCaveat !== "string" || candidate.syntheticTopologyCaveat.trim() === "")) return null;
  return candidate as unknown as LayerEvidence;
}

type ResolvedLayer = { status: SourceStatus; reason: string | null; evidence: LayerEvidence | null };

export function resolveLayer(layer: LayerDescriptor): ResolvedLayer {
  const status = sourceStatusOf(layer.sourceStatus);
  if (status === null) return { status: "unavailable", reason: "This layer has no recognized source-truth status and is unavailable.", evidence: null };
  const evidence = evidenceOf(layer.evidence);
  if (evidence === null) return { status: "unavailable", reason: "This layer has incomplete or malformed evidence disclosure and is unavailable.", evidence: null };
  if (!layer.visibility.enabled) return { status, reason: layer.visibility.reason, evidence };
  if (status === "unavailable" || status === "request_failed") {
    return { status, reason: "This layer is not available for display.", evidence };
  }
  return { status, reason: null, evidence };
}

function EvidenceDisclosure({ evidence }: { evidence: LayerEvidence }) {
  return (
    <dl className="layer-evidence">
      <div><dt>Source</dt><dd>{evidence.source}</dd></div>
      <div><dt>Vintage</dt><dd>{evidence.vintage}</dd></div>
      <div><dt>Coverage</dt><dd>{evidence.coverage}</dd></div>
      <div><dt>Transformation</dt><dd>{evidence.transformation}</dd></div>
      <div><dt>Uncertainty</dt><dd>{evidence.uncertainty}</dd></div>
      {evidence.syntheticTopologyCaveat && <div><dt>Topology caveat</dt><dd>{evidence.syntheticTopologyCaveat}</dd></div>}
    </dl>
  );
}

/** A controlled legend and visibility-request panel. It neither filters data nor renders a scene. */
export function LayerControls({ layers, visibleLayerIds, onVisibleLayerIdsChange, heading = "Layers and evidence" }: LayerControlsProps) {
  const panelId = useId();
  const visible = new Set(visibleLayerIds);

  const requestVisibility = (layer: LayerDescriptor, nextVisible: boolean) => {
    const resolved = resolveLayer(layer);
    if (resolved.reason) return;
    const next = new Set(visible);
    if (nextVisible) next.add(layer.id);
    else next.delete(layer.id);
    onVisibleLayerIdsChange(layers.filter((item) => next.has(item.id)).map((item) => item.id));
  };

  return (
    <section className="layer-controls" aria-labelledby={panelId}>
      <header>
        <h2 id={panelId}>{heading}</h2>
        <p>Visibility is a request to the parent scene. Status and uncertainty remain visible when layers are filtered.</p>
      </header>
      <ul className="layer-list" aria-label="Layer visibility and evidence">
        {layers.map((layer) => {
          const resolved = resolveLayer(layer);
          const disabled = resolved.reason !== null;
          const checked = visible.has(layer.id);
          return (
            <li className="layer-row" key={layer.id} data-status={resolved.status}>
              <div className="layer-main">
                <label>
                  <input
                    type="checkbox"
                    checked={checked}
                    disabled={disabled}
                    onChange={(event) => requestVisibility(layer, event.currentTarget.checked)}
                  />
                  <span>{layer.label}</span>
                </label>
                <span className="layer-category">{categoryCopy[layer.category]}</span>
                <span className="layer-status"><span className="layer-status-glyph" aria-hidden="true">{statusGlyph[resolved.status]}</span>{statusCopy[resolved.status]}</span>
                <span className="layer-evidence-class">{layer.evidenceClass}</span>
              </div>
              {resolved.reason && <p className="layer-reason" role="note">{resolved.reason}</p>}
              {resolved.evidence && <details className="layer-details">
                <summary>Source, vintage, coverage and uncertainty</summary>
                <EvidenceDisclosure evidence={resolved.evidence} />
              </details>}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
