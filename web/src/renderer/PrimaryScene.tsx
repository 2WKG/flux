/**
 * The primary simulation scene, composed inside the one App (2WKG-479).
 *
 * The main route's primary surface is the deck.gl simulation, mounted *beside*
 * the panels the App already carries -- the chat seam, the run trace, the
 * result cards, the inspector, the layer controls and the source-backed
 * physical inventory map -- not in place of any of them. The five-bus fixture
 * screen keeps its one job: the labelled offline preview.
 *
 * This module is presentational. It issues no request: `MainPage` calls
 * `loadPrimaryScene` (`src/data/primary-scene.ts`) and hands the result down,
 * so there is no `fetch` in a component and one seam decides what may be drawn.
 *
 * Two rendering rules:
 *
 * 1. **The canvas is lazy and browser-only**, the same shape `GridInventoryPanel`
 *    uses for `GridMap`. Nothing deck.gl or MapLibre reaches the server render
 *    or a Node test's module loader.
 * 2. **Every node is rendered with its own derived label, in the DOM too.** The
 *    canvas draws `nodeText(node)` and the accessible list below prints the same
 *    string from the same owner, so the scene's truth labels are assertable
 *    without a WebGL context and a relabelled or unlabelled node is a red test
 *    rather than a screenshot no one reads.
 */
import { Suspense, lazy, useEffect, useState } from "react";
import { STATUS_COPY } from "../source-truth";
import type { PrimarySceneState } from "../data/primary-scene";
import { nodeText } from "./primary-scene-layout";

const LazyPrimarySceneDeck = lazy(() =>
  import("./PrimarySceneDeck").then((module) => ({ default: module.PrimarySceneDeck })));

/** How many nodes get a list row before the list discloses the remainder. */
export const LISTED_NODES = 40;

export function PrimaryScene({ scene, onRetry }: {
  readonly scene: PrimarySceneState;
  readonly onRetry: () => void;
}) {
  // The canvas needs a document, so it is mounted after the first client render
  // rather than during the server render.
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  const nodes = scene.kind === "ready" ? scene.nodes : [];

  return <section className="primary-scene" aria-label="Primary simulation scene">
    <div className="map-head">
      <div>
        <p className="eyebrow">PRIMARY SIMULATION</p>
        <p className="hint">
          The deck.gl scene, read from the read-only synthetic model route. An orthographic schematic of the
          topology's own published coordinates; it is not a map and asserts no geographic position.
        </p>
      </div>
    </div>

    <div className="primary-scene-canvas">
      {scene.kind === "ready" && mounted
        ? <Suspense fallback={<p className="primary-scene-pending">Loading the simulation renderer.</p>}>
            <LazyPrimarySceneDeck nodes={nodes} />
          </Suspense>
        : <p className="primary-scene-pending">
            {scene.kind === "ready"
              ? "The simulation renderer loads in the browser."
              : scene.kind === "loading"
                ? "Requesting the synthetic topology release from the read-only model route."
                : "No simulation is drawn; the named state below is the whole of what this origin answered."}
          </p>}
    </div>

    <div className="primary-scene-note" role="status">
      {scene.kind === "loading"
        ? <span>Requesting the synthetic topology release from the read-only model route.</span>
        : scene.kind === "unavailable"
          ? <>
              <strong>{STATUS_COPY[scene.status]}</strong>
              <span>{scene.message}</span>
              <span>Code <code>{scene.code}</code>{scene.requestId ? <> · request <code>{scene.requestId}</code></> : null}</span>
              <button type="button" onClick={onRetry}>Retry the simulation request</button>
            </>
          : <>
              <strong className="primary-scene-release">{scene.topology.label}{scene.topology.modelMode ? <> · {scene.topology.modelMode}</> : null}{scene.topology.solver ? <> · solver {scene.topology.solver}</> : null}</strong>
              <span>{nodes.length} node{nodes.length === 1 ? "" : "s"} drawn, each labelled from its own provenance.</span>
              {scene.topology.coordinateSource
                ? <span className="primary-scene-release">Coordinate source: {scene.topology.coordinateSource}</span>
                : null}
              {scene.topology.declaredBuses !== null || scene.topology.declaredBranches !== null
                ? <span>
                    The release declares {scene.topology.declaredBuses ?? "an unstated number of"} bus
                    {scene.topology.declaredBuses === 1 ? "" : "es"} and{" "}
                    {scene.topology.declaredBranches ?? "an unstated number of"} branch
                    {scene.topology.declaredBranches === 1 ? "" : "es"}; branches carry no node position and are
                    not drawn as nodes.
                  </span>
                : null}
              {scene.excluded > 0
                ? <span>
                    {scene.excluded} loaded element{scene.excluded === 1 ? " is" : "s are"} not drawn as
                    node{scene.excluded === 1 ? "" : "s"}, of which {scene.refusedTopology}{" "}
                    {scene.refusedTopology === 1 ? "does" : "do"} not derive the asserted synthetic topology.
                    Nothing was relabelled to fit it.
                  </span>
                : null}
            </>}
    </div>

    {scene.kind === "ready"
      ? <ul className="primary-scene-nodes" aria-label="Rendered simulation nodes">
          {nodes.slice(0, LISTED_NODES).map((node) => (
            <li className="primary-scene-node" key={node.id}>
              <b>{node.id}</b>
              <span className="primary-scene-label">{nodeText(node)}</span>
            </li>
          ))}
          {nodes.length > LISTED_NODES
            ? <li className="primary-scene-node" key="__remainder__">
                <span className="primary-scene-remainder">
                  Showing the first {LISTED_NODES} of {nodes.length} drawn nodes; the rest are on the canvas above.
                </span>
              </li>
            : null}
        </ul>
      : null}
  </section>;
}
