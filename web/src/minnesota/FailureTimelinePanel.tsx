/**
 * Minnesota failure, flow, and critical-service timeline.
 *
 * This is intentionally a presentation boundary. `./run-context` owns the
 * active, immutable run context and the two-part `RunIdentity`; a server
 * supplies the result. This component does not fetch, reorder, derive,
 * simulate, or infer topology from either.
 *
 * Two axes are kept apart on purpose. *Freshness* (`data-timeline-freshness`)
 * says whether the facts on screen belong to the active run. *Outcome*
 * (`data-request-status`) is the Gate-0 frozen vocabulary
 * (`docs/design/minnesota-gate-0-approval.md` §3, owned by `src/labels.ts`),
 * and this surface may only emit the two request-outcome tokens of it. The
 * headings for those come from `STATUS_COPY`, the one owner of the six display
 * strings, rather than being hand-spelled here.
 */
import type { RunIdentity } from "../ask/run-state/types";
import type { FailureStatus } from "../failure-states/types";
import { STATUS_COPY } from "../source-truth";
import { isCurrentMinnesotaRun, type MinnesotaRunContext } from "./run-context";

/** The frozen request-outcome tokens; `FailureStatus` is the Gate-0 subset. */
export type MinnesotaTimelineOutcome = FailureStatus;

/** Whether the rendered facts belong to the active run. Not a status token. */
export type MinnesotaTimelineFreshness = "current" | "stale";

export type MinnesotaTimelineFactKind = "failure" | "flow" | "critical_service";

/** A server-ordered, display-ready fact. `at`, `label`, and `detail` are never computed here. */
export interface MinnesotaTimelineFact {
  readonly id: string;
  readonly at: string;
  readonly kind: MinnesotaTimelineFactKind;
  readonly label: string;
  readonly detail?: string;
}

interface TimelineResponseBase {
  /** Identity asserted by the server for this response, in the shell's own shape. */
  readonly identity: Readonly<RunIdentity>;
}

export type MinnesotaFailureTimelineResult =
  | (TimelineResponseBase & {
      readonly status: "ready";
      /** Already ordered by the server; order is significant and preserved. */
      readonly facts: readonly MinnesotaTimelineFact[];
    })
  | (TimelineResponseBase & {
      readonly status: "stale";
      /** Retained, previously returned facts. They are never described as current. */
      readonly facts: readonly MinnesotaTimelineFact[];
      readonly message: string;
    })
  | (TimelineResponseBase & {
      readonly status: "unavailable";
      readonly message: string;
      readonly nextStep?: string;
    })
  | (TimelineResponseBase & {
      readonly status: "request_failed";
      readonly message: string;
      readonly requestId?: string;
    });

export interface FailureTimelinePanelProps {
  /** The immutable aggregate context the shell has made current. */
  readonly context: Readonly<MinnesotaRunContext>;
  /** The active run's two-part identity, from `createMinnesotaRunIdentity`. */
  readonly identity: Readonly<RunIdentity>;
  readonly result: MinnesotaFailureTimelineResult;
}

function factKindLabel(kind: MinnesotaTimelineFactKind): string {
  switch (kind) {
    case "failure":
      return "Failure";
    case "flow":
      return "Flow";
    case "critical_service":
      return "Critical service";
  }
}

function RunContext({ context, identity }: Pick<FailureTimelinePanelProps, "context" | "identity">) {
  return (
    <dl aria-label="Timeline run context">
      <div><dt>Run</dt><dd>{identity.attemptId}</dd></div>
      <div><dt>Revision</dt><dd>{identity.contextRevision}</dd></div>
      <div><dt>Scene</dt><dd>{context.sceneId}</dd></div>
      <div><dt>Artifact</dt><dd>{context.artifactId}</dd></div>
      <div><dt>Model mode</dt><dd>{context.mode}</dd></div>
    </dl>
  );
}

function Facts({ facts }: { readonly facts: readonly MinnesotaTimelineFact[] }) {
  if (facts.length === 0) return <p role="status">No timeline facts were returned for this run.</p>;

  // `facts.map` over the array exactly as supplied: no sort, no dedupe, no
  // gap-fill, no synthesized timestamp. The server's order is the order.
  return (
    <ol aria-label="Failure, flow, and critical-service facts">
      {facts.map((fact) => (
        <li key={fact.id} data-timeline-fact-kind={fact.kind} data-timeline-fact-id={fact.id}>
          <time>{fact.at}</time>
          <strong>{factKindLabel(fact.kind)}</strong>
          <span>{fact.label}</span>
          {fact.detail ? <p>{fact.detail}</p> : null}
        </li>
      ))}
    </ol>
  );
}

function StaleFacts({ identity, result, messages }: {
  readonly identity: Readonly<RunIdentity>;
  readonly result: Extract<MinnesotaFailureTimelineResult, { status: "ready" | "stale" }>;
  readonly messages: readonly string[];
}) {
  return (
    <section aria-label="Stale failure timeline" data-timeline-freshness="stale" role="status">
      <h2>Stale timeline</h2>
      {messages.map((message) => <p key={message}>{message}</p>)}
      <p>These facts belong to run {result.identity.attemptId} revision {result.identity.contextRevision}; the active run is {identity.attemptId} revision {identity.contextRevision}.</p>
      <Facts facts={result.facts} />
    </section>
  );
}

const MISMATCH = "The returned timeline does not match the active run and is retained only as stale.";

function Outcome({ status, message, extra }: {
  readonly status: MinnesotaTimelineOutcome;
  readonly message: string;
  readonly extra?: string;
}) {
  return (
    <section
      aria-label={status === "unavailable" ? "Unavailable failure timeline" : "Failed failure timeline"}
      data-request-status={status}
      role={status === "unavailable" ? "status" : "alert"}
    >
      {/* The one owner of the six display strings; never re-spelled here. */}
      <h2>{STATUS_COPY[status]}</h2>
      <p>{message}</p>
      {extra ? <p>{extra}</p> : null}
    </section>
  );
}

/**
 * Render only the supplied server result for the supplied run. A mismatched
 * identity is retained as visibly stale rather than being promoted to the
 * active run. No branch creates an inferred network, flow, or service outcome.
 */
export function FailureTimelinePanel({ context, identity, result }: FailureTimelinePanelProps) {
  const identityMatches = isCurrentMinnesotaRun(identity, result.identity);

  return (
    <section aria-label="Minnesota failure timeline" data-active-run-id={identity.attemptId}>
      <h1>Failure, flow, and critical-service timeline</h1>
      <RunContext context={context} identity={identity} />
      {!identityMatches && (result.status === "ready" || result.status === "stale")
        ? (
          <StaleFacts
            identity={identity}
            result={result}
            // The server's own stale message is kept alongside the mismatch
            // sentence rather than being replaced by it.
            messages={result.status === "stale" ? [MISMATCH, result.message] : [MISMATCH]}
          />
        )
        : result.status === "ready"
          ? (
            <section aria-label="Current failure timeline" data-timeline-freshness="current">
              <Facts facts={result.facts} />
            </section>
          )
          : result.status === "stale"
            ? <StaleFacts identity={identity} result={result} messages={[result.message]} />
            : result.status === "unavailable"
              ? <Outcome status="unavailable" message={result.message} extra={result.nextStep ? `Next step: ${result.nextStep}` : undefined} />
              : <Outcome status="request_failed" message={result.message} extra={result.requestId ? `Request ID: ${result.requestId}` : undefined} />}
    </section>
  );
}
