"""Generate PlateOS PWA icons (PNG, stdlib only — no PIL required).

Run from the repo root:  python scripts/generate_icons.py
Writes frontend/public/icon-192.png, icon-512.png, apple-touch-icon.png (180px).

Design: the Plate Prompt mark — a zinc dish containing an emerald command
prompt. The filenames are referenced by the manifest and index.html.
"""

import struct
import zlib
from pathlib import Path

BG = (9, 9, 11)            # zinc-950
RIM = (113, 113, 122)      # zinc-500
DISH = (228, 228, 231)     # zinc-200
PROMPT = (52, 211, 153)    # emerald-400


def chunk(tag: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    )


def segment_distance(
    x: float, y: float, ax: float, ay: float, bx: float, by: float
) -> float:
    dx, dy = bx - ax, by - ay
    length_squared = dx * dx + dy * dy
    if length_squared == 0:
        return ((x - ax) ** 2 + (y - ay) ** 2) ** 0.5
    position = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / length_squared))
    px, py = ax + position * dx, ay + position * dy
    return ((x - px) ** 2 + (y - py) ** 2) ** 0.5


def mark_color(x: float, y: float) -> tuple[int, int, int] | None:
    # Coordinates match logo.svg's 64 x 64 viewBox.
    if segment_distance(x, y, 10, 22, 54, 22) <= 1.5:
        return RIM

    # Lower half of an ellipse approximates the bowl's cubic outline.
    if y >= 23:
        ellipse_distance = abs((((x - 32) / 22) ** 2 + ((y - 22) / 30) ** 2) ** 0.5 - 1) * 22
        if ellipse_distance <= 2:
            return DISH

    prompt_segments = (
        (20, 31, 27, 37),
        (27, 37, 20, 43),
        (34, 43, 44, 43),
    )
    if min(segment_distance(x, y, *segment) for segment in prompt_segments) <= 2:
        return PROMPT
    return None


def write_png(path: Path, size: int) -> None:
    samples = 3

    raw = bytearray()
    for y in range(size):
        raw.append(0)  # filter: none
        for x in range(size):
            accumulated = [0, 0, 0]
            for sy in range(samples):
                for sx in range(samples):
                    mark_x = (x + (sx + 0.5) / samples) * 64 / size
                    mark_y = (y + (sy + 0.5) / samples) * 64 / size
                    color = mark_color(mark_x, mark_y) or BG
                    for channel in range(3):
                        accumulated[channel] += color[channel]
            divisor = samples * samples
            raw.extend(round(value / divisor) for value in accumulated)

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
