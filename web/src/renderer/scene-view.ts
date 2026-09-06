/** The renderer's own input vocabulary, and the pure transform that produces it.
 *
 * The renderer must not switch on the adapter's discriminants directly. The
 * adapter vocabulary is migrating: `web/src/scene/minnesota-adapter.ts` on
 * `master` returns `topology_scene` / `aggregate_zones` with per-node
 * `truthLabel`, while the server-bound adapter on
 * `joshuawangia/2wkg-367-adapter-server-bound` (PR #210) returns
 * `bound_placement` / `aggregate_coverage` with a `statusLabel` drawn from the
 * six shared status tokens. A renderer written against either set stops
 * type-checking when the other lands. This module is the single seam that
 * reads an adaptation structurally, so the renderer above it compiles against
 * both.
 *
 * The six tokens are the `MAT_STATUS` slot vocabulary from
 * `data/3d/asset-archetypes-v1.json` (`statusMaterials.allowedLabels`), which
 * `docs/design/minnesota-demo-narrative-ia.md` requires the map surface to
 * carry as a primary state label. Nothing here invents a label: an adaptation
 * that carries no recognised token becomes `unavailable`, never a guess.
 */

/** The shared status vocabulary. Order is the file's; membership is what matters. */
export const STATUS_LABELS = [
  "source_supported",
  "source_screened",
  "hypothetical",
  "synthetic",
  "unavailable",
  "request_failed",
] as const;

export type StatusLabel = (typeof STATUS_LABELS)[number];

/**
 * The only labels that may position geometry, kept identical to
 * `PLACEABLE_STATUS_LABELS` in the server-bound adapter. Synthetic topology --
 * every ACTIVSg2000-family node -- is deliberately absent: it is Texas-shaped
 * and must never be drawn as geography.
 */
export const PLACEABLE_STATUS_LABELS: readonly StatusLabel[] = ["source_supported", "source_screened"];

export interface ScenePoint {
  /** The server's own identifier, preserved verbatim. */
  readonly id: string;
  /** [longitude, latitude] in EPSG:4326, exactly as the adapter produced it. */
  readonly position: readonly [number, number];
  readonly statusLabel: StatusLabel;
}

export interface SceneView {
  /** Primary state label for the map legend. One of the six shared tokens. */
  readonly status: StatusLabel;
  /** Candidate points. Drawing is decided by `acceptedPoints`, not by this list. */
  readonly points: readonly ScenePoint[];
  /** Operator-facing sentence explaining the state. */
  readonly detail: string;
}

/**
 * A structural read of whatever the adapter returned. Deliberately permissive:
 * it spans both adapter vocabularies without importing either, and every field
 * is optional because a given vocabulary supplies only some of them.
 */
