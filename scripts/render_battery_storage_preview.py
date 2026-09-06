"""Render the neutral 512 px battery-storage preview without a committed binary."""

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
            color = (232, 236, 238)
            if 62 <= x <= 450 and 342 <= y <= 402:
                color = (105, 113, 117)
            if 82 <= x <= 430 and 227 <= y <= 342:
                color = (132, 141, 145)
            if 245 <= y <= 324 and (
                105 <= x <= 143 or 188 <= x <= 226 or 271 <= x <= 309 or 354 <= x <= 392
            ):
                color = (163, 170, 173)
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
