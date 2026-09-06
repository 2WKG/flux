import { useState } from "react";

import { FailureState } from "../failure-states/FailureState";
import type { RunIdentity } from "../ask/run-state/types";
import {
  MINNESOTA_AGGREGATE_ARTIFACT_ID,
  MINNESOTA_AGGREGATE_SCENE_ID,
  MINNESOTA_BASELINE_RUN_CONTEXT,
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
  const targetLocation = location ?? browserLocation();

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
        {bookmarkNotice ? <p role="status">{bookmarkNotice}</p> : null}
      </section>

      <section aria-label="Aggregate scene">
        <h2>Aggregate mode</h2>
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

      <section aria-label="Unavailable inspection">
        <h2>Inspect a feature</h2>
        <p>Picking and inspection stay unavailable until a server artifact names a feature and its evidence.</p>
        <button type="button" disabled aria-disabled="true">Inspect feature unavailable</button>
      </section>
    </main>
  );
}
