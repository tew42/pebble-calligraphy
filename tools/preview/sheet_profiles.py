#!/usr/bin/env python3
"""Width-profile studies, drawn by the firmware's own rasterizer.

    python3 tools/preview/sheet_profiles.py && ./shot.sh profiles-kink

Track 1 asks what to do where the centerline folds back on itself near hand
overlap. Everything is rendered through `raster.render_polygons`, so a profile
built in Python is drawn by exactly the pipeline that draws the shipped one --
`check_raster.py` check 10 asserts that, and `profiles.check()` asserts the
shipped profile reproduces the compiled C to 1.4e-6 px over all 720 minutes.
"""
from __future__ import annotations

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import profiles
import raster
import sheet_workshop as W
import svgcanvas as S

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
CENTRE = (100.0, 114.0)

#: The shipped waist term saturates at delta 3.80, so it acts only below that.
#: These walk the acting band in even steps -- the clock does reach 0.5, 1.0,
#: 1.5, 2.0, 2.5 and 3.5 degrees, just not within a single hour -- plus two
#: controls past saturation, the second at the sharpest curvature of all.
#:
#: Caveat worth stating: because these are different hours, the stroke points a
#: different way in each column, so separation and orientation vary together.
#: That does not change the profile decision (curvature depends on delta and the
#: stem geometry, not heading) but it does change rasterization, since the 1 px
#: outline skips antialiasing at horizontal, vertical and exactly 45 degrees.
#: Nothing finer than 0.5 degrees exists: the face updates once a minute.
KINK_TIMES = ((12, 0), (9, 49), (7, 38), (6, 33), (8, 44),
              (10, 55), (8, 43), (9, 50), (12, 2))


def build(times, variants):
    """Render every (variant, time) cell and return frames plus diagnostics."""
    base = raster.gather(times=list(times))
    dense = raster.gather(times=list(times), overrides=profiles.DENSE)
    rows = []
    for label, fn in variants:
        specs, widths = [], []
        for frame, dframe in zip(base, dense):
            ctx = profiles.context_from(
                frame, profiles.separation_degrees(frame["hour"], frame["minute"]))
            w = fn(ctx, dframe)
            widths.append(w)
            poly = profiles.to_polygon_widths(w)
            points = [(x, y) for x, y, *_ in frame["centerline"]]
            specs.append((W.polygon_from(points, poly, W.bisector_tangents(points)),
                          [(x, y) for x, y, *_ in frame["centerline"][frame["pivot"]:]]))
        rows.append((label, raster.render_polygons(specs), widths))
    return base, rows


def overshoot(frame_buffer, centre_points, widths, width, height):
    """Worst distance any lit pixel sits beyond the half-width it was given.

    A jag at the fold shows up as ink further from the centerline than the
    profile asked for, so this measures the thing being judged rather than a
    proxy for it.
    """
    levels = raster.LEVELS
    worst = 0.0
    for y in range(height):
        row = frame_buffer[y * width:(y + 1) * width]
        for x, byte in enumerate(row):
            if not levels[byte]:
                continue
            best = min(range(len(centre_points)),
                       key=lambda i: (centre_points[i][0] - x) ** 2
                                     + (centre_points[i][1] - y) ** 2)
            d = math.hypot(centre_points[best][0] - x, centre_points[best][1] - y)
            worst = max(worst, d - widths[best] * 0.5)
    return worst


def sheet(path, title, notes, times, variants, zoom=5.0, size=170,
          rows=None, base=None):
    if base is None:
        base, rows = build(times, variants)
    label_w, gap, top = 300, 10, 104 + 15 * len(notes)
    cell_h = 228 if zoom <= 1.0 else size
    canvas = S.Canvas(label_w + len(times) * (size + gap) + 20,
                      top + len(rows) * (cell_h + gap) + 24, background=S.PAGE)
    canvas.text(24, 34, title, size=17, fill=S.LABEL, weight="600")
    for i, line in enumerate(notes):
        canvas.text(24, 56 + 15 * i, line, size=10, fill=S.DIM)

    for col, frame in enumerate(base):
        d = profiles.separation_degrees(frame["hour"], frame["minute"])
        canvas.text(label_w + col * (size + gap) + size / 2, top - 10,
                    f"{frame['hour'] % 12 or 12:02d}:{frame['minute']:02d}  "
                    f"d={d:.1f}", size=9, fill=S.LABEL, anchor="middle",
                    weight="600")

    shipped_bufs = None
    for r, (label, frames, widths) in enumerate(rows):
        y = top + r * (cell_h + gap)
        canvas.text(24, y + 16, label, size=10, fill=S.LABEL, weight="600")
        if shipped_bufs is None:
            shipped_bufs = [f["buffer"] for f in frames]
            canvas.text(24, y + 31, "(baseline for the deltas below)", size=8,
                        fill=S.DIM)
        else:
            moved = sum(sum(1 for p, q in zip(a["buffer"], b) if p != q)
                        for a, b in zip(frames, shipped_bufs))
            dw = max(max(abs(a - b) for a, b in zip(w, sw))
                     for w, sw in zip(widths, rows[0][2]))
            canvas.text(24, y + 31, f"pixels changed: {moved}", size=8,
                        fill=S.DIM if moved == 0 else "#f4d35e")
            canvas.text(24, y + 44, f"max width delta: {dw:.2f} px", size=8,
                        fill=S.DIM if dw < 0.3 else "#f4d35e")
        for col, (frame, cframe) in enumerate(zip(frames, base)):
            ox = label_w + col * (size + gap)
            W.panel(canvas, ox, y, size, cell_h, cframe, 0, zoom, frame["buffer"])
            canvas.text(ox + 4, y + cell_h - 4,
                        f"pivot w {widths[col][cframe['pivot']]:.2f}",
                        size=7, fill=S.DIM)
    os.makedirs(OUT, exist_ok=True)
    canvas.write(path)
    print("wrote", path)
    return rows


def main() -> int:
    notes = [
        "Near overlap the centerline folds back on itself. At exact overlap it is a true "
        "reversal: the path runs in along a ray and back out along the same ray.",
        "The shipped rule thins the waist by hand SEPARATION. The curvature rule thins by the "
        "local radius instead, holding w <= 2R -- the condition for the inner offset not to cusp.",
        "Measured: the sharpest point is NOT at exact overlap (where the fold is a clean "
        "reversal) but just after it, and it sits between samples, so it is taken per arc interval.",
    ]
    # Rendered once, drawn twice: the face at 1:1 to judge it as a watchface,
    # the 5x crop to see what the fold is actually doing.
    base, rows = build(KINK_TIMES, profiles.TRACK1)
    sheet(os.path.join(OUT, "profiles-kink-face.svg"),
          "Track 1. What to do where the stroke folds -- full face, 1:1",
          notes + ["Each cell is the whole 200x228 emery framebuffer at actual "
                   "size. The companion -zoom sheet is the same grid at 5x."],
          KINK_TIMES, profiles.TRACK1, zoom=1.0, size=200,
          rows=rows, base=base)
    sheet(os.path.join(OUT, "profiles-kink-zoom.svg"),
          "Track 1. What to do where the stroke folds -- fold at 5x",
          notes + ["Same grid as the -face sheet, cropped to the centre so the "
                   "fold is legible. Each square is one device pixel."],
          KINK_TIMES, profiles.TRACK1, zoom=5.0, size=170,
          rows=rows, base=base)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
