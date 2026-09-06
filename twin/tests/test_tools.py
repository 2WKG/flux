from __future__ import annotations

from twin.tools import run_cascade_tool


def test_tool_fails_closed_when_case_is_missing(tmp_path) -> None:
    try:
        run_cascade_tool([], "storm", 0, case_path=tmp_path / "missing.m")
    except RuntimeError as exc:
        assert "MATPOWER case is unavailable" in str(exc)
    else:  # pragma: no cover - makes the intended failure explicit
        raise AssertionError("missing case must not return a plausible cascade")
