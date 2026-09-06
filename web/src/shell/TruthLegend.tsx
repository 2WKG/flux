import type { AssetStatus } from "../labels";
import { STATUS_COPY } from "../source-truth";

/**
 * The truth-label legend, shared by every page.
 *
 * It renders the display strings `STATUS_COPY` (`src/source-truth.ts`) owns for
 * exactly the tokens the caller's page can assert -- never the whole
 * vocabulary, which would put a claim like "Source-supported" on a page whose
 * data does not support it. The same token therefore reads identically on every
 * page, because both pages render it from the same owner.
 */
export function TruthLegend({ statuses, note }: { statuses: readonly AssetStatus[]; note: string }) {
  return (
    <section className="truth-legend" aria-label="Truth labels on this page">
      <p className="eyebrow">Truth labels on this page</p>
      <ul>
        {statuses.map((status) => (
          <li key={status} data-truth-label={status}>{STATUS_COPY[status]}</li>
        ))}
      </ul>
      <p className="truth-note">{note}</p>
    </section>
  );
}
