#!/usr/bin/env python3
"""List and download bounded public datasets in datasets/catalog.json."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
CATALOG_PATH = HERE / "catalog.json"
DEFAULT_OUTPUT = HERE / "raw"


def load_catalog() -> list[dict]:
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    return data["datasets"]


def human_size(value: int | None) -> str:
    if value is None:
        return "unknown"
    size = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024 or unit == "TiB":
            return f"{size:.1f} {unit}"
        size /= 1024
    raise AssertionError("unreachable")


def select(entries: list[dict], ids: list[str], group: str | None) -> list[dict]:
    by_id = {entry["id"]: entry for entry in entries}
    missing = sorted(set(ids) - set(by_id))
    if missing:
        raise SystemExit(f"Unknown dataset ID(s): {', '.join(missing)}")
    selected = [by_id[item] for item in ids]
    if group:
        selected.extend(
            entry
            for entry in entries
            if group == "all" or group in entry.get("groups", [])
        )
    if not ids and not group:
        raise SystemExit("Choose dataset IDs, --group core, or --group all.")
    return list({entry["id"]: entry for entry in selected}.values())


def print_entry(entry: dict) -> None:
    size = entry.get("estimated_bytes")
    print(
        f"{entry['id']:<32} {entry['access']:<10} "
        f"{human_size(size):>11}  {entry['name']}"
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as input_file:
        for block in iter(lambda: input_file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download_file(url: str, destination: Path, force: bool, *, expected_sha256: str | None = None,
                  attempts: int = 3) -> None:
    """Publish a complete, optionally checksum-pinned direct download.

    A ``.part`` file is never promoted. Failed attempts retain it for forensic
    inspection, while each retry starts a fresh response so an incomplete body
    cannot be mistaken for a complete artifact.
    """
    if destination.exists() and not force:
        if expected_sha256 and _sha256(destination).lower() != expected_sha256.lower():
            raise RuntimeError(f"existing file checksum differs from catalog: {destination}")
        print(f"  exists: {destination}")
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    request = urllib.request.Request(url, headers={"User-Agent": "flux-data/1.0"})
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                content_length = response.headers.get("Content-Length")
                if content_length is None:
                    raise ValueError("response omitted Content-Length; completeness cannot be verified")
                expected_bytes = int(content_length)
                with temporary.open("wb") as output:
                    shutil.copyfileobj(response, output)
            actual_bytes = temporary.stat().st_size
            if actual_bytes != expected_bytes:
                raise ValueError(f"downloaded {actual_bytes} bytes; expected {expected_bytes}")
            actual_sha256 = _sha256(temporary)
            if expected_sha256 and actual_sha256.lower() != expected_sha256.lower():
                raise ValueError("download checksum differs from catalog")
            temporary.replace(destination)
            print(f"  saved:  {destination}")
            return
        except (OSError, ValueError, urllib.error.URLError) as exc:
            if attempt == attempts:
                raise RuntimeError(f"failed to download {url}: {exc}") from exc
            time.sleep(attempt)
    raise AssertionError("unreachable")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ids", nargs="*", help="dataset IDs from catalog.json")
    parser.add_argument(
        "--group",
        choices=("core", "extended", "national", "demo-ny", "demo-tx", "all"),
    )
    parser.add_argument("--list", action="store_true", help="list catalog entries")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--include-large", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    entries = load_catalog()
    if args.list:
        for entry in entries:
            print_entry(entry)
        return 0

    chosen = select(entries, args.ids, args.group)
    failures = 0
    for entry in chosen:
        print_entry(entry)
        downloads = entry.get("downloads", [])
        if entry["access"] != "direct" or not downloads:
            print(f"  route:   {entry['source_url']}")
            continue
        if entry.get("large") and not args.include_large:
            print("  skipped: large source; pass --include-large after checking capacity")
            continue
        for item in downloads:
            target = args.output / entry["id"] / item["filename"]
            if args.dry_run:
                print(f"  would download {item['url']} -> {target}")
                continue
            try:
                download_file(item["url"], target, args.force, expected_sha256=item.get("sha256"))
            except RuntimeError as exc:
                failures += 1
                print(f"  ERROR: {exc}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
