import { type ReactNode, useId, useRef, useState } from "react";
import { SOURCE_STATUS_COPY, type SourceStatus, requiresDetail } from "../labels";
import "./app-shell.css";

/**
 * The shell deliberately knows nothing about a geography, model, renderer, or
 * API. Its caller supplies a truthful source label and the bounded content for
 * each panel. That keeps it usable for the current synthetic static demo and
 * for a later, server-backed explorer without relabelling either one.
 */
export type { SourceStatus };

interface ShellSourceLabelBase {
  /** Human-readable disclosure, for example "Synthetic fixture · no live API". */
  label: string;
}

/**
 * The IA requires accompanying copy for `unavailable` (missing prerequisite and
 * a named next step) and for `request_failed` (safe message and request ID), so
 * `detail` is required for exactly those two statuses and optional otherwise.
 */
export type ShellSourceLabel =
  | (ShellSourceLabelBase & {
      /** A server or fixture supplied classification; the shell never derives it. */
      status: Exclude<SourceStatus, "unavailable" | "request_failed">;
      /** Optional source, version, coverage, or caveat supplied by the caller. */
      detail?: string;
    })
  | (ShellSourceLabelBase & {
      status: "unavailable" | "request_failed";
      /** Required: the missing prerequisite and named next step, or the safe message and request ID. */
      detail: string;
    });

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
  // A contract violation, not a display state: rendering "Unavailable" or
  // "Request failed" without the IA's required accompanying copy would show a
  // bare pill with no next step or request ID. Fail loudly instead.
  if (requiresDetail(source.status) && !source.detail?.trim()) {
    throw new Error(`source status "${source.status}" requires a detail: a named next step or request id`);
  }

  return (
    <main className="flux-shell" data-source-status={source.status}>
      <header className="flux-shell__header">
        <div>
          <p className="flux-shell__eyebrow">EXPLORER SHELL</p>
          <h1>{title}</h1>
        </div>
        <div className="flux-shell__source" role="status">
          <span className="flux-shell__source-status">{SOURCE_STATUS_COPY[source.status]}</span>
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
