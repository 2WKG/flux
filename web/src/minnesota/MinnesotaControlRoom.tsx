import { useEffect, useRef, useState } from "react";

import type { ClientState } from "../data/client-state";
import { FailureState } from "../failure-states/FailureState";
import { fromClientState } from "../failure-states/adapters";
import type { RunIdentity } from "../ask/run-state/types";
import {
  requestMinnesotaAggregate,
  type MinnesotaAggregateResponse,
} from "./aggregate-client";
import {
  MINNESOTA_AGGREGATE_ARTIFACT_ID,
  MINNESOTA_AGGREGATE_SCENE_ID,
  MINNESOTA_BASELINE_RUN_CONTEXT,
  createMinnesotaRunIdentity,
  minnesotaBookmarkUrl,
  readMinnesotaBookmark,
  resetMinnesotaRunContext,
  acceptMinnesotaRunResult,
  type MinnesotaRunContext,
  type MinnesotaRunContextChange,
} from "./run-context";

export interface MinnesotaControlRoomProps {
  /** Injectable for render tests and future route hosts; production reads location.search. */
  readonly search?: string;
  readonly location?: Pick<Location, "pathname" | "hash">;
  readonly onContextChange?: MinnesotaRunContextChange;
  /** Injectable for focused UI tests; production always uses the same-origin read route. */
  readonly loadAggregate?: () => Promise<ClientState<MinnesotaAggregateResponse>>;
}

interface MountedMinnesotaRun {
  readonly context: Readonly<MinnesotaRunContext>;
  readonly identity: Readonly<RunIdentity>;
}

/** Runtime-pack catalog identifiers. They are previews only until a placement artifact is accepted. */
const LATER_INFRASTRUCTURE_CATALOG = Object.freeze([
  { id: "battery_storage", label: "Battery storage" },
  { id: "warehouse_logistics_center", label: "Warehouse logistics center" },
  { id: "school_emergency_services", label: "School emergency services" },
  { id: "ev_charging_station", label: "EV charging station" },
] as const);

const CATALOG_UNAVAILABLE = "No accepted Minnesota placement record is available. This preview supplies no point, geometry, facility, or model claim.";

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
 * flow, score, or fabricated fallback. It reads one server-returned aggregate
 * artifact and refuses to use a partial or topology-shaped response.
 */
export function MinnesotaControlRoom({ search, location, onContextChange, loadAggregate = requestMinnesotaAggregate }: MinnesotaControlRoomProps) {
  const initialSearch = search ?? (typeof window === "undefined" ? "" : window.location.search);
  const [{ parsed, run }, setMounted] = useState(() => initialRun(initialSearch));
  const [bookmarkNotice, setBookmarkNotice] = useState<string | null>(null);
  const [aggregate, setAggregate] = useState<ClientState<MinnesotaAggregateResponse>>({ kind: "loading" });
  const [catalogSelection, setCatalogSelection] = useState<(typeof LATER_INFRASTRUCTURE_CATALOG)[number]["id"] | null>(null);
  const currentIdentity = useRef(run.identity);
  currentIdentity.current = run.identity;
  const targetLocation = location ?? browserLocation();

  useEffect(() => {
    const identity = run.identity;
    let mounted = true;
    setAggregate({ kind: "loading" });
    void loadAggregate().then((value) => {
      if (!mounted) return;
      const accepted = acceptMinnesotaRunResult(currentIdentity.current, { identity, value });
      if (accepted.kind === "accepted") setAggregate(accepted.value);
    });
    return () => { mounted = false; };
  }, [loadAggregate, run.identity]);

  const reset = () => {
    const context = resetMinnesotaRunContext();
    const identity = createMinnesotaRunIdentity(context);
    const url = minnesotaBookmarkUrl(context, targetLocation);
    if (typeof window !== "undefined") window.history.replaceState(null, "", url);
    setMounted({ parsed: { kind: "valid", bookmark: { version: "v1", context } }, run: { context, identity } });
    setBookmarkNotice("Baseline restored. The URL now names the aggregate baseline.");
    onContextChange?.(context, identity);
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
          allocation, flow, outage, or scenario-result contract.
        </p>
      </header>

      <section aria-label="Minnesota run controls">
        <p><strong>Baseline:</strong> aggregate coverage</p>
        <p><strong>Artifact:</strong> <code>{MINNESOTA_AGGREGATE_ARTIFACT_ID}</code></p>
        <p><strong>Scene:</strong> <code>{MINNESOTA_AGGREGATE_SCENE_ID}</code></p>
        <p><strong>Run:</strong> <code>{run.identity.contextRevision}</code></p>
        <button type="button" onClick={reset}>Reset to baseline</button>
        <button type="button" onClick={copyBookmark}>Copy shareable baseline link</button>
        <button type="button" onClick={() => {
          const identity = createMinnesotaRunIdentity(run.context);
          setMounted((current) => ({ ...current, run: { ...current.run, identity } }));
        }}>Reload accepted aggregate record</button>
        {bookmarkNotice ? <p role="status">{bookmarkNotice}</p> : null}
      </section>

      <section aria-label="Aggregate scene">
        <h2>Aggregate mode</h2>
        <p>
          The accepted record is read from the same-origin server route. It remains aggregate-only: it does not
          authorize Minnesota topology, facility geometry, allocation, flow, outage, or feature inspection.
        </p>
        {aggregate.kind === "ready" ? <AggregateEvidence result={aggregate.data} identity={run.identity} /> : (
          <FailureState state={fromClientState(aggregate)!} onRetry={() => {
            const identity = createMinnesotaRunIdentity(run.context);
            setMounted((current) => ({ ...current, run: { ...current.run, identity } }));
          }} onReset={reset} />
        )}
      </section>

      <section aria-label="Unavailable inspection">
        <h2>Inspect a feature</h2>
        <p>Picking and inspection stay unavailable until a server artifact names a feature and its evidence.</p>
        <button type="button" disabled aria-disabled="true">Inspect feature unavailable</button>
      </section>

      <section aria-label="Later infrastructure catalog" data-placement-count="0">
        <h2>Later infrastructure catalog</h2>
        <p>{CATALOG_UNAVAILABLE}</p>
        <p role="status">No point or 3D asset is rendered; all entries remain unavailable catalogue previews.</p>
        <ul>
          {LATER_INFRASTRUCTURE_CATALOG.map((asset) => (
            <li key={asset.id}>
              <strong>{asset.label}</strong> <code>{asset.id}</code>
              <button type="button" onClick={() => setCatalogSelection(asset.id)}>Inspect catalog entry</button>
            </li>
          ))}
        </ul>
        {catalogSelection ? (
          <section aria-label="Unavailable catalog inspection" data-placement-count="0">
            <h3><code>{catalogSelection}</code></h3>
            <p>{CATALOG_UNAVAILABLE}</p>
          </section>
        ) : null}
      </section>
    </main>
  );
}

