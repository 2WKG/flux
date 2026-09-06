/**
 * Author-guided presenter scenes for the Minnesota aggregate shell.
 *
 * These are deliberately presentation instructions, not map camera commands.
 * Gate 0 has no Minnesota geometry, topology, model output, or viewport
 * contract. A host can render the cues in any medium, but may only treat the
 * aggregate context it receives as current.
 */
import type { RunIdentity } from "../ask/run-state/types";
import type {
  MinnesotaSceneRunContext,
  MinnesotaRunContextChange,
} from "../minnesota/run-context";

export const MINNESOTA_PRESENTER_SCENE_IDS = [
  "mn-presenter-aggregate-evidence",
  "mn-presenter-synthetic-disclosure",
  "mn-presenter-artifact-unavailable",
] as const;

export type MinnesotaPresenterSceneId = (typeof MINNESOTA_PRESENTER_SCENE_IDS)[number];
export type MinnesotaPresenterSceneFrame = "aggregate" | "synthetic" | "unavailable";

export interface MinnesotaPresenterScene {
  readonly id: MinnesotaPresenterSceneId;
  readonly frame: MinnesotaPresenterSceneFrame;
  readonly title: string;
  readonly presenterCue: string;
  /**
   * A named, host-facing instruction. It intentionally contains no target,
   * bearing, zoom, coordinates, or feature identifier.
   */
  readonly actionLabel: string;
}

export interface MinnesotaPresenterSceneAction {
  readonly scene: MinnesotaPresenterScene;
  readonly context: Readonly<MinnesotaSceneRunContext>;
  readonly identity: Readonly<RunIdentity>;
  activate(): void;
}

const scenes: readonly MinnesotaPresenterScene[] = Object.freeze([
  Object.freeze({
    id: "mn-presenter-aggregate-evidence",
    frame: "aggregate",
    title: "Aggregate evidence baseline",
    presenterCue:
      "Frame this as the accepted Minnesota aggregate baseline. It identifies coverage metadata only; it does not locate or model grid assets.",
    actionLabel: "Present aggregate evidence baseline",
  }),
  Object.freeze({
    id: "mn-presenter-synthetic-disclosure",
    frame: "synthetic",
    title: "Synthetic view unavailable",
    presenterCue:
      "Do not substitute a synthetic preview for Minnesota evidence. This run context supplies no synthetic model, topology, or camera target.",
    actionLabel: "Present synthetic-view disclosure",
  }),
  Object.freeze({
    id: "mn-presenter-artifact-unavailable",
    frame: "unavailable",
    title: "Feature artifact unavailable",
    presenterCue:
      "State that no Minnesota feature artifact, geometry, allocation, or scenario result is available for inspection in this run.",
    actionLabel: "Present unavailable-artifact disclosure",
  }),
]);

/** Stable ordered script for a presenter or accessibility host. */
export function listMinnesotaPresenterScenes(): readonly MinnesotaPresenterScene[] {
  return scenes;
}

export function getMinnesotaPresenterScene(id: MinnesotaPresenterSceneId): MinnesotaPresenterScene {
  const scene = scenes.find((candidate) => candidate.id === id);
  if (!scene) throw new Error(`Unknown Minnesota presenter scene: ${id}`);
  return scene;
}

/**
 * Bind a named presenter action to the shell's existing change seam. Scene
 * selection never mutates aggregate state: it republishes the exact context
 * and run identity a host supplied, so consumers can preserve stale-result
 * protection while reporting a presentation transition.
 */
export function createMinnesotaPresenterSceneAction(
  sceneId: MinnesotaPresenterSceneId,
  context: Readonly<MinnesotaSceneRunContext>,
  identity: Readonly<RunIdentity>,
  onContextChange?: MinnesotaRunContextChange,
): MinnesotaPresenterSceneAction {
  return Object.freeze({
    scene: getMinnesotaPresenterScene(sceneId),
    context,
    identity,
    activate: () => onContextChange?.(context, identity),
  });
}

/** Build the complete ordered presenter script against one current shell run. */
export function createMinnesotaPresenterSceneActions(
  context: Readonly<MinnesotaSceneRunContext>,
  identity: Readonly<RunIdentity>,
  onContextChange?: MinnesotaRunContextChange,
): readonly MinnesotaPresenterSceneAction[] {
  return Object.freeze(
    scenes.map((scene) => createMinnesotaPresenterSceneAction(scene.id, context, identity, onContextChange)),
  );
}
