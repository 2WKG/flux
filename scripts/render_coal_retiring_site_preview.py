"""Render the neutral 512 px coal/retiring-site preview without a committed binary."""

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
            if 68 <= x <= 443 and 337 <= y <= 405:
                color = (108, 116, 120)
            if 108 <= x <= 230 and 235 <= y <= 337:
                color = (142, 149, 151)
            if 266 <= x <= 381 and 270 <= y <= 337:
                color = (128, 136, 139)
            if 168 <= x <= 204 and 108 <= y <= 337:
                color = (92, 99, 102)
            if 323 <= x <= 356 and 151 <= y <= 337:
                color = (92, 99, 102)
            if 158 <= x <= 214 and 93 <= y <= 125:
                color = (112, 119, 122)
            if 313 <= x <= 366 and 136 <= y <= 168:
                color = (112, 119, 122)
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
