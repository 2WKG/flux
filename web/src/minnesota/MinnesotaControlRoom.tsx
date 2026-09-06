import { useRef, useState } from "react";

import type { ClientState } from "../data/client-state";
import { FailureState } from "../failure-states/FailureState";
import { fromClientState } from "../failure-states/adapters";
import type { RunIdentity } from "../ask/run-state/types";
import { MinnesotaVisualHierarchy } from "./MinnesotaVisualHierarchy";
import { requestMinnesotaComparison, type MinnesotaComparisonResponse } from "./comparison-client";
import {
  MINNESOTA_AGGREGATE_ARTIFACT_ID,
  MINNESOTA_AGGREGATE_SCENE_ID,
  MINNESOTA_BASELINE_RUN_CONTEXT,
  MINNESOTA_COMPARISON_CONTEXT_IDS,
  acceptMinnesotaRunResult,
  createMinnesotaRunIdentity,
  minnesotaBookmarkUrl,
  readMinnesotaBookmark,
  resetMinnesotaRunContext,
  type MinnesotaRunContext,
  type MinnesotaRunContextChange,
} from "./run-context";

export interface MinnesotaControlRoomProps {
  /** Injectable for render tests and future route hosts; production reads location.search. */
  readonly search?: string;
  readonly location?: Pick<Location, "pathname" | "hash">;
  readonly onContextChange?: MinnesotaRunContextChange;
}

interface MountedMinnesotaRun {
  readonly context: Readonly<MinnesotaRunContext>;
  readonly identity: Readonly<RunIdentity>;
}

const LATER_INFRASTRUCTURE_CATALOG = Object.freeze([
  { id: "battery_storage", label: "Battery storage" },
  { id: "warehouse_logistics_center", label: "Warehouse logistics center" },
  { id: "school_emergency_services", label: "School emergency services" },
  { id: "ev_charging_station", label: "EV charging station" },
] as const);

const CATALOG_DISCLOSURE = "Illustrative catalogue preview — not Minnesota infrastructure: no accepted Minnesota placement artifact was supplied.";
const CATALOG_PREREQUISITE = "The verified runtime pack installs 96 same-origin files under /assets/flux-grid. A placement still requires a server artifact with provenance, an available mn_artifact_manifests row, inventory permission for point placement, a source_supported or source_screened label when scored, and an EPSG:4326 identity and coordinate inside accepted Minnesota geometry.";

function browserLocation(): Pick<Location, "pathname" | "hash"> {
  return typeof window === "undefined"
    ? { pathname: "/minnesota", hash: "" }
    : window.location;
}

function initialRun(search: string): { readonly parsed: ReturnType<typeof readMinnesotaBookmark>; readonly run: MountedMinnesotaRun } {
  const parsed = readMinnesotaBookmark(search);
  const context = parsed.kind === "valid" ? parsed.bookmark.context : MINNESOTA_BASELINE_RUN_CONTEXT;
  return { parsed, run: { context, identity: createMinnesotaRunIdentity(context) } };
}

/**
 * Aggregate-only Minnesota shell. It deliberately contains no map, line, bus,
 * flow, score, or fabricated fallback: those require a server-returned
 * artifact contract that is not present on this branch.
 */
