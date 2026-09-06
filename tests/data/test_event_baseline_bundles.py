"""Every event bundle committed on disk is validated by the suite itself.

The root contract (2WKG-461) is only a contract if CI enforces it over
`docs/data/event-baseline/events/**`. Without this walker each hazard bundle PR
would land validated only by whoever remembered to run the CLI by hand.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
EVENTS_DIR = ROOT / "docs/data/event-baseline/events"

SPEC = importlib.util.spec_from_file_location(
    "event_baseline_validate", ROOT / "scripts/data/event_baseline_validate.py"
)
assert SPEC and SPEC.loader
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)


def committed_bundles() -> list[Path]:
    if not EVENTS_DIR.is_dir():
        return []
    return validator.iter_bundle_paths(EVENTS_DIR)


def test_events_directory_exists_as_the_walker_root() -> None:
    assert EVENTS_DIR.is_dir(), (
        f"{EVENTS_DIR} must exist so hazard bundles have a validated home"
    )


@pytest.mark.parametrize(
    "bundle_path",
    committed_bundles(),
    ids=lambda path: str(path.relative_to(EVENTS_DIR)),
)
def test_committed_bundle_satisfies_the_contract(bundle_path: Path) -> None:
    validator.load_and_validate(bundle_path)


def test_bundles_live_under_a_hazard_directory() -> None:
    misplaced = [
        path
        for path in committed_bundles()
        if path.parent == EVENTS_DIR or path.suffix != ".json"
    ]
    assert not misplaced, (
        "bundles belong in events/<hazard>/<event_id>.json, not at the events root: "
        f"{[str(path) for path in misplaced]}"
    )
