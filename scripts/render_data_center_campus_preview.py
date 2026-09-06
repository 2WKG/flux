"""Render the neutral 512 px data-center preview without a committed binary."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.asset_contract_lib import png_bytes

SIZE = 512


def render(path: Path) -> None:
    pixels = bytearray()
    for y in range(SIZE):
        pixels.append(0)
        for x in range(SIZE):
            color = (231, 236, 238)
            if 76 <= x <= 435 and 341 <= y <= 406:
                color = (104, 113, 117)
            if 96 <= x <= 234 and 205 <= y <= 341:
                color = (137, 146, 149)
            if 278 <= x <= 416 and 244 <= y <= 341:
                color = (128, 137, 141)
            if 112 <= x <= 218 and 169 <= y <= 205:
                color = (159, 166, 169)
            if 294 <= x <= 400 and 208 <= y <= 244:
                color = (154, 162, 165)
            if 246 <= x <= 266 and 272 <= y <= 341:
                color = (86, 94, 98)
            pixels.extend((*color, 255))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png_bytes(SIZE, SIZE, bytes(pixels), 6))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    render(parser.parse_args(argv).output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