export function MinnesotaControlRoom({ search, location, onContextChange }: MinnesotaControlRoomProps) {
  const initialSearch = search ?? (typeof window === "undefined" ? "" : window.location.search);
  const [{ parsed, run }, setMounted] = useState(() => initialRun(initialSearch));
  const [bookmarkNotice, setBookmarkNotice] = useState<string | null>(null);
  const [comparison, setComparison] = useState<ClientState<MinnesotaComparisonResponse> | null>(null);
  const [catalogSelection, setCatalogSelection] = useState<(typeof LATER_INFRASTRUCTURE_CATALOG)[number]["id"] | null>(null);
  const currentIdentity = useRef(run.identity);
  currentIdentity.current = run.identity;
  const targetLocation = location ?? browserLocation();

  const reset = () => {
    const context = resetMinnesotaRunContext();
    const identity = createMinnesotaRunIdentity(context);
    const url = minnesotaBookmarkUrl(context, targetLocation);
    if (typeof window !== "undefined") window.history.replaceState(null, "", url);
    setMounted({ parsed: { kind: "valid", bookmark: { version: "v1", context } }, run: { context, identity } });
    setBookmarkNotice("Baseline restored. The URL now names the aggregate baseline.");
    setComparison(null);
    onContextChange?.(context, identity);
  };

  const compareBaseline = async () => {
    const identity = run.identity;
    setComparison({ kind: "loading" });
    const value = await requestMinnesotaComparison({
      baselineContextId: MINNESOTA_COMPARISON_CONTEXT_IDS.baseline,
      candidateContextId: MINNESOTA_COMPARISON_CONTEXT_IDS.candidate,
    });
    const accepted = acceptMinnesotaRunResult(currentIdentity.current, { identity, value });
    if (accepted.kind === "accepted") setComparison(accepted.value);
  };

  const copyBookmark = async () => {
    const url = minnesotaBookmarkUrl(run.context, targetLocation);
    const absolute = typeof window === "undefined" ? url : new URL(url, window.location.origin).toString();
    try {
      if (!navigator.clipboard?.writeText) throw new Error("Clipboard is not available.");
      await navigator.clipboard.writeText(absolute);
      setBookmarkNotice("Versioned aggregate baseline link copied.");
    } catch {
      setBookmarkNotice(`Copy unavailable. Use this link: ${url}`);
    }
  };

  if (parsed.kind === "invalid") {
    return (
      <main className="minnesota-control-room" data-scene-mode="aggregate">
        <FailureState
          state={{ kind: "version_mismatch", code: "mn_bookmark_invalid", message: parsed.message }}
          onReset={reset}
        />
      </main>
    );
  }

  return (
    <main className="minnesota-control-room" data-scene-mode="aggregate" data-run-revision={run.identity.contextRevision}>
      <header>
        <p className="eyebrow">MINNESOTA / AGGREGATE EVIDENCE SHELL</p>
        <h1>Minnesota aggregate baseline</h1>
        <p>
          This view is bounded to accepted aggregate metadata. It has no Minnesota topology, facility geometry,
          allocation, flow, outage, or feature-inspection contract. Comparison facts appear only when the server
          returns persisted aggregate artifacts.
        </p>
      </header>

      <section aria-label="Minnesota run controls">
        <p><strong>Baseline:</strong> aggregate coverage</p>
        <p><strong>Artifact:</strong> <code>{MINNESOTA_AGGREGATE_ARTIFACT_ID}</code></p>
        <p><strong>Scene:</strong> <code>{MINNESOTA_AGGREGATE_SCENE_ID}</code></p>
        <p><strong>Run:</strong> <code>{run.identity.contextRevision}</code></p>
        <p><strong>Comparison contexts:</strong> <code>{MINNESOTA_COMPARISON_CONTEXT_IDS.baseline}</code> → <code>{MINNESOTA_COMPARISON_CONTEXT_IDS.candidate}</code></p>
        <button type="button" onClick={reset}>Reset to baseline</button>
        <button type="button" onClick={copyBookmark}>Copy shareable baseline link</button>
        <button type="button" onClick={compareBaseline} disabled={comparison?.kind === "loading"}>
          {comparison?.kind === "loading" ? "Comparing baseline…" : "Compare baseline"}
        </button>
        {bookmarkNotice ? <p role="status">{bookmarkNotice}</p> : null}
      </section>

      {comparison && (
        <section aria-label="Aggregate comparison" data-comparison-state={comparison.kind}>
          {comparison.kind === "ready" ? <ServerComparison comparison={comparison.data} /> : (
            <FailureState state={fromClientState(comparison)!} onRetry={compareBaseline} onReset={reset} />
          )}
        </section>
      )}

      <MinnesotaVisualHierarchy
        truthStatus="unavailable"
        truthNote="No accepted Minnesota geometry, placement, or feature artifact is supplied for this aggregate surface."
        eyebrow="AGGREGATE EVIDENCE"
        title="Aggregate mode"
        summary="Coverage and provenance remain visible; geographic and feature claims stay unavailable."
      >
      <section aria-label="Aggregate scene">
        <p>
          The accepted manifest supports provenance and coverage display only. MISO balancing-authority values are
          not Minnesota demand and are not allocated to counties or service areas.
        </p>
        <FailureState
          state={{
            kind: "unavailable",
            code: "mn_server_read_contract_missing",
            message: "No server read contract currently supplies a Minnesota aggregate result, geometry, feature inspection, or model output.",
          }}
          onReset={reset}
        />
      </section>
      </MinnesotaVisualHierarchy>

      <section aria-label="Unavailable inspection">
        <h2>Inspect a feature</h2>
        <p>Picking and inspection stay unavailable until a server artifact names a feature and its evidence.</p>
        <button type="button" disabled aria-disabled="true">Inspect feature unavailable</button>
      </section>

      <section aria-label="Later infrastructure catalogue" data-placement-count="0">
        <h2>Later infrastructure catalogue</h2>
        <p>{CATALOG_PREREQUISITE}</p>
        <p role="status">No point or 3D asset is rendered. All four entries are unavailable catalogue previews.</p>
        <ul>
          {LATER_INFRASTRUCTURE_CATALOG.map((asset) => (
            <li key={asset.id}>
              <strong>{asset.label}</strong> <code>{asset.id}</code>
              <button type="button" onClick={() => setCatalogSelection(asset.id)}>Inspect catalogue entry</button>
            </li>
          ))}
        </ul>
        {catalogSelection ? (
          <section aria-label="Unavailable catalogue inspection" data-placement-count="0">
            <h3>{catalogSelection}</h3>
            <p>{CATALOG_DISCLOSURE}</p>
            <p>{CATALOG_PREREQUISITE}</p>
          </section>
        ) : null}
      </section>
    </main>
  );
}

