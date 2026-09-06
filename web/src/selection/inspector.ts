/** The inspector's view model: what a selection means for a detail panel.
 *
 * This module never fetches, joins, or invents data. It takes the current
 * `SelectionState` (see `./selection.ts`) plus a caller-supplied detail
 * lookup and produces exactly one of three named states. A blank panel, a
 * zero value, or an invented field is never one of them: an inspector with no
 * source detail renders `"unavailable"` naming the missing prerequisite,
 * never a quiet empty success.
 */

import type { EntityPresence, PickedEntity, SelectionState, TruthLabel } from "./selection.js";

export interface InspectorField {
  readonly label: string;
  readonly value: string;
}

/**
 * Detail beyond what travels with the pick itself (see `PickedEntity`).
 * `truthLabel`/`provenance` are repeated here deliberately: source detail may
 * be scoped more precisely (e.g. a specific reading) than the pick-time
 * label, but it must still carry its own label rather than borrow one
 * silently.
 */
export interface EntityDetail {
  readonly fields: readonly InspectorField[];
  readonly truthLabel: TruthLabel;
  readonly provenance: {
    readonly sourceNames: readonly string[];
    readonly fixtureBatchIds: readonly string[];
  };
}

/** Looks up source detail for a picked entity. `null` means "no record", not "empty record". */
export type DetailLookup = (entity: PickedEntity) => EntityDetail | null;

export type InspectorViewModel =
  | { readonly kind: "empty" }
  | {
      readonly kind: "unavailable";
      readonly entity: PickedEntity;
      /** Named, operator-facing prerequisite that is missing. Never a number or a blank. */
      readonly missingPrerequisite: string;
    }
  | {
      readonly kind: "ready";
      readonly entity: PickedEntity;
      readonly presence: EntityPresence;
      readonly detail: EntityDetail;
    };

/**
 * Build the inspector's view model for the current selection.
 *
 * - No selection -> `"empty"` (there is nothing to inspect; this is not the
 *   same state as "selected but no detail").
 * - Selected but the detail lookup returns `null` -> `"unavailable"`, naming
 *   the missing prerequisite. This also covers a selection whose entity has
 *   left the visible set: presence is reported through the `"ready"` branch
 *   below when detail exists, so the caller can still show the last-known
 *   truth label and provenance while flagging that the entity is currently
 *   out of view -- selection is never silently dropped by an inspector
 *   redraw.
 * - Selected and detail exists -> `"ready"`, carrying both the entity's
 *   pick-time label/provenance and the looked-up detail.
 */
export function buildInspectorViewModel(
  state: SelectionState,
  lookupDetail: DetailLookup,
): InspectorViewModel {
  if (state.kind === "none") {
    return { kind: "empty" };
  }

  const detail = lookupDetail(state.entity);
  if (detail === null) {
    return {
      kind: "unavailable",
      entity: state.entity,
      missingPrerequisite: `No source detail record for ${state.entity.kind} "${state.entity.id}".`,
    };
  }

  return { kind: "ready", entity: state.entity, presence: state.presence, detail };
}

/** True only for a view model that may render a labeled detail value. */
export function hasRenderableDetail(
  viewModel: InspectorViewModel,
): viewModel is Extract<InspectorViewModel, { kind: "ready" }> {
  return viewModel.kind === "ready";
}
