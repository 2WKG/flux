"""Render the neutral 512 px battery-storage preview without a committed binary."""

from __future__ import annotations

import argparse
import struct
import zlib
from pathlib import Path

SIZE = 512


def _chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    )


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
    png = (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", SIZE, SIZE, 8, 6, 0, 0, 0))
        + _chunk(b"IDAT", zlib.compress(bytes(pixels), 9))
        + _chunk(b"IEND", b"")
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    render(parser.parse_args().output)


if __name__ == "__main__":
    main()