function AggregateEvidence({ result, identity }: { readonly result: MinnesotaAggregateResponse; readonly identity: RunIdentity }) {
  const metric = result.stress_metric;
  return (
    <section aria-label="Accepted aggregate evidence" data-selected-artifact={result.artifact_id}>
      <h3>Persisted aggregate record</h3>
      <p><strong>Run:</strong> <code>{identity.contextRevision}</code></p>
      <p><strong>Artifact:</strong> <code>{result.artifact_id}</code></p>
      <p><strong>Model mode:</strong> {result.model_mode}</p>
      <p><strong>Record format:</strong> {result.aggregate_manifest.format}</p>
      <p><strong>Metric:</strong> {metric.metric_name}: {metric.metric_value} {metric.unit}</p>
      <p><strong>Formula:</strong> {metric.formula}</p>
      <p><strong>Source context:</strong> {metric.source_label}</p>
      <p><strong>Window:</strong> {metric.window_start_utc} to {metric.window_end_utc} ({metric.time_basis})</p>
      <p><strong>Peak:</strong> {metric.window_peak_demand_mw} MW at {metric.window_peak_hour_utc}; {metric.scored_hours} source hours.</p>
      <p><strong>Allocation:</strong> {result.aggregate_manifest.allocation_status}. {result.aggregate_manifest.allocation_limit}</p>
      <h4>Accepted source records</h4>
      <ul aria-label="Accepted aggregate source records">
        {result.aggregate_manifest.sources.map((source) => (
          <li key={source.id}><code>{source.id}</code> — {source.file_sha256
            ? Object.entries(source.file_sha256).map(([file, digest]) => `${file}: ${digest}`).join(", ")
            : "Digest is carried in persisted provenance."}</li>
        ))}
      </ul>
      <h4>Provenance</h4>
      <ul aria-label="Aggregate provenance">
        {result.provenance.map((source) => (
          <li key={`${source.source_name}:${source.content_sha256}`}>
            {source.source_name} ({source.source_version}) — <code>{source.content_sha256}</code>{source.is_derived ? " (derived)" : ""}
          </li>
        ))}
      </ul>
      <h4>Limits</h4>
      <ul aria-label="Aggregate limitations">{result.limitations.map((limit) => <li key={limit}>{limit}</li>)}</ul>
      <h4>Prohibited claims</h4>
      <ul aria-label="Aggregate prohibited claims">{result.prohibited_claims.map((claim) => <li key={claim}>{claim}</li>)}</ul>
    </section>
  );
}
