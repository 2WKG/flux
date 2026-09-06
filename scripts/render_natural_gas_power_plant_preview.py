"""Render the neutral 512 px natural-gas plant preview without a committed binary."""

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
            if 74 <= x <= 438 and 348 <= y <= 405:
                color = (105, 113, 117)
            if 102 <= x <= 238 and 252 <= y <= 348:
                color = (139, 147, 150)
            if 274 <= x <= 406 and 220 <= y <= 348:
                color = (126, 135, 139)
            if 172 <= x <= 212 and 122 <= y <= 348:
                color = (90, 98, 102)
            if 326 <= x <= 362 and 151 <= y <= 348:
                color = (90, 98, 102)
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
