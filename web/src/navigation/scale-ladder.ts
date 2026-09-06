/** The statewide-to-facility scale ladder and its stable reset target.
 *
 * This is a pure navigation *model*: it names the ordered set of scales a
 * viewport can sit at and the deterministic step between adjacent scales. It
 * renders nothing and reads no server artifact; per `docs/specs/00-overview.md`
 * the browser/server boundary and Gate 0
 * (`docs/design/minnesota-gate-0-approval.md`) are a renderer's concern, not
 * this module's. Nothing here invents a coordinate, a label, or a count --
 * see `search.ts` and `breadcrumbs.ts` for where real data enters the model.
 */

/** Widest to narrowest. A later scale is always a specialization of the one before it. */
export const SCALE_LADDER = ["statewide", "region", "facility"] as const;

export type Scale = (typeof SCALE_LADDER)[number];

/** The named, stable target for "return to a known statewide view." Never changes. */
export const RESET_SCALE: Scale = SCALE_LADDER[0];

export function isScale(value: unknown): value is Scale {
  return typeof value === "string" && (SCALE_LADDER as readonly string[]).includes(value);
}

export function scaleIndex(scale: Scale): number {
  return SCALE_LADDER.indexOf(scale);
}

/** The next scale out (wider), or null when already at the reset scale. */
export function parentScale(scale: Scale): Scale | null {
  const index = scaleIndex(scale);
  return index > 0 ? SCALE_LADDER[index - 1] : null;
}

/** The next scale in (narrower), or null when already at the narrowest scale. */
export function childScale(scale: Scale): Scale | null {
  const index = scaleIndex(scale);
  return index >= 0 && index < SCALE_LADDER.length - 1 ? SCALE_LADDER[index + 1] : null;
}

/** Step one level narrower. Clamps at the narrowest scale rather than wrapping. */
export function zoomInScale(scale: Scale): Scale {
  return childScale(scale) ?? scale;
}

/** Step one level wider. Clamps at `RESET_SCALE` rather than wrapping. */
export function zoomOutScale(scale: Scale): Scale {
  return parentScale(scale) ?? scale;
}

export function isNarrowerThan(a: Scale, b: Scale): boolean {
  return scaleIndex(a) > scaleIndex(b);
}
