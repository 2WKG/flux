"""Render the neutral 512 px natural-gas plant preview without a committed binary."""

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
