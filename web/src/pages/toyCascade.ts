/**
 * A deliberately small DC-screening example for the explainer page.
 *
 * This is synthetic teaching data, separate from the main-page fixture. The
 * values make one initiating outage visibly reroute power through an
 * overloaded corridor before an islanded load is shed. It is not a grid study,
 * forecast, or protection model.
 */
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

export const TOY_BUSES: readonly ToyBus[] = [
  { id: "west", name: "West generator", generationMw: 120, demandMw: 0, x: 84, y: 185 },
  { id: "north", name: "North load", generationMw: 40, demandMw: 50, x: 255, y: 65 },
  { id: "hub", name: "Central hub", generationMw: 0, demandMw: 30, x: 390, y: 185 },
  { id: "east", name: "East load", generationMw: 0, demandMw: 70, x: 590, y: 125 },
  { id: "south", name: "South load", generationMw: 0, demandMw: 10, x: 490, y: 330 },
] as const;

export const TOY_LINES: readonly ToyLine[] = [
  { id: "west-north", from: "west", to: "north", reactance: 0.25, ratingMw: 80 },
  { id: "west-hub", from: "west", to: "hub", reactance: 0.2, ratingMw: 110 },
  { id: "north-hub", from: "north", to: "hub", reactance: 0.25, ratingMw: 80 },
  { id: "hub-east", from: "hub", to: "east", reactance: 0.2, ratingMw: 90 },
  { id: "hub-south", from: "hub", to: "south", reactance: 0.25, ratingMw: 70 },
  { id: "east-south", from: "east", to: "south", reactance: 0.25, ratingMw: 35 },
] as const;

const BUS_BY_ID = new Map(TOY_BUSES.map((bus) => [bus.id, bus]));
const LINE_BY_ID = new Map(TOY_LINES.map((line) => [line.id, line]));

function number(value: number): number {
  return Math.abs(value) < 1e-9 ? 0 : Number(value.toFixed(6));
}

function connectedComponents(activeLines: readonly ToyLine[]): string[][] {
  const neighbors = new Map(TOY_BUSES.map((bus) => [bus.id, [] as string[]]));
  for (const line of activeLines) {
    neighbors.get(line.from)?.push(line.to);
    neighbors.get(line.to)?.push(line.from);
  }
  const unseen = new Set(TOY_BUSES.map((bus) => bus.id));
  const components: string[][] = [];
  while (unseen.size) {
    const first = unseen.values().next().value as string;
    const component: string[] = [];
    const todo = [first];
    unseen.delete(first);
    while (todo.length) {
      const id = todo.pop()!;
      component.push(id);
      for (const neighbor of neighbors.get(id) ?? []) if (unseen.delete(neighbor)) todo.push(neighbor);
    }
    components.push(component);
  }
  return components;
}

function balanceComponents(activeLines: readonly ToyLine[]) {
  const injections: Record<string, number> = Object.fromEntries(
    TOY_BUSES.map((bus) => [bus.id, bus.generationMw - bus.demandMw]),
  );
  const actions: BalanceAction[] = [];
  for (const component of connectedComponents(activeLines)) {
    const total = component.reduce((sum, id) => sum + injections[id], 0);
    if (Math.abs(total) < 1e-9) continue;
    const candidates = component.map((id) => BUS_BY_ID.get(id)!).filter((bus) => total < 0 ? bus.demandMw > 0 : bus.generationMw > 0);
    const denominator = candidates.reduce((sum, bus) => sum + (total < 0 ? bus.demandMw : bus.generationMw), 0);
    if (!denominator) throw new Error(`Cannot balance component containing ${component.join(", ")}.`);
    for (const bus of candidates) {
      const mw = Math.abs(total) * ((total < 0 ? bus.demandMw : bus.generationMw) / denominator);
      injections[bus.id] += total < 0 ? mw : -mw;
      actions.push({ busId: bus.id, kind: total < 0 ? "shed_load" : "curtail_generation", mw: number(mw) });
    }
  }
  return { injections, actions };
}

