/**
 * The explainer's teaching cascade, as the server solved it.
 *
 * Nothing here computes. `twin/toy_cascade.py` runs the DC screening chain on
 * the server, `scripts/export_toy_cascade_trace.py` freezes the result into
 * `data/explainer/toy-cascade-trace.json`, and `GET /explainer/toy-cascade`
 * serves those exact bytes. This module imports the same artifact so the page
 * can replay it with no API round trip; `twin/tests/test_toy_cascade.py` fails
 * if the committed artifact is not what a fresh server solve produces.
 *
 * There is no browser solver: the page renders numbers it was handed.
 */
import artifact from "../../../data/explainer/toy-cascade-trace.json";

export interface ToyBus {
  readonly id: string;
  readonly name: string;
  readonly generationMw: number;
  readonly demandMw: number;
  readonly x: number;
  readonly y: number;
}

export interface ToyLine {
  readonly id: string;
  readonly from: string;
  readonly to: string;
  readonly reactance: number;
  readonly ratingMw: number;
}

export interface BalanceAction {
  readonly busId: string;
  readonly kind: "shed_load" | "curtail_generation";
  readonly mw: number;
}

export interface SolvedLine extends ToyLine {
  readonly flowMw: number;
  readonly utilizationPct: number;
}

export interface CascadeStage {
  readonly id: string;
  readonly title: string;
  readonly explanation: string;
  readonly trippedLineId: string | null;
  readonly activeLineIds: readonly string[];
  readonly injectionsMw: Readonly<Record<string, number>>;
  readonly angles: Readonly<Record<string, number>>;
  readonly balanceActions: readonly BalanceAction[];
  readonly lines: readonly SolvedLine[];
  readonly nextTripLineId: string | null;
}

export interface ToyCascadeTrace {
  readonly schemaVersion: number;
  readonly modelFidelity: string;
  readonly networkProvenance: string;
  readonly networkLabel: string;
  readonly limitations: readonly string[];
  readonly network: { readonly buses: readonly ToyBus[]; readonly lines: readonly ToyLine[] };
  readonly stages: readonly CascadeStage[];
  readonly traceHash: string;
}

/** The persisted server trace. Read-only; the page never recomputes it. */
export const TOY_CASCADE_TRACE = artifact as unknown as ToyCascadeTrace;

/** The read route that serves the identical bytes, named for the page's provenance line. */
export const TOY_CASCADE_ROUTE = "/explainer/toy-cascade";

/** The artifact this page replays, named so a reader can find and re-solve it. */
export const TOY_CASCADE_ARTIFACT_ID = "data/explainer/toy-cascade-trace.json";

export const TOY_BUSES: readonly ToyBus[] = TOY_CASCADE_TRACE.network.buses;
export const TOY_LINES: readonly ToyLine[] = TOY_CASCADE_TRACE.network.lines;
