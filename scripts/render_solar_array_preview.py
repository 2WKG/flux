"""Render the neutral 512 px solar-array preview without a committed binary."""

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
            if 56 <= x <= 455 and 334 <= y <= 402:
                color = (105, 113, 117)
            if 75 <= x <= 437 and 155 <= y <= 334 and ((x // 36 + y // 32) % 2 == 0):
                color = (128, 137, 141)
            if 75 <= x <= 437 and 155 <= y <= 334 and ((x // 36 + y // 32) % 2):
                color = (154, 162, 165)
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
