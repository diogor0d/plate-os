"""Generate placeholder PWA icons (PNG, stdlib only — no PIL required).

Run from the repo root:  python scripts/generate_icons.py
Writes frontend/public/icon-192.png, icon-512.png, apple-touch-icon.png (180px).

Design: dark #09090b plate, emerald ring, zinc dot — a stylized plate.
Replace with real artwork anytime; the filenames are referenced by the
manifest (vite.config.ts) and index.html.
"""

import struct
import zlib
from pathlib import Path

BG = (9, 9, 11)        # #09090b
RING = (52, 211, 153)  # emerald-400
DOT = (250, 250, 250)  # zinc-50


def chunk(tag: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def write_png(path: Path, size: int) -> None:
    cx = cy = (size - 1) / 2
    ring_r, ring_w = size * 0.30, size * 0.045
    dot_r = size * 0.075

    raw = bytearray()
    for y in range(size):
        raw.append(0)  # filter: none
        for x in range(size):
            d = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
            if abs(d - ring_r) <= ring_w / 2:
                color = RING
            elif d <= dot_r:
                color = DOT
            else:
                color = BG
            raw.extend(color)

    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )
    path.write_bytes(png)


def main() -> None:
    out = Path(__file__).resolve().parents[1] / "frontend" / "public"
    out.mkdir(parents=True, exist_ok=True)
    for name, size in [("icon-192.png", 192), ("icon-512.png", 512), ("apple-touch-icon.png", 180)]:
        target = out / name
        write_png(target, size)
        print(f"wrote {target}")


if __name__ == "__main__":
    main()
