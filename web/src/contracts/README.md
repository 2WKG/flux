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
