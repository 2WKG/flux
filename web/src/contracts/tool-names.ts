/**
 * The runtime view of the frozen tool vocabulary.
 *
 * `copilot-tools.d.ts` is types-only, so a surface that must *decide* whether a
 * received `tool` name is a published tool needs the names at runtime. They are
 * read out of the generated `copilot-tools.schema.json` rather than re-typed
 * here: `gate/contract-drift` regenerates that file, so this list cannot drift
 * away from `copilot/tools/schemas.py`. Nothing in this module restates a tool
 * name, an input, or an output.
 *
 * WHAT IS AND IS NOT DERIVED -- read this before trusting the module name.
 * `TOOL_NAMES` and `ARTIFACT_SOURCE_KINDS` are genuinely DERIVED: they are read
 * out of the generated schema. `SIMULATION_TOOL_NAMES` is NOT derived and
 * cannot be: the frozen contract publishes no field that distinguishes a
 * scene-driving tool from any other -- every one of the 13 tools' data outputs
 * carries `provenance: ArtifactRef[]`, so there is nothing to select on. It is
 * a HAND-MAINTAINED PRODUCT STATEMENT about which published tools drive a
 * scene, and its only relation to the contract is that it is CHECKED against
 * it, two ways:
 *   - at typecheck, by the `readonly ToolName[]` annotation (an undeclared name
 *     is a TS2322 error against `copilot-tools.d.ts`), and
 *   - at module load, by `assertPublished` below, against the tool names as
 *     read from `copilot-tools.schema.json` itself.
 * Checked against the contract is a weaker claim than derived from it. Making
 * it derived would require amending the frozen contract to mark scene-driving
 * tools, which is a spec change, not a client change.
 */
import type { ArtifactRef, ToolName } from "./copilot-tools";
import schema from "./copilot-tools.schema.json";

/** Every tool the frozen contract publishes, in the generated file's order. */
export const TOOL_NAMES: readonly ToolName[] = Object.keys(
  (schema as { tools: Record<string, unknown> }).tools,
) as readonly ToolName[];

/** True when a wire-supplied tool name is one the frozen contract publishes. */
export function isToolName(value: string): value is ToolName {
  return (TOOL_NAMES as readonly string[]).includes(value);
}

/**
 * Refuse at module load if a hand-maintained name is not published by the
 * generated schema. The `readonly ToolName[]` annotations check the same thing
 * against `copilot-tools.d.ts`, but a cast or a `.d.ts`-vs-JSON drift would slip
 * past that; this reads the JSON the exporter actually wrote. Missing evidence
 * is a refusal, not a default.
 */
function assertPublished(names: readonly ToolName[]): readonly ToolName[] {
  const unpublished = names.filter((name) => !isToolName(name));
  if (unpublished.length > 0) {
    throw new Error(
      `tool-names.ts names tools the frozen contract does not publish: ${unpublished.join(", ")}` +
        ` (read from copilot-tools.schema.json, which publishes ${TOOL_NAMES.length} tools)`,
    );
  }
  return names;
}

/**
 * The published tools that run a simulation and return a scene-bearing result.
 *
 * HAND-MAINTAINED, not derived -- see the module header. The schema does not
 * express which tools drive a scene, so this set is a product statement. It is
 * checked against the contract at typecheck by the `readonly ToolName[]`
 * annotation, and again at module load by `assertPublished`.
 */
export const SIMULATION_TOOL_NAMES: readonly ToolName[] = assertPublished([
  "run_cascade",
  "score_site",
  "predict_outage",
  "compare_interventions",
]);

/** True when a received tool name is a published simulation action. */
export function isSimulationToolName(value: string): value is ToolName {
  return (SIMULATION_TOOL_NAMES as readonly string[]).includes(value);
}

/**
 * The `source_kind` values the frozen `ArtifactRef` enumerates, read out of the
 * generated schema so a wire-supplied kind can be checked at runtime without
 * re-typing the union.
 */
const ARTIFACT_SOURCE_KINDS: readonly string[] =
  ((schema as { $defs: Record<string, { properties?: { source_kind?: { enum?: readonly string[] } } }> })
    .$defs.ArtifactRef.properties?.source_kind?.enum ?? []);

/** True when a wire-supplied value is an `ArtifactRef["source_kind"]`. */
export function isArtifactSourceKind(value: string): value is ArtifactRef["source_kind"] {
  return ARTIFACT_SOURCE_KINDS.includes(value);
}
