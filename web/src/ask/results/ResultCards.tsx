import { useId, useState } from "react";
import type { AskResult, ResultActionHandler, ResultCitation } from "./types";
import { isSupportedResultAction } from "./types";
import "./result-cards.css";

export interface ResultCardsProps {
  results: readonly AskResult[];
  onAction?: ResultActionHandler;
  /** The caller restores the prior scene/filter state using the same opaque action context. */
  onUndoAction?: ResultActionHandler;
}

function citationId(citation: ResultCitation): string {
  return `citation-${citation.doc}-${citation.page}-${citation.chunkId}`.replace(/[^a-zA-Z0-9_-]/g, "-");
}

function CitationList({ citations }: { citations: readonly ResultCitation[] }) {
  if (citations.length === 0) {
    return <p className="ask-result__missing-citations">No citations were returned with this answer.</p>;
  }
  return <ol className="ask-result__citations" aria-label="Returned citations">
    {citations.map((citation) => (
      <li id={citationId(citation)} key={`${citation.doc}:${citation.page}:${citation.chunkId}`}>
        <strong>{citation.title}</strong> · {citation.doc} p.{citation.page}
        {citation.version ? ` · ${citation.version}` : ""}
        {citation.text ? <blockquote>{citation.text}</blockquote> : null}
      </li>
    ))}
  </ol>;
}

function linkedAnswer(answer: string, citations: readonly ResultCitation[]) {
  const token = /\[([^\]]+) p\.(\d+)\]/g;
  const parts: React.ReactNode[] = [];
  let cursor = 0;
  for (const match of answer.matchAll(token)) {
    const index = match.index ?? 0;
    const doc = match[1];
    const page = Number(match[2]);
    const citation = citations.find((item) => item.doc === doc && item.page === page);
    if (!citation) continue;
    parts.push(answer.slice(cursor, index));
    parts.push(<a key={`${index}-${doc}-${page}`} href={`#${citationId(citation)}`}>{match[0]}</a>);
    cursor = index + match[0].length;
  }
  parts.push(answer.slice(cursor));
  return parts;
}

function Status({ result }: { result: AskResult }) {
  const { status } = result;
  const labels: Record<typeof status.availability, string> = {
    source_supported: "Source-supported",
    source_screened: "Source-screened",
    hypothetical: "Hypothetical",
    synthetic: "Synthetic",
    unavailable: "Unavailable",
    request_failed: "Request failed",
  };
  const label = labels[status.availability];
  if (status.empty) return <p className="ask-result__status">Source status: {label}. No matching result was returned.</p>;
  if (status.availability === "unavailable") return <p className="ask-result__status is-unavailable">Source status: unavailable. {status.reason ?? "The source did not provide a result."}</p>;
  if (status.availability === "request_failed") return <p className="ask-result__status is-failed">Source status: request failed. {status.reason ?? "The request failed before an answer was returned."}</p>;
  if (status.verified === true) return <p className="ask-result__status is-verified">Source status: {label}. Verified against returned tools and citations.</p>;
  if (status.verified === false) return <p className="ask-result__status is-unverified">Source status: {label}. Verification reported unresolved evidence.</p>;
  return <p className="ask-result__status">Source status: {label}. Verification status was not supplied.</p>;
}

export function ResultCard({ result, onAction, onUndoAction, titleId }: { result: AskResult; onAction?: ResultActionHandler; onUndoAction?: ResultActionHandler; titleId: string }) {
  const [applied, setApplied] = useState(false);
  const action = result.status.availability === "request_failed" || result.status.availability === "unavailable"
    ? undefined
    : isSupportedResultAction(result.action) ? result.action : undefined;
  const actionUnavailable = result.action?.geometry === "unavailable";
  const actionRejected = result.action !== undefined && !actionUnavailable && !isSupportedResultAction(result.action);
  return <article className="ask-result" aria-labelledby={titleId}>
    <header>
      <p className="ask-result__eyebrow">{result.scope ?? "Ask result"}{result.scenarioId ? ` · ${result.scenarioId}` : ""}</p>
      <h3 id={titleId}>Answer</h3>
      <Status result={result} />
    </header>
    {result.answer ? <p className="ask-result__answer">{linkedAnswer(result.answer, result.citations)}</p> : null}
    {result.limitations.length > 0 ? <section><h4>Limitations</h4><ul>{result.limitations.map((item) => <li key={item}>{item}</li>)}</ul></section> : null}
    {result.provenance.length > 0 ? <section><h4>Source and artifact evidence</h4><ul className="ask-result__provenance">{result.provenance.map((item) => <li key={`${item.artifact_id}:${item.artifact_version}`}>{item.source_kind} · {item.source_ref} · artifact {item.artifact_id} v{item.artifact_version}</li>)}</ul></section> : null}
    <section><h4>Citations</h4><CitationList citations={result.citations} /></section>
    {result.status.unverifiedNumbers?.length ? <p className="ask-result__caveat">Unverified numbers: {result.status.unverifiedNumbers.join(", ")}</p> : null}
    {result.status.unverifiedCitations?.length ? <p className="ask-result__caveat">Unverified citations: {result.status.unverifiedCitations.join(", ")}</p> : null}
    {action && onAction && onUndoAction ? applied
      ? <button type="button" onClick={() => { onUndoAction(action); setApplied(false); }}>Undo {action.label}</button>
      : <button type="button" onClick={() => { onAction(action); setApplied(true); }}>{action.label}{action.geometry === "synthetic" ? " (synthetic geometry)" : ""}</button>
      : null}
    {actionUnavailable ? <p className="ask-result__action-unavailable">Scene action unavailable: the supplied geometry is unavailable.</p> : null}
    {actionRejected ? <p className="ask-result__action-unavailable">Scene action was not applied because its supplied server action is unsupported.</p> : null}
  </article>;
}

export function ResultCards({ results, onAction, onUndoAction }: ResultCardsProps) {
  const instanceId = useId();
  if (results.length === 0) return <p className="ask-result__empty">No answer results are available.</p>;
  return <section className="ask-results" aria-label="Ask results">
    {results.map((result, index) => <ResultCard key={result.id} result={result} onAction={onAction} onUndoAction={onUndoAction} titleId={`${instanceId}-title-${index}`} />)}
  </section>;
}
