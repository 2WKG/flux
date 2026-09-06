/**
 * The deck.gl canvas for the primary simulation scene.
 *
 * It is imported lazily by `PrimaryScene.tsx` and never from a module the
 * server render reaches -- the same shape `GridInventoryPanel` uses for
 * `GridMap`, and for the same two reasons: deck is half a megabyte the rest of
 * the page does not need in order to paint, and the panel above it must stay
 * renderable and assertable in a plain Node test without a WebGL context.
 * Nothing here imports a stylesheet, so no vendor CSS path can reach Node's
 * module loader through this file.
 *
 * **This is an orthographic schematic, not a map.** `src/renderer/scene-view.ts`
 * refuses to place synthetic topology as geography -- ACTIVSg2000 coordinates
 * are Texas-shaped synthetic values and drawing them over a basemap would
 * assert a geography the data does not have. So the positions below are
 * normalised into an abstract square and drawn with `OrthographicView`: no
 * basemap, no tiles, no projection, and no network request of any kind.
 *
 * Every node carries its own derived label as rendered text. There is no code
 * path that draws a node without one: `getText` reads `node.label`, which
 * `src/data/primary-scene.ts` derived from that node's own provenance.
 */
import { useMemo } from "react";
import DeckGL from "@deck.gl/react";
import { OrthographicView } from "@deck.gl/core";
import { ScatterplotLayer, TextLayer } from "@deck.gl/layers";
import type { PrimarySceneNode } from "../data/primary-scene";
import { nodeText, placeNodes, type PlacedNode } from "./primary-scene-layout";

export function PrimarySceneDeck({ nodes }: { readonly nodes: readonly PrimarySceneNode[] }) {
  const placed = useMemo(() => placeNodes(nodes), [nodes]);
  const layers = useMemo(() => [
    new ScatterplotLayer<PlacedNode>({
      id: "primary-scene-nodes",
      data: placed,
      getPosition: (node) => node.xy as [number, number],
      getRadius: 6,
      radiusUnits: "pixels",
      getFillColor: [114, 217, 255, 220],
      pickable: true,
    }),
    new TextLayer<PlacedNode>({
      id: "primary-scene-node-labels",
      data: placed,
      getPosition: (node) => node.xy as [number, number],
      // The one place a node's words come from. Nothing is composed here.
      getText: nodeText,
      getSize: 11,
      getPixelOffset: [0, -14],
      getColor: [237, 245, 255, 235],
      characterSet: "auto",
      background: true,
      getBackgroundColor: [7, 23, 37, 210],
      backgroundPadding: [3, 2],
      pickable: false,
    }),
  ], [placed]);

  return <DeckGL
    views={new OrthographicView({ id: "primary-scene-schematic" })}
    initialViewState={{ target: [0, 0, 0], zoom: 0 }}
    controller={true}
    layers={layers}
    getTooltip={({ object }) => (object ? { text: `${(object as PlacedNode).id}\n${(object as PlacedNode).label}` } : null)}
  />;
}

export default PrimarySceneDeck;
