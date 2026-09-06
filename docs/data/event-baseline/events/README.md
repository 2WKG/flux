# Event bundles

One directory per hazard, one JSON bundle per event:

```text
docs/data/event-baseline/events/<hazard>/<event_id>.json
```

Every `*.json` under this tree is validated by
`tests/data/test_event_baseline_bundles.py` against
`docs/data/event-baseline/event_baseline.schema.json` and the cross-field rules
in `scripts/data/event_baseline_validate.py`. A bundle committed here is
therefore validated by `gate/pytest`, not by whoever remembers to run the CLI.

Read `../README.md` for the contract itself before adding a bundle.
