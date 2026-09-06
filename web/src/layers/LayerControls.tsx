import { useEffect, useId } from "react";
import { isAssetStatus, type AssetStatus } from "../labels";
import "./layer-controls.css";

/**
 * The vocabulary is owned by `../labels.ts` and imported, never restated here.
 * `SourceStatus` is this component's local name for that same union.
 */
export type SourceStatus = AssetStatus;
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
  /**
   * A parent must provide this to permit a visibility request. `unavailable` and
   * `request_failed` carry no evidence of their own, so the producer's named reason
   * is the only channel this component has: it is required, never substituted.
   */
  readonly visibility: { readonly enabled: true } | { readonly enabled: false; readonly reason: string };
}

export interface LayerControlsProps {
  readonly layers: readonly LayerDescriptor[];
  readonly visibleLayerIds: readonly string[];
  readonly onVisibleLayerIdsChange: (ids: readonly string[]) => void;
  readonly heading?: string;
}

/**
 * The IA's user-visible copy, `docs/design/minnesota-demo-narrative-ia.md:224-231`, quoted
 * exactly. `src/source-truth.ts`'s `STATUS_COPY` currently carries the unhyphenated
 * variants ("Source supported"); unifying the two display maps is a call for the owner of
 * that module, and this panel must not repeat copy the IA table does not use.
 */
const statusCopy: Record<SourceStatus, string> = {
  source_supported: "Source-supported",
  source_screened: "Source-screened",
  hypothetical: "Hypothetical",
  synthetic: "Synthetic",
  unavailable: "Unavailable",
  request_failed: "Request failed",
};

/**
 * Accompanying copy the IA binds to the label itself rather than to a producer field.
 * Statuses whose required copy is producer-supplied (`unavailable`'s named next step,
 * `request_failed`'s retry guidance) are absent here on purpose: this component refuses
 * instead of inventing them.
 */
const statusNote: Partial<Record<SourceStatus, string>> = {
  hypothetical: "Not a recommendation.",
};

const categoryCopy: Record<LayerCategory, string> = {
  topology: "Topology",
  facilities: "Facilities",
  flows: "Flows",
  events: "Events",
  proposals: "Proposals",
  provenance: "Provenance",
};

const evidenceClassCopy: Record<EvidenceClass, string> = {
  observed: "Observed",
  proxy: "Proxy",
  modeled: "Modeled",
  fixture: "Fixture",
  stale: "Stale",
  malformed: "Malformed",
  unavailable: "Unavailable",
};

/**
 * A refusal this component owns, named by token. It is never presented as a reason the
 * producer gave; the browser has no reason of its own to offer.
 */
export type RefusalCode =
  | "unrecognized_status"
  | "unrecognized_descriptor"
  | "malformed_evidence"
  | "missing_status_reason";

const refusalCopy: Record<RefusalCode, string> = {
  unrecognized_status: "Refused: the supplied source-truth status is not one this vocabulary defines.",
  unrecognized_descriptor: "Refused: the supplied category or evidence class is not one this vocabulary defines.",
  malformed_evidence: "Refused: the evidence disclosure is incomplete or malformed.",
  missing_status_reason: "Refused: no reason was supplied for this status.",
};

/** The statuses that assert a five-field disclosure. `unavailable`/`request_failed` have none to give. */
const STATUSES_ASSERTING_EVIDENCE: readonly SourceStatus[] = [
  "source_supported",
  "source_screened",
  "hypothetical",
  "synthetic",
];

function isLayerCategory(value: unknown): value is LayerCategory {
  return typeof value === "string" && Object.prototype.hasOwnProperty.call(categoryCopy, value);
}

