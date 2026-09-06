import { type ReactNode, useId, useRef, useState } from "react";
import "./app-shell.css";

/**
 * The shell deliberately knows nothing about a geography, model, renderer, or
 * API. Its caller supplies a truthful source label and the bounded content for
 * each panel. That keeps it usable for the current synthetic static demo and
 * for a later, server-backed explorer without relabelling either one.
 */
/** Frozen UI statuses; only the supplied artifact or server result may select one. */
export type SourceStatus =
  | "source_supported"
  | "source_screened"
  | "hypothetical"
  | "synthetic"
  | "unavailable"
  | "request_failed";

export interface ShellSourceLabel {
  /** A server or fixture supplied classification; the shell never derives it. */
  status: SourceStatus;
  /** Human-readable disclosure, for example "Synthetic fixture · no live API". */
  label: string;
  /** Optional source, version, coverage, or caveat supplied by the caller. */
  detail?: string;
}

export interface ShellSlots {
  /** The primary scene, map, static diagram, or explicit unavailable view. */
  viewport: ReactNode;
  /** Layer, navigation, and scene controls. */
  controls?: ReactNode;
  /** The selected facility/corridor detail. */
  inspector?: ReactNode;
  /** Timeline or other temporal controls. */
  timeline?: ReactNode;
  /** Baseline/candidate comparison content. */
  comparison?: ReactNode;
  /** Agent conversation and editable context. */
  chat?: ReactNode;
}

export interface AppShellProps extends ShellSlots {
  source: ShellSourceLabel;
  title?: string;
}

type CollapsiblePanelProps = {
  className: string;
  heading: string;
  children: ReactNode;
  defaultOpen?: boolean;
};

function CollapsiblePanel({ className, heading, children, defaultOpen = true }: CollapsiblePanelProps) {
  const [open, setOpen] = useState(defaultOpen);
  const contentId = useId();
  const disclosure = useRef<HTMLButtonElement>(null);

  const closeAndRestoreFocus = () => {
    setOpen(false);
    requestAnimationFrame(() => disclosure.current?.focus());
  };

  return (
    <section
      className={`${className}${open ? "" : " flux-shell__panel--collapsed"}`}
      aria-label={heading}
      onKeyDown={(event) => {
        if (event.key !== "Escape" || !open) return;
        event.preventDefault();
        event.stopPropagation();
        closeAndRestoreFocus();
      }}
    >
      <div className="flux-shell__panel-heading">
        <h2>{heading}</h2>
        <button
          type="button"
          ref={disclosure}
          className="flux-shell__collapse"
          aria-expanded={open}
          aria-controls={contentId}
          onClick={() => setOpen((value) => !value)}
        >
          {open ? "Collapse" : "Expand"}
        </button>
      </div>
      <div id={contentId} className="flux-shell__panel-content" hidden={!open}>
        {children}
      </div>
    </section>
  );
}

function sourceStatusCopy(status: SourceStatus): string {
  return {
    source_supported: "Source supported",
    source_screened: "Source screened",
    hypothetical: "Hypothetical",
    synthetic: "Synthetic",
    unavailable: "Unavailable",
    request_failed: "Request failed",
  }[status];
}

/** A keyboard-operable, responsive composition boundary for the future explorer. */
export function AppShell({
  source,
  title = "Grid explorer",
  viewport,
  controls,
  inspector,
  timeline,
  comparison,
  chat,
}: AppShellProps) {
  return (
    <main className="flux-shell" data-source-status={source.status}>
      <header className="flux-shell__header">
        <div>
          <p className="flux-shell__eyebrow">EXPLORER SHELL</p>
          <h1>{title}</h1>
        </div>
        <div className="flux-shell__source" role="status" aria-label={`Data status: ${source.label}`}>
          <span className="flux-shell__source-status">{sourceStatusCopy(source.status)}</span>
          <span>{source.label}</span>
          {source.detail && <small>{source.detail}</small>}
        </div>
      </header>

      <section className="flux-shell__grid" aria-label="Explorer workspace">
        <section className="flux-shell__viewport" aria-label="Primary viewport">
          <div className="flux-shell__viewport-content">{viewport}</div>
          {controls && <div className="flux-shell__controls" aria-label="Scene controls">{controls}</div>}
        </section>

        {inspector !== undefined && <CollapsiblePanel className="flux-shell__inspector" heading="Inspector">{inspector}</CollapsiblePanel>}
        {timeline !== undefined && <CollapsiblePanel className="flux-shell__timeline" heading="Timeline" defaultOpen={false}>{timeline}</CollapsiblePanel>}
        {comparison !== undefined && <CollapsiblePanel className="flux-shell__comparison" heading="Comparison">{comparison}</CollapsiblePanel>}
        {chat !== undefined && <CollapsiblePanel className="flux-shell__chat" heading="Ask" defaultOpen={false}>{chat}</CollapsiblePanel>}
      </section>
    </main>
  );
}
