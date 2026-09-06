import type { ReactNode } from "react";

import type { AssetStatus } from "../labels";
import { STATUS_COPY } from "../source-truth";
import "./MinnesotaVisualHierarchy.css";

export interface MinnesotaVisualHierarchyProps {
  /** The caller supplies only a status that its delivered artifact asserts. */
  readonly truthStatus: AssetStatus;
  /** Names the evidence boundary for this particular mounted surface. */
  readonly truthNote: string;
  readonly eyebrow: string;
  readonly title: string;
  readonly summary: string;
  readonly children: ReactNode;
  readonly className?: string;
}

/**
 * A Minnesota-local presentation frame for evidence-backed content.
 *
 * This component owns hierarchy, surface treatment, and motion preference
 * handling only. It accepts its truth token from the host and renders no map,
 * topology, facility, metric, or result of its own.
 */
export function MinnesotaVisualHierarchy({
  truthStatus,
  truthNote,
  eyebrow,
  title,
  summary,
  children,
  className,
}: MinnesotaVisualHierarchyProps) {
  const classes = ["mn-visual-hierarchy", className].filter(Boolean).join(" ");

  return (
    <section className={classes} aria-label={title} data-mn-visual-hierarchy="true">
      <header className="mn-visual-hierarchy__header">
        <div>
          <p className="mn-visual-hierarchy__eyebrow">{eyebrow}</p>
          <h2>{title}</h2>
          <p className="mn-visual-hierarchy__summary">{summary}</p>
        </div>
        <span className="mn-visual-hierarchy__truth" data-truth-label={truthStatus}>
          {STATUS_COPY[truthStatus]}
        </span>
      </header>
      <p className="mn-visual-hierarchy__truth-note">{truthNote}</p>
      <div className="mn-visual-hierarchy__content">{children}</div>
    </section>
  );
}