function isEvidenceClass(value: unknown): value is EvidenceClass {
  return typeof value === "string" && Object.prototype.hasOwnProperty.call(evidenceClassCopy, value);
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

export type ResolvedLayer = {
  status: SourceStatus;
  /** Producer-supplied text only. Never written by this component. */
  reason: string | null;
  refusal: RefusalCode | null;
  evidence: LayerEvidence | null;
};

export function resolveLayer(layer: LayerDescriptor): ResolvedLayer {
  if (!isAssetStatus(layer.sourceStatus)) {
    return { status: "unavailable", reason: null, refusal: "unrecognized_status", evidence: null };
  }
  const status: SourceStatus = layer.sourceStatus;
  if (!isLayerCategory(layer.category) || !isEvidenceClass(layer.evidenceClass)) {
    return { status: "unavailable", reason: null, refusal: "unrecognized_descriptor", evidence: null };
  }
  const evidence = evidenceOf(layer.evidence);
  if (STATUSES_ASSERTING_EVIDENCE.includes(status) && evidence === null) {
    return { status: "unavailable", reason: null, refusal: "malformed_evidence", evidence: null };
  }
  if (!layer.visibility.enabled) return { status, reason: layer.visibility.reason, refusal: null, evidence };
  // `unavailable` and `request_failed` keep their own token: a failed request is not the
  // same claim as a missing artifact, and neither is rewritten into the other.
  if (status === "unavailable" || status === "request_failed") {
    return { status, reason: null, refusal: "missing_status_reason", evidence };
  }
  return { status, reason: null, refusal: null, evidence };
}

/** A layer is blocked when it carries a producer reason or a refusal of ours. */
export function isBlocked(resolved: ResolvedLayer): boolean {
  return resolved.reason !== null || resolved.refusal !== null;
}

/**
 * The list the parent should hold after a toggle, or `null` when the layer is blocked and
 * no request may be made at all.
 */
export function nextVisibleLayerIds(
  layers: readonly LayerDescriptor[],
  visibleLayerIds: readonly string[],
  layer: LayerDescriptor,
  nextVisible: boolean,
): readonly string[] | null {
  if (isBlocked(resolveLayer(layer))) return null;
  const next = new Set(visibleLayerIds);
  if (nextVisible) next.add(layer.id);
  else next.delete(layer.id);
  return layers.filter((item) => next.has(item.id)).map((item) => item.id);
}

/**
 * The visible list with every blocked layer removed. A layer that flips to unavailable on
 * a refresh must leave the parent's list, not merely grey out.
 */
export function prunedVisibleLayerIds(
  layers: readonly LayerDescriptor[],
  visibleLayerIds: readonly string[],
): readonly string[] {
  const visible = new Set(visibleLayerIds);
  return layers.filter((item) => visible.has(item.id) && !isBlocked(resolveLayer(item))).map((item) => item.id);
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

  const pruned = prunedVisibleLayerIds(layers, visibleLayerIds);
  const prunedKey = pruned.join(" ");
  useEffect(() => {
    if (pruned.length !== visibleLayerIds.length) onVisibleLayerIdsChange(pruned);
    // Keyed on the pruned list itself so the retraction runs once per change, not per render.
  }, [prunedKey, visibleLayerIds.length]);

  const requestVisibility = (layer: LayerDescriptor, nextVisible: boolean) => {
    const next = nextVisibleLayerIds(layers, visibleLayerIds, layer, nextVisible);
    if (next === null) return;
    onVisibleLayerIdsChange(next);
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
          const disabled = isBlocked(resolved);
          const checked = visible.has(layer.id) && !disabled;
          const note = statusNote[resolved.status];
          return (
            <li className="layer-row" key={layer.id} data-status={resolved.status} data-refusal={resolved.refusal ?? undefined}>
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
                <span className="layer-category">{isLayerCategory(layer.category) ? categoryCopy[layer.category] : "Unrecognized category"}</span>
                <span className="layer-status">{statusCopy[resolved.status]}</span>
                <span className="layer-evidence-class">{isEvidenceClass(layer.evidenceClass) ? evidenceClassCopy[layer.evidenceClass] : "Unrecognized evidence class"}</span>
              </div>
              {note && <p className="layer-note">{note}</p>}
              {resolved.reason && <p className="layer-reason" role="note">{resolved.reason}</p>}
              {resolved.refusal && <p className="layer-refusal" role="note">{refusalCopy[resolved.refusal]}</p>}
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
