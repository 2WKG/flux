"""Render the neutral 512 px solar-array preview without a committed binary."""

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
            if 56 <= x <= 455 and 334 <= y <= 402:
                color = (105, 113, 117)
            if 75 <= x <= 437 and 155 <= y <= 334 and ((x // 36 + y // 32) % 2 == 0):
                color = (128, 137, 141)
            if 75 <= x <= 437 and 155 <= y <= 334 and ((x // 36 + y // 32) % 2):
                color = (154, 162, 165)
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
