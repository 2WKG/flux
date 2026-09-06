# Generated Copilot tool contracts

`copilot-tools.schema.json` and `copilot-tools.d.ts` are **generated** from
`copilot/tools/schemas.py`. Do not hand-edit them; edit the pydantic models and
regenerate:

```sh
uv run --extra dev python scripts/ci/export_tool_contracts.py
```

`gate/contract-drift` in CI reruns the export and fails if the committed files
differ, so a schema change cannot merge without its mirror. Import the types
from `web/src/contracts/copilot-tools` instead of re-declaring them in panel
code.

## `tool-names.ts` is hand-written, and is *not* an exporter output

`tool-names.ts` is the one file in this directory that is **not** generated.
`scripts/ci/export_tool_contracts.py` writes only its own two named outputs and
deletes nothing, so regenerating never clobbers it and it never shows as drift.

It is the runtime view of the vocabulary: `TOOL_NAMES` and the `ArtifactRef`
`source_kind` values are **read out of** `copilot-tools.schema.json`, so they
cannot drift from the pydantic models. `SIMULATION_TOOL_NAMES` is different --
it is a hand-maintained product statement about which published tools drive a
scene, because the frozen contract publishes no field that distinguishes them.
It is *checked against* the contract (typecheck against `copilot-tools.d.ts`,
plus a module-load assertion against the schema JSON), not derived from it.
