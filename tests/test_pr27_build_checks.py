from __future__ import annotations

import inspect

from pipelines import checks


def test_checks_scope_full_fixture_by_declared_source_and_reject_unknown_coordinates() -> None:
    source = inspect.getsource(checks.run_checks)
    assert "source_name = 'activsg2000'" in source
    assert "transformers == 847" in source
    assert "coord_source IS DISTINCT FROM 'tamu_aux'" in source


def test_checks_cover_each_loaded_p0_domain() -> None:
    source = inspect.getsource(checks.run_checks)
    for relation in ("storm_events", "ba_load_hourly", "critical_loads", "site_candidates"):
        assert relation in source
