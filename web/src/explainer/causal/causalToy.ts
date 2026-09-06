/**
 * A deliberately small discrete causal model for the explainer page.
 *
 * `docs/specs/07-causal-layer.md` (C1) specifies a hand-drawn Bayesian network
 * `weather_severity → exposure → line_failures → substation_loss →
 * customers_out` with `investment` (a hardening proxy) confounding both
 * `line_failures` and `customers_out`. This module is a teaching miniature of
 * that graph: the same node names and the same edges, with two states where the
 * spec uses four, so the whole joint distribution is 96 rows and every number on
 * screen can be recomputed by hand.
 *
 * Every probability below is ILLUSTRATIVE. Nothing here is fitted, and nothing
 * here comes from `causal/bn.py`, `causal_attribution`, or `causal_query`. The
 * fitted artifacts live offline and reach the copilot only through the evidence
 * gate mirrored in `./evidenceGate.ts`. The numbers exist to demonstrate one
 * structural fact — that conditioning on a variable and intervening on it are
 * different operations — which holds for any CPT with these edges.
 */
export type VariableId =
  | "weather_severity"
  | "exposure"
  | "investment"
  | "line_failures"
  | "substation_loss"
  | "customers_out";

export interface Variable {
  readonly id: VariableId;
  readonly label: string;
  readonly states: readonly string[];
  /** Human copy for each state, positionally aligned with `states`. */
  readonly stateLabels: readonly string[];
  readonly parents: readonly VariableId[];
  /** Parent-state key (`states.join("|")`, `""` at a root) to a distribution over `states`. */
  readonly table: Readonly<Record<string, readonly number[]>>;
}

export type Assignment = Readonly<Partial<Record<VariableId, string>>>;

export interface JointRow {
  readonly assignment: Readonly<Record<VariableId, string>>;
  readonly probability: number;
}

/** The outcome state the spec's attribution query asks about (`frac_out ≥ 5%`). */
export const OUTAGE_STATE = "at_least_5pct";

function key(states: readonly string[]): string {
  return states.join("|");
}

/** Enumerate every parent-state combination in the order the parents are listed. */
function parentCombinations(parents: readonly Variable[]): string[][] {
  return parents.reduce<string[][]>(
    (rows, parent) => rows.flatMap((row) => parent.states.map((state) => [...row, state])),
    [[]],
  );
}

function tableFrom(
  parents: readonly Variable[],
  distribution: (parentStates: readonly string[]) => readonly number[],
): Record<string, readonly number[]> {
  return Object.fromEntries(parentCombinations(parents).map((row) => [key(row), distribution(row)]));
}

function root(
  id: VariableId,
  label: string,
  states: readonly string[],
  stateLabels: readonly string[],
  distribution: readonly number[],
): Variable {
  return { id, label, states, stateLabels, parents: [], table: { "": distribution } };
}

const weatherSeverity = root(
  "weather_severity",
  "Weather severity",
  ["calm", "severe"],
  ["Calm window", "Severe window"],
  [0.75, 0.25],
);

const exposure = root(
  "exposure",
  "Exposure",
  ["low", "high"],
  ["Low exposure", "High exposure"],
  [0.6, 0.4],
);

const investment = root(
  "investment",
  "Utility investment",
  ["maintained", "under_invested"],
  ["Maintained", "Under-invested"],
  [0.5, 0.5],
);

/**
 * `line_failures` rises with weather, with exposure, and with under-investment.
 * The three inputs are added into one illustrative severity score so the table
 * is legible; the shape of the numbers is what matters, not their level.
 */
const lineFailureRows: readonly (readonly number[])[] = [
  [0.9, 0.09, 0.01],
  [0.75, 0.2, 0.05],
  [0.55, 0.3, 0.15],
  [0.3, 0.35, 0.35],
  [0.1, 0.3, 0.6],
];

