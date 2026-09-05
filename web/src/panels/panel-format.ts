/**
 * Render helpers shared by the artifact panels.
 *
 * Tool numbers come from the wire.  A value that is not a finite number is
 * rendered as the explicit word "unavailable" so a panel can never show a
 * plausible default (blank, 0, NaN) in place of missing data.
 */

export const UNAVAILABLE_LABEL = "unavailable";

export function formatMetric(value: unknown, unit?: string): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return UNAVAILABLE_LABEL;
  return unit ? `${value} ${unit}` : String(value);
}

export function formatCount(value: unknown): string {
  return Array.isArray(value) ? String(value.length) : UNAVAILABLE_LABEL;
}
