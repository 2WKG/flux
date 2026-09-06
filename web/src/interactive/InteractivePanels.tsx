/**
 * Mounts the interactive inspectors inside the one App (`src/pages/MainPage.tsx`).
 *
 * Before this existed, `BalancePanel` and `RedundancyPanel` had no importer, so
 * `npm run build` tree-shook them out and no user could reach them — and no test
 * could notice, because an unmounted panel still renders green in isolation.
 * `test/interactive-panels-mounted.test.mjs` asserts both panels' own rendered
 * strings are present in the built bundle, so an unmount goes red.
 *
 * The interactive router is not mounted on every origin. When it is absent the
 * request fails and each panel renders its named refusal; nothing is invented.
 */
import { useEffect, useState } from "react";
import type { ClientState } from "../data/client-state";
import {
  createInteractiveClient,
  type BalanceView,
  type InteractiveClient,
  type RedundancyView,
} from "../data/interactive-client";
import { BalancePanel } from "./BalancePanel";
import { RedundancyPanel } from "./RedundancyPanel";

export interface InteractivePanelsProps {
  readonly scenarioId: string;
  readonly busId: string;
  /** Injected in tests; the default is the one shared HTTP boundary. */
  readonly client?: InteractiveClient;
}

const DEFAULT_CLIENT = createInteractiveClient();

export function InteractivePanels({ scenarioId, busId, client = DEFAULT_CLIENT }: InteractivePanelsProps) {
  const [balance, setBalance] = useState<ClientState<BalanceView>>({ kind: "loading" });
  const [redundancy, setRedundancy] = useState<ClientState<RedundancyView>>({ kind: "loading" });

  useEffect(() => {
    let live = true;
    void client.getBalance({ scenarioId, scope: "state" }).then((state) => { if (live) setBalance(state); });
    void client.getRedundancy({ busId }).then((state) => { if (live) setRedundancy(state); });
    return () => { live = false; };
  }, [client, scenarioId, busId]);

  return (
    <section className="interactive-panels" aria-label="Interactive twin inspectors">
      <BalancePanel state={balance} />
      <RedundancyPanel state={redundancy} />
    </section>
  );
}
