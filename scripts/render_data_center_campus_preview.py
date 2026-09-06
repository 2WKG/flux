"""Render the neutral 512 px data-center preview without a committed binary."""

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
    png = b"\x89PNG\r\n\x1a\n" + _chunk(
        b"IHDR", struct.pack(">IIBBBBB", SIZE, SIZE, 8, 6, 0, 0, 0)
    )
    png += _chunk(b"IDAT", zlib.compress(bytes(pixels), 9)) + _chunk(b"IEND", b"")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    render(parser.parse_args().output)


if __name__ == "__main__":
    main()
