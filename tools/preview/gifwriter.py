#!/usr/bin/env python3
"""Turn a directory of PNG frames into an animated GIF, standard library only.

The Chromium bundled in this environment can rasterize SVG but only writes PNG,
and the bundled ffmpeg is a stripped Playwright build with no GIF encoder (only
libvpx). Rather than ship an animation format that cannot be checked here, this
decodes the PNGs and writes GIF89a directly: PNG inflate plus un-filtering,
frequency-based palette selection, then GIF LZW.

    python3 gifwriter.py out/anim/anim-current/png out/anim-current.gif 6
"""

from __future__ import annotations

import collections
import os
import struct
import sys
import zlib

MAX_COLOURS = 256


# ---------------------------------------------------------------------------
# PNG
# ---------------------------------------------------------------------------

def decode_png(path: str) -> tuple[int, int, bytes]:
    """Return (width, height, packed RGB bytes) for an 8-bit RGB/RGBA PNG."""
    data = open(path, "rb").read()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{path}: not a PNG")

    offset = 8
    chunks: list[bytes] = []
    width = height = colour_type = bit_depth = None
    while offset < len(data):
        (length,) = struct.unpack(">I", data[offset:offset + 4])
        kind = data[offset + 4:offset + 8]
        body = data[offset + 8:offset + 8 + length]
        if kind == b"IHDR":
            width, height, bit_depth, colour_type = struct.unpack(">IIBB", body[:10])
        elif kind == b"IDAT":
            chunks.append(body)
        elif kind == b"IEND":
            break
        offset += 12 + length

    if bit_depth != 8 or colour_type not in (2, 6):
        raise ValueError(f"{path}: need 8-bit RGB or RGBA, got "
                         f"depth={bit_depth} type={colour_type}")

    channels = 3 if colour_type == 2 else 4
    raw = zlib.decompress(b"".join(chunks))
    stride = width * channels

    out = bytearray(width * height * 3)
    previous = bytes(stride)
    position = 0
    for row_index in range(height):
        filter_type = raw[position]
        position += 1
        row = bytearray(raw[position:position + stride])
        position += stride

        if filter_type == 1:
            for i in range(channels, stride):
                row[i] = (row[i] + row[i - channels]) & 0xFF
        elif filter_type == 2:
            for i in range(stride):
                row[i] = (row[i] + previous[i]) & 0xFF
        elif filter_type == 3:
            for i in range(stride):
                left = row[i - channels] if i >= channels else 0
                row[i] = (row[i] + ((left + previous[i]) >> 1)) & 0xFF
        elif filter_type == 4:
            for i in range(stride):
                left = row[i - channels] if i >= channels else 0
                up = previous[i]
                upper_left = previous[i - channels] if i >= channels else 0
                estimate = left + up - upper_left
                da, db, dc = (abs(estimate - left), abs(estimate - up),
                              abs(estimate - upper_left))
                if da <= db and da <= dc:
                    predictor = left
                elif db <= dc:
                    predictor = up
                else:
                    predictor = upper_left
                row[i] = (row[i] + predictor) & 0xFF
        elif filter_type != 0:
            raise ValueError(f"{path}: unknown PNG filter {filter_type}")

        if channels == 3:
            out[row_index * width * 3:(row_index + 1) * width * 3] = row
        else:
            del out[row_index * width * 3:(row_index + 1) * width * 3]
            out[row_index * width * 3:row_index * width * 3] = bytes(
                b for i in range(0, stride, 4) for b in row[i:i + 3])
        previous = bytes(row)

    return width, height, bytes(out)


# ---------------------------------------------------------------------------
# Palette and quantization
# ---------------------------------------------------------------------------

def build_palette(frames: list[bytes]) -> list[tuple[int, int, int]]:
    """Most-frequent colours first. These renders use a small fixed set of inks
    plus antialiasing blends, so frequency selection is a good fit -- roughly
    1700 distinct colours per frame, dominated by two flat backgrounds."""
    counts: collections.Counter = collections.Counter()
    for rgb in frames:
        counts.update(rgb[i:i + 3] for i in range(0, len(rgb), 3))
    palette = [tuple(colour) for colour, _ in counts.most_common(MAX_COLOURS)]
    while len(palette) < MAX_COLOURS:
        palette.append((0, 0, 0))
    return palette


def quantizer(palette: list[tuple[int, int, int]]):
    """Colour -> palette index, memoized, with nearest-match for the tail."""
    lookup: dict[bytes, int] = {
        bytes(colour): index for index, colour in enumerate(palette)
    }

    def resolve(key: bytes) -> int:
        index = lookup.get(key)
        if index is not None:
            return index
        r, g, b = key[0], key[1], key[2]
        best = 0
        best_distance = 1 << 30
        for candidate, (cr, cg, cb) in enumerate(palette):
            distance = (r - cr) ** 2 + (g - cg) ** 2 + (b - cb) ** 2
            if distance < best_distance:
                best_distance, best = distance, candidate
        lookup[key] = best
        return best

    return resolve


