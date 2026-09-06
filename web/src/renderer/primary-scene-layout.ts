/**
 * The pure layout and text rules for the primary simulation scene.
 *
 * They live apart from `PrimarySceneDeck.tsx` so a Node test can drive them
 * without importing deck.gl, and so the words a node renders have exactly one
 * owner that both the canvas and the accessible node list read.
 */
import type { PrimarySceneNode } from "../data/primary-scene";

/** The schematic's half-extent, in the orthographic view's own units. */
export const SCENE_EXTENT = 400;

export type PlacedNode = PrimarySceneNode & { readonly xy: readonly [number, number] };

/**
 * Normalise the topology's own coordinate pairs into the schematic square.
 *
 * This is a layout, not a projection: it preserves relative arrangement and
 * asserts no geographic position. `src/renderer/scene-view.ts` refuses to place
 * synthetic topology as geography, and this is how the primary scene honours
 * that rule while still drawing the simulation.
 */
export function placeNodes(nodes: readonly PrimarySceneNode[]): readonly PlacedNode[] {
  if (nodes.length === 0) return [];
  const xs = nodes.map((node) => node.position[0]);
  const ys = nodes.map((node) => node.position[1]);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const maxY = Math.max(...ys);
  const span = Math.max(maxX - minX, maxY - minY);
  const scale = span === 0 ? 0 : (SCENE_EXTENT * 2) / span;
  const midX = (maxX + minX) / 2;
  const midY = (maxY + minY) / 2;
  return nodes.map((node) => ({
    ...node,
    // y is negated so the schematic reads the same way up as the numbers do.
    xy: [(node.position[0] - midX) * scale, -(node.position[1] - midY) * scale] as const,
  }));
}

/**
 * The text a node renders, on the canvas and in the list alike.
 *
 * It is the label `src/data/primary-scene.ts` derived from that node's own
 * provenance through `sourceSummary`. Nothing is composed, defaulted or
 * abbreviated here: a node with no derived label is a node this scene refuses
 * to have produced, so returning anything else would be inventing one.
 */
export function nodeText(node: PrimarySceneNode): string {
  return node.label;
}
