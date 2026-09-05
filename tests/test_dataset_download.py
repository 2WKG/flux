from __future__ import annotations

import hashlib
from io import BytesIO
from typing import Self

import pytest

from datasets import download


class _Response:
    def __init__(self, payload: bytes, content_length: int | None) -> None:
        self._payload = BytesIO(payload)
        self.headers = {} if content_length is None else {"Content-Length": str(content_length)}

    def read(self, size: int = -1) -> bytes:
        return self._payload.read(size)

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        self._payload.close()


def test_download_retries_a_truncated_response_without_promoting_it(tmp_path, monkeypatch) -> None:
    responses = iter([_Response(b"short", 7), _Response(b"complete", 8)])
    monkeypatch.setattr(download.urllib.request, "urlopen", lambda *_args, **_kwargs: next(responses))
    monkeypatch.setattr(download.time, "sleep", lambda *_args: None)
    destination = tmp_path / "artifact.csv"

    download.download_file("https://example.test/artifact.csv", destination, force=False, attempts=2)

    assert destination.read_bytes() == b"complete"
    assert not destination.with_suffix(".csv.part").exists()


def test_download_rejects_checksum_mismatch_without_promoting(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(download.urllib.request, "urlopen", lambda *_args, **_kwargs: _Response(b"complete", 8))
    destination = tmp_path / "artifact.csv"

    with pytest.raises(RuntimeError, match="checksum"):
        download.download_file("https://example.test/artifact.csv", destination, force=False,
                               expected_sha256=hashlib.sha256(b"different").hexdigest(), attempts=1)

    assert not destination.exists()
    assert destination.with_suffix(".csv.part").read_bytes() == b"complete"
