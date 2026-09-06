/**
 * The runtime view of the frozen tool vocabulary.
 *
 * `copilot-tools.d.ts` is types-only, so a surface that must *decide* whether a
 * received `tool` name is a published tool needs the names at runtime. They are
 * read out of the generated `copilot-tools.schema.json` rather than re-typed
 * here: `gate/contract-drift` regenerates that file, so this list cannot drift
 * away from `copilot/tools/schemas.py`. Nothing in this module restates a tool
 * name, an input, or an output.
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
 * The published tools that run a simulation and return a scene-bearing result.
 * Each is a member of `ToolName`, checked by the type annotation below; the set
 * is a product statement about which published tools drive a scene, which the
 * schema does not itself express.
 */
export const SIMULATION_TOOL_NAMES: readonly ToolName[] = [
  "run_cascade",
  "score_site",
  "predict_outage",
  "compare_interventions",
];

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