export interface AdapterSceneShape {
  readonly kind?: unknown;
  readonly nodes?: unknown;
  readonly placement?: unknown;
  readonly zones?: unknown;
  readonly allocationStatus?: unknown;
  readonly reason?: unknown;
  readonly detail?: unknown;
  readonly [key: string]: unknown;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function isStatusLabel(value: unknown): value is StatusLabel {
  return typeof value === "string" && (STATUS_LABELS as readonly string[]).includes(value);
}

/**
 * Map one adapter truth/status label onto the shared vocabulary.
 *
 * `source_backed` is the `master` adapter's name for the same thing the bound
 * adapter calls `source_supported`; that rename is the only translation. Any
 * other value -- including `"synthetic"`, which both vocabularies spell the
 * same -- is passed through when it is a known token and becomes `unavailable`
 * when it is not. The browser never upgrades an unknown label into a
 * placeable one.
 */
export function statusLabelOf(value: unknown): StatusLabel {
  if (value === "source_backed") return "source_supported";
  return isStatusLabel(value) ? value : "unavailable";
}

function pointOf(value: unknown): ScenePoint | null {
  if (!isRecord(value)) return null;
  const position = value.position;
  if (!Array.isArray(position) || position.length < 2) return null;
  const [longitude, latitude] = position;
  if (typeof longitude !== "number" || typeof latitude !== "number") return null;
  if (!Number.isFinite(longitude) || !Number.isFinite(latitude)) return null;
  const id = typeof value.id === "string" && value.id.length > 0 ? value.id : null;
  if (id === null) return null;
  // `truthLabel` is the master adapter's field; `statusLabel` the bound one's.
  const label = value.statusLabel === undefined ? value.truthLabel : value.statusLabel;
  return { id, position: [longitude, latitude], statusLabel: statusLabelOf(label) };
}

function pointsOf(values: unknown): ScenePoint[] {
  if (!Array.isArray(values)) return [];
  const points: ScenePoint[] = [];
  for (const value of values) {
    const point = pointOf(value);
    // One unreadable member makes the whole set unusable; a partial scene would
    // silently drop nodes the server did send.
    if (point === null) return [];
    points.push(point);
  }
  return points;
}

const AGGREGATE_DETAIL = "Accepted aggregate coverage has no renderable geometry.";
const REJECTED_DETAIL = "No accepted geographic feature artifact is available.";

/**
 * Read any adapter output into the renderer's view.
 *
 * Rejections and aggregate coverage carry no geometry, so they yield no
 * points at all. Point-bearing kinds keep their points and their per-point
 * labels; whether any of them may be drawn is `acceptedPoints`' decision.
 */
export function sceneViewFor(adaptation: AdapterSceneShape): SceneView {
  const detailOf = (fallback: string) =>
    typeof adaptation.detail === "string" && adaptation.detail.length > 0 ? adaptation.detail : fallback;

  if (adaptation.kind === "rejected") {
    // A refusal reason is not a status token; the state is simply "no artifact".
    const status: StatusLabel = adaptation.reason === "request_failed" ? "request_failed" : "unavailable";
    return { status, points: [], detail: detailOf(REJECTED_DETAIL) };
  }
  if (adaptation.kind === "aggregate_coverage" || adaptation.kind === "aggregate_zones") {
    return {
      status: statusLabelOf(adaptation.allocationStatus),
      points: [],
      detail: detailOf(AGGREGATE_DETAIL),
    };
  }

  const points = adaptation.placement === undefined
    ? pointsOf(adaptation.nodes)
    : pointsOf([adaptation.placement]);
  if (points.length === 0) {
    return { status: "unavailable", points: [], detail: detailOf(REJECTED_DETAIL) };
  }
  // The scene is only as accepted as its least accepted point.
  const status = points.every((point) => PLACEABLE_STATUS_LABELS.includes(point.statusLabel))
    ? points[0].statusLabel
    : points.find((point) => !PLACEABLE_STATUS_LABELS.includes(point.statusLabel))!.statusLabel;
  return { status, points, detail: detailOf(describe(status, points.length)) };
}

function describe(status: StatusLabel, count: number): string {
  if (PLACEABLE_STATUS_LABELS.includes(status)) {
    return `${count} server-accepted placement${count === 1 ? "" : "s"} may be drawn; 3D asset placement remains unavailable until a verified asset artifact is supplied.`;
  }
  return `Topology labelled ${status} is not rendered as a geographic feature layer.`;
}

/**
 * The points the renderer may draw.
 *
 * This is the synthetic-topology guard. A scene is drawn only when *every*
 * point carries a placeable server label, so a single synthetic or unlabeled
 * node suppresses the whole layer rather than being drawn alongside accepted
 * ones. Softening it -- filtering instead of refusing, or admitting
 * `synthetic` -- is what would put ACTIVSg2000 nodes on a Minnesota map.
 */
export function acceptedPoints(view: SceneView): readonly ScenePoint[] {
  if (view.points.length === 0) return [];
  if (!PLACEABLE_STATUS_LABELS.includes(view.status)) return [];
  if (!view.points.every((point) => PLACEABLE_STATUS_LABELS.includes(point.statusLabel))) return [];
  return view.points;
}
