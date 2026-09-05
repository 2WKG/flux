from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from pipelines.state_scope import parse_states


def _fetch_context_module():
    path = Path(__file__).parents[1] / "scripts" / "data" / "fetch_context.py"
    spec = importlib.util.spec_from_file_location("fetch_context", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_parse_states_normalizes_a_multi_state_request() -> None:
    assert parse_states(["tx, ok", "NM", "TX"]) == ("TX", "OK", "NM")


def test_parse_states_rejects_non_postal_values() -> None:
    with pytest.raises(ValueError, match="two-letter"):
        parse_states(["Texas"])


def test_fetch_context_writes_one_dod_artifact_per_requested_state(tmp_path: Path, monkeypatch) -> None:
    fetch_context = _fetch_context_module()
    calls: list[tuple[str, Path, str]] = []
    monkeypatch.setattr(fetch_context, "save", lambda url, path, user_agent: calls.append((url, path, user_agent)))
    monkeypatch.setattr(sys, "argv", ["fetch_context.py", "--raw-dir", str(tmp_path), "--states", "TX,OK", "--dod"])

    assert fetch_context.main() == 0
    assert [path.name for _, path, _ in calls] == ["TX.geojson", "OK.geojson"]
    assert all("stateNameCode%3D%27" + state.lower() + "%27" in url for (url, _, _), state in zip(calls, ("TX", "OK"), strict=True))
