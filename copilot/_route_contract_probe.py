"""Pytest plugin that records which API routes a test actually exercised.

``copilot/test_read_route_contracts.py`` uses this to prove that the test it
files under a route/state cell really drives *that* route into *that* state.
Loaded with ``-p copilot._route_contract_probe`` in a subprocess run; it writes
``{node id: [[method, route template, status], ...]}`` to the JSON file named by
``FLUX_ROUTE_PROBE_OUT``.

The recording seam is :func:`copilot.app.create_app`: every app the referenced
tests build gets an HTTP middleware that appends the matched route template and
the response status.  A test that stops issuing requests, or that issues them
against a different route, records nothing for its cell.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI, Request

import copilot.app as app_module

_CALLS: list[tuple[str, str, int]] = []
_BY_NODE: dict[str, list[tuple[str, str, int]]] = {}
_ORIGINAL_CREATE_APP = app_module.create_app


def _instrument(app: FastAPI) -> FastAPI:
    @app.middleware("http")
    async def _record(request: Request, call_next: Any) -> Any:
        response = await call_next(request)
        route = request.scope.get("route")
        template = getattr(
            route, "path_format", getattr(route, "path", request.url.path)
        )
        _CALLS.append((request.method.upper(), template, response.status_code))
        return response

    return app


def _create_app(*args: Any, **kwargs: Any) -> FastAPI:
    return _instrument(_ORIGINAL_CREATE_APP(*args, **kwargs))


app_module.create_app = _create_app  # type: ignore[assignment]


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(
    item: pytest.Item, nextitem: pytest.Item | None
) -> Iterator[None]:
    start = len(_CALLS)
    yield
    _BY_NODE.setdefault(item.nodeid, []).extend(_CALLS[start:])


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    destination = os.environ.get("FLUX_ROUTE_PROBE_OUT")
    if not destination:
        return
    Path(destination).write_text(
        json.dumps({node: calls for node, calls in _BY_NODE.items()}),
        encoding="utf-8",
    )
