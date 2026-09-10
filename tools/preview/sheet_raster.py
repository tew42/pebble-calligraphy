#!/usr/bin/env python3
"""The watchface as the watch draws it: real pixels, four grey levels.

    python3 tools/preview/sheet_raster.py && ./shot.sh raster-face

Six representative hand positions at 1:1, then the two hardest ones magnified
so the pixel grid and the coverage levels are legible.  Every pixel here came
out of the firmware's own rasterizer (vendor/pebbleos) driven by the geometry
compiled out of main.c, so this is the first sheet in this directory that shows
what the display will actually contain rather than a vector approximation of it.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import raster
import svgcanvas as S

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")

# Overlap, the reversing turn, a right angle, opposition, and two ordinary
# positions -- the same spread the vector sheets use, so they can be compared.
TIMES = ((12, 0), (1, 5), (10, 10), (3, 0), (6, 33), (7, 38))
ZOOMS = ((12, 0), (10, 10))


def census_line(frame):
    black, third, twothird, white = frame["census"]
    return (f"ink {third + twothird + white}   "
            f"solid {white}   2/3 {twothird}   1/3 {third}")


def main() -> int:
    frames = raster.gather(times=TIMES + ZOOMS)
    by_time = {(f["hour"], f["minute"]): f for f in frames}

    pad, gap, label = 26, 18, 34
    width, height = frames[0]["width"], frames[0]["height"]
    columns = 3
    rows_of_faces = 2

    zoom = 3.0
    crop = 76                      # px of framebuffer shown in the zoom panels
    zoom_w = crop * zoom

    sheet_w = pad * 2 + columns * width + (columns - 1) * gap
    top = pad + label + 16
    faces_h = rows_of_faces * (height + label) + (rows_of_faces - 1) * gap
    zoom_top = top + faces_h + gap * 2 + 28
    sheet_h = zoom_top + zoom_w + label + pad + 20

    canvas = S.Canvas(sheet_w, sheet_h, background=S.PAGE)
    canvas.text(pad, pad + 12, "Calligraphy, rasterized by the firmware itself",
                size=15, weight="600")
    canvas.text(pad, pad + 30,
                "emery 200x228, one byte per pixel, four coverage levels. "
                "Fill + antialiased outline + hard minute core.",
                size=10, fill=S.DIM)

    for index, key in enumerate(TIMES):
        frame = by_time[key]
        column, row = index % columns, index // columns
        x = pad + column * (width + gap)
        y = top + row * (height + label + gap)
        canvas.rect(x, y, width, height, fill="#000000")
        canvas.pixels(x, y, raster.as_levels(frame), scale=1.0)
        canvas.rect(x - 0.5, y - 0.5, width + 1, height + 1,
                    fill="none", stroke=S.GUIDE, stroke_width=1.0)
        canvas.text(x, y + height + 14,
                    f"{key[0]:02d}:{key[1]:02d}", size=11, weight="600")
        canvas.text(x, y + height + 27, census_line(frame), size=9, fill=S.DIM)

    canvas.text(pad, zoom_top - 34,
                f"the same frames at {zoom:g}x, centre {crop}x{crop} px -- "
                "each square is one device pixel", size=11, weight="600")
    canvas.text(pad, zoom_top - 19,
                "greys are the only two intermediate levels the hardware has: "
                "one third and two thirds coverage", size=9, fill=S.DIM)

    for index, key in enumerate(ZOOMS):
        frame = by_time[key]
        levels = raster.as_levels(frame)
        x0 = (width - crop) // 2
        y0 = (height - crop) // 2
        window = [row[x0:x0 + crop] for row in levels[y0:y0 + crop]]
        x = pad + index * (zoom_w + gap * 2)
        canvas.rect(x, zoom_top, zoom_w, zoom_w, fill="#000000")
        canvas.pixels(x, zoom_top, window, scale=zoom, gap=0.35)
        canvas.rect(x - 0.5, zoom_top - 0.5, zoom_w + 1, zoom_w + 1,
                    fill="none", stroke=S.GUIDE, stroke_width=1.0)
        canvas.text(x, zoom_top + zoom_w + 15,
                    f"{key[0]:02d}:{key[1]:02d}", size=11, weight="600")

    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, "raster-face.svg")
    canvas.write(path)
    print(f"wrote {path}  ({sheet_w:.0f}x{sheet_h:.0f})")
    for key in TIMES:
        print(f"  {key[0]:02d}:{key[1]:02d}  {census_line(by_time[key])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
