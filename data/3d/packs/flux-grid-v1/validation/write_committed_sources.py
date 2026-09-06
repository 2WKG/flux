"""Regenerate `committed-sources.SHA256SUMS`, the pack's *in-repo* inventory.

`package.SHA256SUMS` is the inventory of the downloaded binary archive: 178 lines
naming bytes this repository does not contain and cannot fetch, so nothing here
can ever falsify one of them. This file is the opposite: it pins the sha256 of
every file the pack actually commits, and `web/test/flux-grid-install.test.mjs`
re-hashes each one, so a changed byte or an added/removed file is red.

Run it after editing anything under `data/3d/packs/flux-grid-v1/`:

    uv run --extra dev python \\
        data/3d/packs/flux-grid-v1/validation/write_committed_sources.py
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

PACK = Path(__file__).resolve().parents[1]
INVENTORY = PACK / "committed-sources.SHA256SUMS"


def committed_files(pack: Path = PACK) -> list[Path]:
    """Every tracked-shaped file under the pack, except the inventory itself.

    `__pycache__` and dotfiles are build residue, not committed sources; listing
    them would make the inventory drift on a bare test run rather than on a real
    edit, which is the failure that teaches a reader to ignore this file.
    """
    files = [
        path
        for path in sorted(pack.rglob("*"))
        if path.is_file()
        and path != INVENTORY
        and "__pycache__" not in path.parts
        and not any(part.startswith(".") for part in path.relative_to(pack).parts)
    ]
    if not files:
        raise SystemExit(f"no committed pack files found under {pack}")
    return files


def line(path: Path, pack: Path = PACK) -> str:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return f"{digest}  {path.relative_to(pack).as_posix()}"


def render(pack: Path = PACK) -> str:
    return "".join(f"{line(path, pack)}\n" for path in committed_files(pack))


def main(argv: list[str] | None = None) -> int:
    text = render()
    if argv and argv[0] == "--check":
        current = INVENTORY.read_text(encoding="utf-8") if INVENTORY.is_file() else ""
        if current != text:
            print(f"{INVENTORY} is stale; rerun without --check", file=sys.stderr)
            return 1
        return 0
    INVENTORY.write_text(text, encoding="utf-8")
    print(f"wrote {len(text.splitlines())} entries to {INVENTORY}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