const lineFailures: Variable = {
  id: "line_failures",
  label: "Line failures",
  states: ["none", "few", "many"],
  stateLabels: ["No lines out", "A few lines out", "Many lines out"],
  parents: ["weather_severity", "exposure", "investment"],
  table: tableFrom([weatherSeverity, exposure, investment], ([weather, exposureState, invest]) => {
    const score =
      (weather === "severe" ? 2 : 0) +
      (exposureState === "high" ? 1 : 0) +
      (invest === "under_invested" ? 1 : 0);
    return lineFailureRows[score];
  }),
};

const substationLoss: Variable = {
  id: "substation_loss",
  label: "Substation loss",
  states: ["no", "yes"],
  stateLabels: ["Substations held", "A substation de-energised"],
  parents: ["line_failures"],
  table: tableFrom([lineFailures], ([failures]) => {
    const yes = failures === "many" ? 0.55 : failures === "few" ? 0.15 : 0.02;
    return [1 - yes, yes];
  }),
};

/**
 * `customers_out` keeps the spec's direct `weather_severity` and `investment`
 * edges: a generation-shortfall event (Uri) darkens customers without a wires
 * story, and an under-invested county restores more slowly. Those two edges are
 * exactly what make `line_failures` a confounded treatment.
 */
const customersOut: Variable = {
  id: "customers_out",
  label: "Customers out",
  states: ["under_5pct", OUTAGE_STATE],
  stateLabels: ["Under 5% out", "At least 5% out"],
  parents: ["line_failures", "substation_loss", "investment", "weather_severity"],
  table: tableFrom(
    [lineFailures, substationLoss, investment, weatherSeverity],
    ([failures, substation, invest, weather]) => {
      const base = failures === "many" ? 0.55 : failures === "few" ? 0.2 : 0.03;
      const raw =
        base +
        (substation === "yes" ? 0.2 : 0) +
        (invest === "under_invested" ? 0.12 : 0) +
        (weather === "severe" ? 0.1 : 0);
      const out = Math.min(0.97, Math.max(0.01, Number(raw.toFixed(6))));
      return [1 - out, out];
    },
  ),
};

/** Topologically ordered: every variable appears after its parents. */
export const CAUSAL_MODEL: readonly Variable[] = [
  weatherSeverity,
  exposure,
  investment,
  lineFailures,
  substationLoss,
  customersOut,
] as const;

/** The edges of the graph, for drawing and for tests that pin the structure. */
export const CAUSAL_EDGES: readonly (readonly [VariableId, VariableId])[] = CAUSAL_MODEL.flatMap(
  (variable) => variable.parents.map((parent) => [parent, variable.id] as const),
);

/** Roots of the graph. Conditioning and intervening agree on exactly these. */
export const EXOGENOUS_IDS: readonly VariableId[] = CAUSAL_MODEL.filter(
  (variable) => variable.parents.length === 0,
).map((variable) => variable.id);

export function variableById(model: readonly Variable[], id: VariableId): Variable {
  const found = model.find((variable) => variable.id === id);
  if (!found) throw new Error(`Unknown causal variable: ${id}`);
  return found;
}

/** Reject a malformed model loudly instead of rendering a number derived from it. */
export function assertModel(model: readonly Variable[]): readonly Variable[] {
  const seen = new Set<VariableId>();
  for (const variable of model) {
    if (variable.states.length !== variable.stateLabels.length) {
      throw new Error(`${variable.id} has a state label for every state.`);
    }
    for (const parent of variable.parents) {
      if (!seen.has(parent)) throw new Error(`${variable.id} lists parent ${parent} out of order.`);
    }
    const parents = variable.parents.map((id) => variableById(model, id));
    const expected = parentCombinations(parents).map(key);
    const actual = Object.keys(variable.table);
    if (expected.length !== actual.length || expected.some((row) => !(row in variable.table))) {
      throw new Error(`${variable.id} is missing a conditional row.`);
    }
    for (const [row, distribution] of Object.entries(variable.table)) {
      if (distribution.length !== variable.states.length) {
        throw new Error(`${variable.id} row "${row}" does not cover every state.`);
      }
      if (distribution.some((value) => value < 0 || value > 1)) {
        throw new Error(`${variable.id} row "${row}" holds a value outside [0, 1].`);
      }
      const total = distribution.reduce((sum, value) => sum + value, 0);
      if (Math.abs(total - 1) > 1e-9) {
        throw new Error(`${variable.id} row "${row}" sums to ${total}, not 1.`);
      }
    }
    seen.add(variable.id);
  }
  return model;
}

