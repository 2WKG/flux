from __future__ import annotations

import importlib.util
import sys
from io import BytesIO
from pathlib import Path

import pytest


def _fetch_module():
    path = Path(__file__).parents[1] / "scripts" / "data" / "fetch_p0.py"
    spec = importlib.util.spec_from_file_location("fetch_p0", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _Response(BytesIO):
    def __init__(self, payload: bytes, headers: dict[str, str], status: int = 200):
        super().__init__(payload)
        self.headers = headers
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def test_short_response_stays_in_partial_custody(tmp_path, monkeypatch) -> None:
    fetch = _fetch_module()
    artifact = fetch.Artifact("fixture", "test", "v1", "fixture.bin", "https://example.test/fixture")
    monkeypatch.setattr(fetch, "urlopen", lambda *_args, **_kwargs: _Response(b"short", {"Content-Length": "10"}))

    with pytest.raises(fetch.DownloadValidationError, match="expected 10"):
        fetch.download(artifact, tmp_path, attempts=1)

    assert not (tmp_path / "fixture.bin").exists()
    assert (tmp_path / "fixture.bin.part").read_bytes() == b"short"


def test_retry_resumes_and_promotes_only_the_verified_total(tmp_path, monkeypatch) -> None:
    fetch = _fetch_module()
    artifact = fetch.Artifact("fixture", "test", "v1", "fixture.bin", "https://example.test/fixture")
    responses = iter((
        _Response(b"short", {"Content-Length": "10"}),
        _Response(b"-file", {"Content-Range": "bytes 5-9/10", "Content-Length": "5"}, status=206),
    ))
    monkeypatch.setattr(fetch, "urlopen", lambda *_args, **_kwargs: next(responses))

    result = fetch.download(artifact, tmp_path, attempts=2)

    assert (tmp_path / "fixture.bin").read_bytes() == b"short-file"
    assert result["expected_bytes"] == 10
    assert not (tmp_path / "fixture.bin.part").exists()
