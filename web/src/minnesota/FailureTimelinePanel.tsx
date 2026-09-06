/**
 * Minnesota failure, flow, and critical-service timeline.
 *
 * This is intentionally a presentation boundary. MN375 owns the active,
 * immutable run context and supplies a typed server response. This component
 * does not fetch, reorder, derive, simulate, or infer topology from either.
 */

export interface MinnesotaRunIdentity {
  readonly runId: string;
  readonly contextRevision: string;
}

/** The immutable context selected by MN375 for the currently visible run. */
export interface MinnesotaRunContext {
  readonly identity: MinnesotaRunIdentity;
  readonly scenarioId: string;
  readonly artifactId: string;
  readonly modelMode: "aggregate" | "topology" | "not_applicable";
}

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
  /** Identity asserted by the server for this response. */
  readonly identity: MinnesotaRunIdentity;
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
      readonly status: "failed";
      readonly message: string;
      readonly requestId?: string;
    });

export interface FailureTimelinePanelProps {
  readonly context: MinnesotaRunContext;
  readonly result: MinnesotaFailureTimelineResult;
}

function sameIdentity(left: MinnesotaRunIdentity, right: MinnesotaRunIdentity): boolean {
  return left.runId === right.runId && left.contextRevision === right.contextRevision;
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

function RunContext({ context }: Pick<FailureTimelinePanelProps, "context">) {
  return (
    <dl aria-label="Timeline run context">
      <div><dt>Run</dt><dd>{context.identity.runId}</dd></div>
      <div><dt>Revision</dt><dd>{context.identity.contextRevision}</dd></div>
      <div><dt>Scenario</dt><dd>{context.scenarioId}</dd></div>
      <div><dt>Artifact</dt><dd>{context.artifactId}</dd></div>
      <div><dt>Model mode</dt><dd>{context.modelMode}</dd></div>
    </dl>
  );
}

function Facts({ facts }: { readonly facts: readonly MinnesotaTimelineFact[] }) {
  if (facts.length === 0) return <p role="status">No timeline facts were returned for this run.</p>;

  return (
    <ol aria-label="Failure, flow, and critical-service facts">
      {facts.map((fact) => (
        <li key={fact.id} data-timeline-fact-kind={fact.kind}>
          <time>{fact.at}</time>
          <strong>{factKindLabel(fact.kind)}</strong>
          <span>{fact.label}</span>
          {fact.detail ? <p>{fact.detail}</p> : null}
        </li>
      ))}
    </ol>
  );
}

function StaleFacts({ context, result, message }: {
  readonly context: MinnesotaRunContext;
  readonly result: Extract<MinnesotaFailureTimelineResult, { status: "ready" | "stale" }>;
  readonly message: string;
}) {
  return (
    <section aria-label="Stale failure timeline" data-timeline-status="stale" role="status">
      <h2>Stale timeline</h2>
      <p>{message}</p>
      <p>These facts belong to run {result.identity.runId} revision {result.identity.contextRevision}; the active run is {context.identity.runId} revision {context.identity.contextRevision}.</p>
      <Facts facts={result.facts} />
    </section>
  );
}

/**
 * Render only the supplied server result for the supplied MN375 context.
 * A mismatched identity is retained as visibly stale rather than being promoted
 * to the active run. No branch creates an inferred network, flow, or service
 * outcome.
 */
export function FailureTimelinePanel({ context, result }: FailureTimelinePanelProps) {
  const identityMatches = sameIdentity(context.identity, result.identity);

  return (
    <section aria-label="Minnesota failure timeline" data-active-run-id={context.identity.runId}>
      <h1>Failure, flow, and critical-service timeline</h1>
      <RunContext context={context} />
      {!identityMatches && (result.status === "ready" || result.status === "stale")
        ? <StaleFacts context={context} result={result} message="The returned timeline does not match the active run and is retained only as stale." />
        : result.status === "ready"
          ? <section aria-label="Current failure timeline" data-timeline-status="ready"><Facts facts={result.facts} /></section>
          : result.status === "stale"
            ? <StaleFacts context={context} result={result} message={result.message} />
            : result.status === "unavailable"
              ? <section aria-label="Unavailable failure timeline" data-timeline-status="unavailable" role="status"><h2>Timeline unavailable</h2><p>{result.message}</p>{result.nextStep ? <p>Next step: {result.nextStep}</p> : null}</section>
              : <section aria-label="Failed failure timeline" data-timeline-status="failed" role="alert"><h2>Timeline request failed</h2><p>{result.message}</p>{result.requestId ? <p>Request ID: {result.requestId}</p> : null}</section>}
    </section>
  );
}
