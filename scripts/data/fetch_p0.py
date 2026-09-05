#!/usr/bin/env python3
"""Fetch P0 artifacts without promoting incomplete downloads."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import asdict, dataclass
from http.client import IncompleteRead
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

REGISTRY = Path(__file__).resolve().parents[2] / "data" / "sources" / "p0_registry.json"
_CONTENT_RANGE = re.compile(r"bytes (\d+)-(\d+)/(\d+)$")


@dataclass(frozen=True)
class Artifact:
    id: str
    source: str
    release: str
    path: str
    url: str
    large: bool = False


class DownloadValidationError(RuntimeError):
    """A response could not prove that the artifact is complete."""


def load_artifacts(registry: Path = REGISTRY) -> tuple[Artifact, ...]:
    data = json.loads(registry.read_text())
    return tuple(
        Artifact(**{key: value for key, value in item.items() if key in Artifact.__dataclass_fields__})
        for item in data["artifacts"]
        if item.get("url")
    )


ARTIFACTS = load_artifacts()


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def _verified_existing(artifact: Artifact, target: Path, known: dict[str, object] | None) -> dict[str, object] | None:
    if not target.exists() or not known:
        return None
    if known.get("url") != artifact.url or known.get("expected_bytes") != target.stat().st_size:
        return None
    actual = digest(target)
    if known.get("sha256") != actual:
        return None
    return {**asdict(artifact), "path": str(target), "bytes": target.stat().st_size,
            "expected_bytes": target.stat().st_size, "sha256": actual, "status": "existing"}


def _download_once(artifact: Artifact, target: Path, partial: Path) -> int:
    start = partial.stat().st_size if partial.exists() else 0
    headers = {"User-Agent": "flux-data-ingest/1.0"}
    if start:
        headers["Range"] = f"bytes={start}-"
    with urlopen(Request(artifact.url, headers=headers), timeout=60) as response:
        content_range = response.headers.get("Content-Range", "")
        match = _CONTENT_RANGE.fullmatch(content_range)
        append = start > 0 and response.status == 206 and match is not None and int(match.group(1)) == start
        content_length = response.headers.get("Content-Length")
        if append:
            expected = int(match.group(3))
        elif content_length is not None:
            expected = int(content_length)
        else:
            raise DownloadValidationError("response omitted Content-Length and Content-Range")
        with partial.open("ab" if append else "wb") as output:
            while block := response.read(1024 * 1024):
                output.write(block)
    actual = partial.stat().st_size
    if actual != expected:
        raise DownloadValidationError(f"downloaded {actual} bytes; expected {expected}")
    partial.replace(target)
    return expected


def download(artifact: Artifact, root: Path, known: dict[str, object] | None = None, attempts: int = 3) -> dict[str, object]:
    target = root / artifact.path
    target.parent.mkdir(parents=True, exist_ok=True)
    if existing := _verified_existing(artifact, target, known):
        return existing
    partial = target.with_name(f"{target.name}.part")
    # An unverified target may be a legacy partial download.  Re-fetch it into
    # the custody file rather than treating its local hash as source evidence.
    if target.exists():
        target.replace(partial)
    for attempt in range(1, attempts + 1):
        try:
            expected = _download_once(artifact, target, partial)
            return {**asdict(artifact), "path": str(target), "bytes": expected,
                    "expected_bytes": expected, "sha256": digest(target), "status": "downloaded"}
        except (DownloadValidationError, IncompleteRead, OSError, URLError):
            if attempt == attempts:
                raise
    raise AssertionError("unreachable")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-dir", default="data/raw")
    parser.add_argument("--source", action="append", choices=sorted({item.source for item in ARTIFACTS}))
    parser.add_argument("--include-large", action="store_true")
    args = parser.parse_args()
    selected = [item for item in ARTIFACTS if (not args.source or item.source in args.source)]
    selected = [item for item in selected if args.include_large or not item.large]
    output = Path(args.raw_dir) / "fetch_manifest_p0.json"
    existing: dict[str, dict[str, object]] = {}
    if output.exists():
        try:
            existing = {str(item["path"]): item for item in json.loads(output.read_text())}
        except (json.JSONDecodeError, KeyError, TypeError):
            pass
    manifest = existing
    for artifact in selected:
        print(f"fetching {artifact.id}", file=sys.stderr)
        result = download(artifact, Path(args.raw_dir), manifest.get(str(Path(args.raw_dir) / artifact.path)))
        manifest[str(result["path"])] = result
    output.write_text(json.dumps(sorted(manifest.values(), key=lambda item: str(item["path"])), indent=2) + "\n")
    print(f"wrote {output} ({len(manifest)} artifacts)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
