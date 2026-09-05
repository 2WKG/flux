# Reusable scenario configuration

`scenario-config-v1.schema.json` separates static network/geography references
from time-indexed demand, weather, outage, and availability inputs. It is a
configuration contract only: it does not execute a model or create a result.

All timestamps use `YYYY-MM-DDTHH:MM:SSZ`; `scripts/validate_scenario_config.py`
checks the contract keys, supported/unavailable reference pairs, real UTC
timestamps, and start/end ordering. Units stay next to every time-series or
resource quantity. Each input, including unavailable input, carries a source
URL, retrieval time, and scope.

Use a Draft 2020-12 JSON Schema validator for structural validation, then run
the Python CLI before adapter use. The CLI is the semantic gate for UTC
calendar/order checks and for blocking `ready_for_adapter` when any input or
resource capability is unavailable or unsupported.

Generation records only fuel and an evidenced ramp value. Storage records only
power (MW), energy (MWh), and state of charge (fraction). Set an unsupported
quantity to `null` with `status: "unsupported"`; adding a guessed value is not
valid evidence. A `ready_for_adapter` scenario is rejected while any input is
unavailable or any resource capability is unsupported.

The example is deliberately non-executable. It traces to 2WKG-279's September
2023 evening net-load condition and includes two dimensioned, explicitly
hypothetical demand and availability sensitivity samples. Minnesota topology,
weather, outage, and resource evidence remain unavailable. It therefore makes
no Texas-to-Minnesota transfer or historical-replay claim. PR 45's
`mn_winter_2023_snow` remains the initial Minnesota candidate; this file only
demonstrates the reusable interface.

Validate an example:

```powershell
uv run python scripts/validate_scenario_config.py configs/scenarios/examples/mn_evening_net_load_stress.json
```
