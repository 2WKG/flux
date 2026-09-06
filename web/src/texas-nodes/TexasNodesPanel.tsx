/**
 * Mounts the annotated Texas nodes inside the one App (`src/pages/MainPage.tsx`).
 *
 * Nothing outside `src/texas-nodes/` imported any of this module set, so
 * `npm run build` tree-shook all of it out of `dist/` and no user could reach
 * it — invisible to the suite, because an unmounted panel still renders green in
 * its own test. `test/texas-nodes-mounted.test.mjs` asserts the built bundle
 * carries this surface.
 *
 * The route is `GET /layers/buses` (`web/server.mjs`'s allowlist). When the
 * origin serves no API the panel renders the shared failure state with a named
 * reason; it never renders an empty map.
 */
import { useEffect, useState } from "react";
import { createReadApiClient } from "../data/client-state";
import type { ClientState } from "../data/client-state";
import { FailureState } from "../failure-states/FailureState";
import { fromClientState } from "../failure-states/adapters";
import type { Scale } from "../navigation/scale-ladder";
import { adaptTexasNodes } from "./adapter";
import { TexasNodeInspector, TexasNodeMarker, TexasNodesFailure } from "./presentation";
import type { TexasNodeAdaptation } from "./types";

const READ_CLIENT = createReadApiClient();
const anyJson = (value: unknown): value is unknown => value !== undefined;
const never = () => false;

export interface TexasNodesPanelProps {
  readonly scenarioId: string;
  readonly hour: number;
  readonly scale?: Scale;
  /** Injected in tests; the default is the shared read client. */
  readonly load?: (url: string) => Promise<ClientState<unknown>>;
}

export function texasNodesUrl(scenarioId: string, hour: number): string {
  return `/layers/buses?${new URLSearchParams({ scenario_id: scenarioId, hour: String(hour) }).toString()}`;
}

export function TexasNodesPanel({ scenarioId, hour, scale = "region", load }: TexasNodesPanelProps) {
  const [state, setState] = useState<ClientState<unknown>>({ kind: "loading" });

  useEffect(() => {
    let live = true;
    const fetcher = load ?? ((url: string) => READ_CLIENT.get(url, anyJson, never));
    void fetcher(texasNodesUrl(scenarioId, hour)).then((next) => { if (live) setState(next); });
    return () => { live = false; };
  }, [load, scenarioId, hour]);

  if (state.kind !== "ready") {
    const failure = fromClientState(state);
    return <section className="texas-nodes" aria-label="Annotated Texas nodes">
      {failure ? <FailureState state={failure} /> : null}
    </section>;
  }

  const adaptation: TexasNodeAdaptation = adaptTexasNodes(state.data);
  if (adaptation.kind !== "ready") {
    return <section className="texas-nodes" aria-label="Annotated Texas nodes">
      <TexasNodesFailure adaptation={adaptation} />
    </section>;
  }

  return <section className="texas-nodes" aria-label="Annotated Texas nodes">
    <h2>Annotated Texas nodes</h2>
    <div className="texas-node-markers">
      {adaptation.nodes.map((node) => <TexasNodeMarker key={node.id} node={node} scale={scale} />)}
    </div>
    {adaptation.nodes.length > 0 ? <TexasNodeInspector node={adaptation.nodes[0]} /> : null}
  </section>;
}
