/**
 * The browser half of the merged `POST /ask` contract.
 *
 * Every shape and bound here mirrors `copilot/routes/ask.py` (lines 24-66 on
 * `master`): `AskContext` is `extra="forbid"`, so a field this file invents is
 * a guaranteed 422, and the length/range bounds are the server's own. The dock
 * builds the exact body it would post and refuses to hand the caller one the
 * server would reject.
 */

/** `AskContext` — copilot/routes/ask.py:24-41. Every field is optional server-side. */
export type SceneContext = {
  /** Current application region, supplied by the primary navigation. */
  region: "texas" | "minnesota" | null;
  /** Current reviewed historical county FIPS, when the selected artifact supplied one. */
  county_fips: string | null;
  /** Scene identity; model actions are valid only in the separate Texas model mode. */
  view_mode: "physical_inventory" | "texas_model" | null;
  /** `scenario_id: str | None`, 1..128 chars. */
  scenario_id: string | null;
  /** `hour: int | None`, 0..167. */
  hour: number | null;
  /** `selected_site_id: str | None`, 1..128 chars. */
  selected_site_id: string | null;
  /** `compare_site_id: str | None`, 1..128 chars. */
  compare_site_id: string | null;
  /** `selected_element_id: str | None`, 1..128 chars. */
  selected_element_id: string | null;
  /** `unit_mw: int | None`, validated to exactly 300 or 1000. */
  unit_mw: 300 | 1000 | null;
};

/** `AskHistoryMessage` — copilot/routes/ask.py:44-49. */
export type AskHistoryMessage = { role: "user" | "assistant"; content: string };

/** The wire body of `AskRequest` — copilot/routes/ask.py:52-66. */
export type AskRequestBody = {
  attempt_id: string;
  question: string;
  context?: Partial<SceneContext>;
  history: AskHistoryMessage[];
};

/** The server's own bounds, restated so a violation is caught before the request. */
export const ASK_LIMITS = {
  attemptIdMin: 16,
  attemptIdMax: 128,
  /** `_ATTEMPT_ID_RE` — copilot/routes/ask.py:20. */
  attemptIdPattern: /^[A-Za-z0-9_-]{16,128}$/,
  questionMin: 1,
  questionMax: 2_000,
  idMin: 1,
  idMax: 128,
  hourMin: 0,
  hourMax: 167,
  unitMwChoices: [300, 1000] as const,
  historyMax: 6,
  historyContentMin: 1,
  historyContentMax: 4_000,
} as const;

export const EMPTY_SCENE_CONTEXT: SceneContext = {
  region: null,
  county_fips: null,
  view_mode: null,
  scenario_id: null,
  hour: null,
  selected_site_id: null,
  compare_site_id: null,
  selected_element_id: null,
  unit_mw: null,
};

/** The scene-context field order the dock displays and edits. */
export const SCENE_CONTEXT_FIELDS = [
  ["region", "Region"],
  ["county_fips", "County FIPS"],
  ["view_mode", "View mode"],
  ["scenario_id", "Scenario"],
  ["hour", "Hour"],
  ["selected_site_id", "Selected site"],
  ["compare_site_id", "Compare site"],
  ["selected_element_id", "Selected element"],
  ["unit_mw", "Unit size (MW)"],
] as const;

export type AskRequestResult =
  | { ok: true; body: AskRequestBody }
  | { ok: false; problems: string[] };

function checkId(value: string | null, field: string, problems: string[]) {
  if (value === null) return;
  if (value.length < ASK_LIMITS.idMin || value.length > ASK_LIMITS.idMax) {
    problems.push(`${field} must be ${ASK_LIMITS.idMin}-${ASK_LIMITS.idMax} characters`);
  }
}

/** Drop nulls: the server defaults every context field to None, and never accepts an unknown key. */
export function askContextPayload(context: SceneContext): Partial<SceneContext> | undefined {
  const payload: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(context)) {
    if (value !== null && value !== "") payload[key] = value;
  }
  return Object.keys(payload).length ? (payload as Partial<SceneContext>) : undefined;
}

/**
 * Build the exact `POST /ask` body, or report every bound the caller broke.
 * Nothing here guesses a value: a violation is returned, never silently trimmed.
 */
export function buildAskRequest(input: {
  attemptId: string;
  question: string;
  context: SceneContext;
  history: AskHistoryMessage[];
}): AskRequestResult {
  const problems: string[] = [];
  const question = input.question.trim();

  if (!ASK_LIMITS.attemptIdPattern.test(input.attemptId)) {
    problems.push(`attempt_id must be ${ASK_LIMITS.attemptIdMin}-${ASK_LIMITS.attemptIdMax} URL-safe ASCII characters`);
  }
  if (question.length < ASK_LIMITS.questionMin) problems.push("question must not be empty");
  if (question.length > ASK_LIMITS.questionMax) {
    problems.push(`question must be at most ${ASK_LIMITS.questionMax} characters (it is ${question.length})`);
  }

  const { hour, unit_mw: unitMw } = input.context;
  if (hour !== null && (!Number.isInteger(hour) || hour < ASK_LIMITS.hourMin || hour > ASK_LIMITS.hourMax)) {
    problems.push(`hour must be a whole number from ${ASK_LIMITS.hourMin} to ${ASK_LIMITS.hourMax}`);
  }
  if (unitMw !== null && !ASK_LIMITS.unitMwChoices.includes(unitMw)) {
    problems.push(`unit_mw must be ${ASK_LIMITS.unitMwChoices.join(" or ")}`);
  }
  checkId(input.context.scenario_id, "scenario_id", problems);
  checkId(input.context.selected_site_id, "selected_site_id", problems);
  checkId(input.context.compare_site_id, "compare_site_id", problems);
  checkId(input.context.selected_element_id, "selected_element_id", problems);
  if (input.context.county_fips !== null && !/^\d{5}$/.test(input.context.county_fips)) {
    problems.push("county_fips must be exactly five digits");
  }

  if (input.history.length > ASK_LIMITS.historyMax) {
    problems.push(`history must be at most ${ASK_LIMITS.historyMax} messages (it is ${input.history.length})`);
  }
  for (const message of input.history) {
    if (message.content.length < ASK_LIMITS.historyContentMin || message.content.length > ASK_LIMITS.historyContentMax) {
      problems.push(`history content must be ${ASK_LIMITS.historyContentMin}-${ASK_LIMITS.historyContentMax} characters`);
      break;
    }
  }

  if (problems.length) return { ok: false, problems };
  const context = askContextPayload(input.context);
  return {
    ok: true,
    body: { attempt_id: input.attemptId, question, ...(context ? { context } : {}), history: input.history },
  };
}