/** Solve A·x=b with Gauss-Jordan elimination. The toy system is at most 4×4. */
function solveLinearSystem(matrix: number[][], vector: number[]): number[] {
  const augmented = matrix.map((row, index) => [...row, vector[index]]);
  for (let column = 0; column < matrix.length; column += 1) {
    let pivot = column;
    for (let row = column + 1; row < matrix.length; row += 1) if (Math.abs(augmented[row][column]) > Math.abs(augmented[pivot][column])) pivot = row;
    if (Math.abs(augmented[pivot][column]) < 1e-9) throw new Error("Toy DC matrix is singular.");
    [augmented[column], augmented[pivot]] = [augmented[pivot], augmented[column]];
    const divisor = augmented[column][column];
    augmented[column] = augmented[column].map((value) => value / divisor);
    for (let row = 0; row < augmented.length; row += 1) {
      if (row === column) continue;
      const factor = augmented[row][column];
      augmented[row] = augmented[row].map((value, index) => value - factor * augmented[column][index]);
    }
  }
  return augmented.map((row) => number(row[row.length - 1]));
}

export function solveToyDc(activeLineIds: ReadonlySet<string>) {
  const activeLines = TOY_LINES.filter((line) => activeLineIds.has(line.id));
  const { injections, actions } = balanceComponents(activeLines);
  const angles: Record<string, number> = Object.fromEntries(TOY_BUSES.map((bus) => [bus.id, 0]));
  for (const component of connectedComponents(activeLines)) {
    if (component.length < 2) continue;
    const reference = component[0];
    const unknowns = component.filter((id) => id !== reference);
    const index = new Map(unknowns.map((id, position) => [id, position]));
    const matrix = unknowns.map(() => unknowns.map(() => 0));
    const vector = unknowns.map((id) => injections[id]);
    for (const line of activeLines) {
      const susceptance = 1 / line.reactance;
      const fromIndex = index.get(line.from);
      const toIndex = index.get(line.to);
      if (fromIndex !== undefined) {
        matrix[fromIndex][fromIndex] += susceptance;
        if (toIndex !== undefined) matrix[fromIndex][toIndex] -= susceptance;
      }
      if (toIndex !== undefined) {
        matrix[toIndex][toIndex] += susceptance;
        if (fromIndex !== undefined) matrix[toIndex][fromIndex] -= susceptance;
      }
    }
    const solution = solveLinearSystem(matrix, vector);
    for (const id of unknowns) angles[id] = solution[index.get(id)!];
  }
  const lines = activeLines.map((line) => {
    const flowMw = number((angles[line.from] - angles[line.to]) / line.reactance);
    return { ...line, flowMw, utilizationPct: number((Math.abs(flowMw) / line.ratingMw) * 100) };
  });
  return { activeLines, injections, actions, angles, lines };
}

function mostOverloaded(lines: readonly SolvedLine[]): SolvedLine | null {
  return lines.filter((line) => line.utilizationPct > 100).sort((left, right) => right.utilizationPct - left.utilizationPct || left.id.localeCompare(right.id))[0] ?? null;
}

/** Run the same tiny chain shown in the page: a seeded outage, re-dispatch, then overload trip(s). */
export function runToyCascade(): readonly CascadeStage[] {
  const open = new Set<string>();
  const stages: CascadeStage[] = [];
  const addStage = (id: string, title: string, explanation: string, trippedLineId: string | null) => {
    const activeLineIds = TOY_LINES.filter((line) => !open.has(line.id)).map((line) => line.id);
    const solved = solveToyDc(new Set(activeLineIds));
    const nextTripLineId = mostOverloaded(solved.lines)?.id ?? null;
    stages.push({
      id, title, explanation, trippedLineId, activeLineIds, nextTripLineId,
      injectionsMw: solved.injections,
      angles: solved.angles,
      balanceActions: solved.actions,
      lines: solved.lines,
    });
  };
  addStage("base", "1. Normal toy network", "All six synthetic corridors are available. DC flow balances the five specified bus injections.", null);
  const initiating = "hub-east";
  open.add(initiating);
  addStage("event", "2. Synthetic initiating outage", "For teaching purposes, Central hub → East load trips. Re-solving redistributes its power through East load → South load.", initiating);
  for (let index = 0; index < 3; index += 1) {
    const next = stages[stages.length - 1].nextTripLineId;
    if (!next) break;
    open.add(next);
    const line = LINE_BY_ID.get(next)!;
    addStage(`cascade-${index + 1}`, `3. Cascade trip ${index + 1}`, `${line.from} → ${line.to} exceeds its thermal rating, so this toy rule removes the most overloaded remaining line and re-solves.`, next);
  }
  return stages;
}