/**
 * `do(X = x)`: delete the edges into `X` and fix its value.
 *
 * This is the whole difference between the two operations. Conditioning filters
 * the population the model already describes; intervening edits the model, so
 * whatever used to explain `X` no longer travels with it.
 */
export function intervene(model: readonly Variable[], values: Assignment): readonly Variable[] {
  return model.map((variable) => {
    const value = values[variable.id];
    if (value === undefined) return variable;
    if (!variable.states.includes(value)) {
      throw new Error(`${variable.id} has no state "${value}" to intervene on.`);
    }
    return {
      ...variable,
      parents: [],
      table: { "": variable.states.map((state) => (state === value ? 1 : 0)) },
    };
  });
}

/** Every full assignment with its probability. 96 rows for this model. */
export function enumerateJoint(model: readonly Variable[]): readonly JointRow[] {
  let rows: JointRow[] = [{ assignment: {} as Record<VariableId, string>, probability: 1 }];
  for (const variable of model) {
    rows = rows.flatMap((row) => {
      const parentStates = variable.parents.map((parent) => row.assignment[parent]);
      const distribution = variable.table[key(parentStates)];
      if (!distribution) throw new Error(`${variable.id} is missing row "${key(parentStates)}".`);
      return variable.states.map((state, index) => ({
        assignment: { ...row.assignment, [variable.id]: state },
        probability: row.probability * distribution[index],
      }));
    });
  }
  return rows;
}

export interface Marginal {
  readonly probabilities: Readonly<Record<string, number>>;
  /** P(evidence). Zero evidence has no conditional distribution at all. */
  readonly evidenceProbability: number;
}

/**
 * P(target | given) in the supplied model. Pass an intervened model to get the
 * interventional answer; the arithmetic afterwards is identical, which is the
 * point the section teaches.
 */
export function marginal(model: readonly Variable[], target: VariableId, given: Assignment = {}): Marginal {
  const variable = variableById(model, target);
  const totals = Object.fromEntries(variable.states.map((state) => [state, 0]));
  let evidenceProbability = 0;
  for (const row of enumerateJoint(model)) {
    if (Object.entries(given).some(([id, state]) => row.assignment[id as VariableId] !== state)) continue;
    evidenceProbability += row.probability;
    totals[row.assignment[target]] += row.probability;
  }
  if (evidenceProbability <= 0) {
    throw new Error(`No population matches the selected evidence, so P(${target} | …) is undefined.`);
  }
  const probabilities = Object.fromEntries(
    Object.entries(totals).map(([state, value]) => [state, value / evidenceProbability]),
  );
  return { probabilities, evidenceProbability };
}

/** P(customers_out ≥ 5%), the quantity the spec's attribution query reports. */
export function outageRisk(model: readonly Variable[], given: Assignment = {}): number {
  return marginal(model, "customers_out", given).probabilities[OUTAGE_STATE];
}

export interface MixRow {
  readonly id: VariableId;
  readonly label: string;
  readonly state: string;
  readonly stateLabel: string;
  /** Share of the conditioned sub-population in this state. */
  readonly observed: number;
  /** Share under `do(...)`, which never disturbs an upstream root. */
  readonly intervened: number;
  /** Share in the whole population, for reference. */
  readonly population: number;
}

export interface Contrast {
  readonly variableId: VariableId;
  readonly label: string;
  readonly state: string;
  readonly stateLabel: string;
  /** P(customers_out ≥ 5% | X = x): read off the sub-population that already has X = x. */
  readonly observed: number;
  /** P(customers_out ≥ 5% | do(X = x)): the same population, X set for everyone. */
  readonly intervened: number;
  readonly gap: number;
  /** True when the two operations disagree, i.e. the variable has parents that matter. */
  readonly confounded: boolean;
  readonly mix: readonly MixRow[];
}

