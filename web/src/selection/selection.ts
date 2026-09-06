/** Selection model: picking, linked selection, and stability across navigation.
 *
 * This is the single source of truth a viewport, an inspector, and any
 * supporting panel read to agree on what is selected. It holds no DOM
 * handlers and draws nothing; it only tracks which server entity is picked,
 * whether that entity is currently in the visible set, and the truth label
 * and provenance that travelled with it at pick time.
 *
 * Per `docs/specs/00-overview.md`'s browser/server boundary, this module
 * never invents a label: a pick payload with no valid status token is
 * rejected, not defaulted, and never reaches the store as a selection. The
 * vocabulary is `../labels.ts`'s `AssetStatus` -- the six UI-status tokens
 * `docs/design/minnesota-demo-narrative-ia.md` and
 * `docs/design/minnesota-gate-0-approval.md` freeze (`source_supported`,
 * `source_screened`, `hypothetical`, `synthetic`, `unavailable`,
 * `request_failed`; deliberately no `illustrative`). That module is written
 * once so this one imports it rather than restating the list a third time.
 *
 * Stability rule (explicit, tested): selecting an entity and then navigating
 * or zooming must never silently clear the selection. When the picked
 * entity's id drops out of the current visible-id set, the selection moves to
 * the named `"not_in_view"` presence rather than being cleared; it returns to
 * `"visible"` if the id reappears. Only an explicit `clear()` empties the
 * selection.
 */

import { isAssetStatus, type AssetStatus } from "../labels.js";

export type { AssetStatus };

/** The three pickable entity kinds. Never a browser-generated pseudo-kind. */
export type EntityKind = "line" | "node" | "facility";

const VALID_KINDS: ReadonlySet<string> = new Set<EntityKind>(["line", "node", "facility"]);

/** Provenance that travels with a pick, not fetched separately afterward. */
export interface EntityProvenance {
  readonly layer: string;
  readonly sourceNames: readonly string[];
  readonly fixtureBatchIds: readonly string[];
}

/**
 * What picking produces. `truthLabel` and `provenance` are required fields,
 * not optional add-ons, so a panel reading a selection can never render a
 * value without its label -- there is no state in which they are absent.
 */
export interface PickedEntity {
  readonly kind: EntityKind;
  /** The server's own id. This module never generates or rewrites an id. */
  readonly id: string;
  readonly name: string | null;
  readonly truthLabel: AssetStatus;
  readonly provenance: EntityProvenance;
}

export type EntityPresence = "visible" | "not_in_view";

export type SelectionState =
  | { readonly kind: "none" }
  | {
      readonly kind: "selected";
      readonly entity: PickedEntity;
      readonly presence: EntityPresence;
    };

export const EMPTY_SELECTION: SelectionState = { kind: "none" };

export function selectEntity(entity: PickedEntity): SelectionState {
  return { kind: "selected", entity, presence: "visible" };
}

export function clearSelection(): SelectionState {
  return EMPTY_SELECTION;
}

/**
 * Reconcile a selection against the ids currently visible for its kind.
 * Never clears on its own: an entity absent from `visibleIds` moves the
 * selection to `"not_in_view"`, a named state a caller can render explicitly,
 * rather than dropping the selection back to empty.
 */
export function reconcileVisibility(
  state: SelectionState,
  visibleIds: ReadonlySet<string>,
): SelectionState {
  if (state.kind === "none") return state;
  const presence: EntityPresence = visibleIds.has(state.entity.id) ? "visible" : "not_in_view";
  if (presence === state.presence) return state;
  return { kind: "selected", entity: state.entity, presence };
}

export type PickRejectionReason =
  | "malformed_pick"
  | "missing_id"
  | "invalid_kind"
  | "missing_truth_label";

export interface PickRejection {
  readonly kind: "rejected";
  readonly reason: PickRejectionReason;
  /** Operator-facing detail. Never rendered as a selected value. */
  readonly detail: string;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function stringsOf(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function reject(reason: PickRejectionReason, detail: string): PickRejection {
  return { kind: "rejected", reason, detail };
}

/**
 * Validate a raw pick payload (e.g. a deck.gl pick-event object) into a
 * `PickedEntity`, or refuse it by name. The browser never supplies a missing
 * id, kind, or truth label on the entity's behalf: an unlabeled or
 * unidentifiable pick is a named rejection, not a defaulted selection.
 */
export function toPickedEntity(raw: unknown): PickedEntity | PickRejection {
  if (!isRecord(raw)) {
    return reject("malformed_pick", "Pick payload is not an object.");
  }
  const { kind, id, name, truthLabel, provenance } = raw;

  if (typeof kind !== "string" || !VALID_KINDS.has(kind)) {
    return reject("invalid_kind", `Unsupported or missing entity kind: ${JSON.stringify(kind)}.`);
  }
  if (typeof id !== "string" || id.length === 0) {
    return reject("missing_id", `Picked ${kind} carries no server id.`);
  }
  if (!isAssetStatus(truthLabel)) {
    return reject(
      "missing_truth_label",
      `Picked ${kind} "${id}" carries no valid truth label; the browser may not invent one.`,
    );
  }

  const provenanceRecord = isRecord(provenance) ? provenance : {};
  return {
    kind: kind as EntityKind,
    id,
    name: typeof name === "string" ? name : null,
    truthLabel,
    provenance: {
      layer: typeof provenanceRecord.layer === "string" ? provenanceRecord.layer : "unknown",
      sourceNames: stringsOf(provenanceRecord.sourceNames ?? provenanceRecord.source_names),
      fixtureBatchIds: stringsOf(provenanceRecord.fixtureBatchIds ?? provenanceRecord.fixture_batch_ids),
    },
  };
}

export type SelectionListener = (state: SelectionState) => void;

/**
 * The linked-selection source of truth. A viewport, an inspector, and any
 * supporting panel all read `getState()` (or subscribe) instead of holding
 * their own copies, so they cannot disagree about what is selected.
 */
export interface SelectionStore {
  getState(): SelectionState;
  /** Select an already-validated picked entity. */
  select(entity: PickedEntity): SelectionState;
  /** Validate a raw pick and select it, or leave the store unchanged and
   *  return the rejection for the caller to surface. */
  pick(raw: unknown): SelectionState | PickRejection;
  clear(): SelectionState;
  /** Apply the stability rule above for the current visible-id set. */
  reconcileVisibility(visibleIds: ReadonlySet<string>): SelectionState;
  subscribe(listener: SelectionListener): () => void;
}

export function createSelectionStore(initial: SelectionState = EMPTY_SELECTION): SelectionStore {
  let state = initial;
  const listeners = new Set<SelectionListener>();

  function setState(next: SelectionState): SelectionState {
    state = next;
    for (const listener of listeners) listener(state);
    return state;
  }

  return {
    getState: () => state,
    select: (entity) => setState(selectEntity(entity)),
    pick: (raw) => {
      const result = toPickedEntity(raw);
      if (result.kind === "rejected") return result;
      return setState(selectEntity(result));
    },
    clear: () => setState(clearSelection()),
    reconcileVisibility: (visibleIds) => {
      const next = reconcileVisibility(state, visibleIds);
      if (next !== state) setState(next);
      return state;
    },
    subscribe: (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
}