function ServerComparison({ comparison }: { readonly comparison: MinnesotaComparisonResponse }) {
  return (
    <>
      <h2>Server aggregate comparison</h2>
      <p><strong>Comparison:</strong> <code>{comparison.comparison_id}</code></p>
      <p><strong>Baseline:</strong> {comparison.baseline.label} (<code>{comparison.baseline.context_id}</code>)</p>
      <p><strong>Candidate:</strong> {comparison.candidate.label} (<code>{comparison.candidate.context_id}</code>)</p>
      <ul aria-label="Server comparison metrics">
        {comparison.metrics.map((metric) => (
          <li key={metric.metric_id}>
            <h3>{metric.label}</h3>
            <p>Baseline: {metric.baseline_value} {metric.unit}</p>
            <p>Candidate: {metric.candidate_value} {metric.unit}</p>
            <p><strong>Server-signed delta:</strong> {metric.delta_signed} {metric.unit}</p>
            <ul aria-label={`${metric.label} provenance`}>
              {metric.provenance.map((source) => <li key={`${source.artifact_id}:${source.source_id}`}>{source.kind}: {source.source_id} / {source.artifact_id} / {source.version}</li>)}
            </ul>
          </li>
        ))}
      </ul>
      <p><strong>Persisted highlights:</strong></p>
      <ul aria-label="Persisted highlight identifiers">{comparison.highlight_ids.map((id) => <li key={id}><code>{id}</code></li>)}</ul>
      {comparison.limitations.length > 0 ? <><p><strong>Server limitations:</strong></p><ul aria-label="Server limitations">{comparison.limitations.map((limitation) => <li key={limitation}>{limitation}</li>)}</ul></> : null}
    </>
  );
}