def to_indices(rgb: bytes, width: int, resolve, row_cache: dict) -> bytes:
    """Index a frame row by row, caching whole rows.

    Large flat areas mean most rows repeat, within a frame and across frames,
    so the row cache removes the bulk of the per-pixel work.
    """
    out = bytearray()
    step = width * 3
    for start in range(0, len(rgb), step):
        row = rgb[start:start + step]
        indexed = row_cache.get(row)
        if indexed is None:
            indexed = bytes(resolve(row[i:i + 3]) for i in range(0, len(row), 3))
            row_cache[row] = indexed
        out += indexed
    return bytes(out)


# ---------------------------------------------------------------------------
# GIF
# ---------------------------------------------------------------------------

def lzw_compress(indices: bytes, code_size: int = 8) -> bytes:
    clear_code = 1 << code_size
    end_code = clear_code + 1

    bits = 0
    accumulator = 0
    packed = bytearray()

    def emit(code: int, width: int) -> None:
        nonlocal bits, accumulator
        accumulator |= code << bits
        bits += width
        while bits >= 8:
            packed.append(accumulator & 0xFF)
            accumulator >>= 8
            bits -= 8

    table: dict[bytes, int] = {}
    next_code = end_code + 1
    current_width = code_size + 1
    emit(clear_code, current_width)

    prefix = b""
    for value in indices:
        candidate = prefix + bytes((value,))
        if candidate in table or len(candidate) == 1:
            prefix = candidate
            continue
        emit(table[prefix] if len(prefix) > 1 else prefix[0], current_width)
        if next_code < 4096:
            table[candidate] = next_code
            next_code += 1
            if next_code > (1 << current_width) and current_width < 12:
                current_width += 1
        else:
            emit(clear_code, current_width)
            table.clear()
            next_code = end_code + 1
            current_width = code_size + 1
        prefix = bytes((value,))

    if prefix:
        emit(table[prefix] if len(prefix) > 1 else prefix[0], current_width)
    emit(end_code, current_width)
    if bits:
        packed.append(accumulator & 0xFF)

    blocked = bytearray()
    for start in range(0, len(packed), 255):
        piece = packed[start:start + 255]
        blocked.append(len(piece))
        blocked += piece
    blocked.append(0)
    return bytes(blocked)


def write_gif(path: str, width: int, height: int,
              palette: list[tuple[int, int, int]],
              frames: list[bytes], delay_centiseconds: int) -> None:
    with open(path, "wb") as handle:
        handle.write(b"GIF89a")
        handle.write(struct.pack("<HHBBB", width, height, 0xF7, 0, 0))
        for r, g, b in palette:
            handle.write(bytes((r, g, b)))
        # Netscape looping extension
        handle.write(b"\x21\xFF\x0BNETSCAPE2.0\x03\x01\x00\x00\x00")
        for indices in frames:
            handle.write(b"\x21\xF9\x04\x04")
            handle.write(struct.pack("<H", delay_centiseconds))
            handle.write(b"\x00\x00")
            handle.write(b"\x2C")
            handle.write(struct.pack("<HHHHB", 0, 0, width, height, 0x00))
            handle.write(bytes((8,)))
            handle.write(lzw_compress(indices))
        handle.write(b"\x3B")


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    png_dir, gif_path = sys.argv[1], sys.argv[2]
    fps = int(sys.argv[3]) if len(sys.argv) > 3 else 6

    names = sorted(n for n in os.listdir(png_dir) if n.endswith(".png"))
    if not names:
        print(f"no PNG frames in {png_dir}", file=sys.stderr)
        return 1

    print(f"decoding {len(names)} frames ...")
    width = height = None
    pixels: list[bytes] = []
    for index, name in enumerate(names):
        w, h, rgb = decode_png(os.path.join(png_dir, name))
        if width is None:
            width, height = w, h
        elif (w, h) != (width, height):
            print(f"{name}: {w}x{h} differs from {width}x{height}",
                  file=sys.stderr)
            return 1
        pixels.append(rgb)
        print(f"\r  {index + 1}/{len(names)}", end="")
    print()

    palette = build_palette(pixels)
    resolve = quantizer(palette)
    row_cache: dict = {}
    print("quantizing ...")
    indexed = [to_indices(rgb, width, resolve, row_cache) for rgb in pixels]

    delay = max(2, round(100 / fps))
    print(f"encoding {gif_path} at {fps} fps ({delay} cs/frame) ...")
    write_gif(gif_path, width, height, palette, indexed, delay)
    size = os.path.getsize(gif_path)
    print(f"done: {gif_path} ({size / 1e6:.1f} MB, {width}x{height}, "
          f"{len(indexed)} frames)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