const MIX_TOLERANCE = 1e-9;

/**
 * Contrast conditioning on `X = x` with intervening to set it, and report why
 * they differ: the mix of upstream causes carried along by the sub-population.
 */
export function contrast(
  model: readonly Variable[],
  variableId: VariableId,
  state: string,
): Contrast {
  const variable = variableById(model, variableId);
  const stateIndex = variable.states.indexOf(state);
  if (stateIndex < 0) throw new Error(`${variableId} has no state "${state}".`);
  const intervened = intervene(model, { [variableId]: state });
  const observedRisk = outageRisk(model, { [variableId]: state });
  const interventionRisk = outageRisk(intervened);
  const mix = EXOGENOUS_IDS.filter((id) => id !== variableId).map((id) => {
    const upstream = variableById(model, id);
    // The last state of each root is its "adverse" state, which is the one the
    // section names in copy; the whole distribution is recoverable from it here
    // because every root is binary.
    const target = upstream.states[upstream.states.length - 1];
    return {
      id,
      label: upstream.label,
      state: target,
      stateLabel: upstream.stateLabels[upstream.stateLabels.length - 1],
      observed: marginal(model, id, { [variableId]: state }).probabilities[target],
      intervened: marginal(intervened, id).probabilities[target],
      population: marginal(model, id).probabilities[target],
    };
  });
  return {
    variableId,
    label: variable.label,
    state,
    stateLabel: variable.stateLabels[stateIndex],
    observed: observedRisk,
    intervened: interventionRisk,
    gap: observedRisk - interventionRisk,
    confounded: Math.abs(observedRisk - interventionRisk) > MIX_TOLERANCE,
    mix,
  };
}

export interface ClaimContrast {
  readonly id: VariableId;
  readonly claim: string;
  readonly fromState: string;
  readonly toState: string;
  /** P(out | X = to) − P(out | X = from): what a correlation reports. */
  readonly observedDifference: number;
  /** P(out | do(X = to)) − P(out | do(X = from)): what a policy would buy. */
  readonly interventionalDifference: number;
  readonly agrees: boolean;
  readonly note: string;
}

/**
 * The three claims the section puts side by side. Two of them are safe in this
 * model only because the model declares their variable to have no causes; the
 * third is confounded by construction.
 */
export function claimContrasts(model: readonly Variable[]): readonly ClaimContrast[] {
  const definitions: readonly (readonly [VariableId, string, string])[] = [
    [
      "weather_severity",
      "Storms cause outages.",
      "Weather has no parents in this graph, so the correlation and the intervention coincide — an assumption the graph makes, not something the numbers proved.",
    ],
    [
      "investment",
      "Under-invested areas have more outages.",
      "Also a root here, so the two agree. Spec 07's own honesty ledger says the real proxy (a SAIDI trend) is partly an outcome of the same weather, so this edge is the assumption doing the work.",
    ],
    [
      "line_failures",
      "Line failures put customers in the dark.",
      "Confounded: weather and investment both cause line failures and independently cause customers to lose power, so the correlation overstates what removing the failures would buy.",
    ],
  ];
  return definitions.map(([id, claim, note]) => {
    const variable = variableById(model, id);
    const fromState = variable.states[0];
    const toState = variable.states[variable.states.length - 1];
    const observedDifference =
      outageRisk(model, { [id]: toState }) - outageRisk(model, { [id]: fromState });
    const interventionalDifference =
      outageRisk(intervene(model, { [id]: toState })) -
      outageRisk(intervene(model, { [id]: fromState }));
    return {
      id,
      claim,
      fromState,
      toState,
      observedDifference,
      interventionalDifference,
      agrees: Math.abs(observedDifference - interventionalDifference) <= MIX_TOLERANCE,
      note,
    };
  });
}
