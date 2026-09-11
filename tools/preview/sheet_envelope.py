#!/usr/bin/env python3
"""Draw the stroke the watchface actually fills, straight out of main.c.

    python3 tools/preview/sheet_envelope.py

Everything else in this directory models the *centerline*; the README says so
deliberately, because the stroke was not under discussion.  It is now, so this
compiles `build_centerline` and `build_stroke_polygon` out of `main.c` (same
trick as check_c_build.py) and renders the resulting `s_polygon_points` as a
filled outline.  What is on the sheet is what the watch draws, not a re-port of
it.

The watchface draws in three passes, and all three are here, because the first
one alone is misleading: the fill is inset by OUTLINE_WIDTH_COMPENSATION so that
the antialiased outline pass puts the pixel back, which means the composite ink
extent is the width profile and the *fill* is one pixel narrower.  At the minute
tip the profile is 1 px, so the fill has zero width there and the minute hand is
carried entirely by the outline and by the hard one-pixel core line.

Two failure modes of an offset curve are marked, because both turn out to be
live near overlap:

  cusp       half the stroke width exceeds the local radius of curvature, so
             the inner offset inverts and the polygon stops being simple
  collision  two non-adjacent parts of the stroke are closer together than
             their widths allow, so they merge

Neither is necessarily wrong -- at overlap the design *wants* a fold that
overlaps itself -- but both extend a good deal further from overlap than the
term meant to control them does.

Needs a C compiler.
"""
from __future__ import annotations

import math
import os
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import svgcanvas as S

MAIN_C = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "..", "..", "src", "c", "main.c")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")

TIMES = ((12, 0), (12, 1), (12, 2), (12, 3), (12, 4),
         (12, 5), (12, 7), (12, 12), (3, 0), (10, 10))

STUB = r"""
#include <stdio.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdlib.h>
#include <math.h>
#include <time.h>
#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif
#define TRIG_MAX_ANGLE 0x10000
#define TRIG_MAX_RATIO 0xffff
typedef struct { int16_t x, y; } GPointStorage;
#define GPoint(a, b) ((GPointStorage){ (int16_t)(a), (int16_t)(b) })
typedef GPointStorage GPoint;
typedef struct { int16_t w, h; } GSize;
typedef struct { GPointStorage origin; GSize size; } GRect;
typedef struct Layer Layer;
typedef struct Window Window;
typedef struct GPath GPath;
typedef struct { uint32_t num_points; GPoint *points; } GPathInfo;
static int32_t sin_lookup(int32_t a) {
  return (int32_t)(sin((double)a * 2.0 * M_PI / TRIG_MAX_ANGLE)
                   * TRIG_MAX_RATIO);
}
static int32_t cos_lookup(int32_t a) {
  return (int32_t)(cos((double)a * 2.0 * M_PI / TRIG_MAX_ANGLE)
                   * TRIG_MAX_RATIO);
}
"""

DRIVER = r"""
int main(void) {
  initialize_solver_workspace();
  const Vec2 center = make_vec2(100.0f, 114.0f);
  int hour, minute;
  while (scanf("%d %d", &hour, &minute) == 2) {
    const CenterlineResult r = build_centerline(
      center, 100.0f,
      hour_to_pebble_angle(hour, minute),
      minute_to_pebble_angle(minute));
    /* Arc lengths first so the T line can carry the total, then the polygon,
       whose own loop prints the C lines.  update_cumulative_lengths is
       idempotent, so build_stroke_polygon repeating it is harmless. */
    update_cumulative_lengths();
    printf("T %d %d %u %.6f %.6f\n",
           hour, minute, r.pivot_index,
           s_cumulative_length[CENTERLINE_POINT_COUNT - 1],
           r.waist_opening);

    build_stroke_polygon(r.pivot_index, r.waist_opening);
    for (int i = 0; i < POLYGON_POINT_COUNT; ++i) {
      printf("P %d %d %d\n", i, s_polygon_points[i].x, s_polygon_points[i].y);
    }
  }
  return 0;
}
"""


def build(directory, overrides=None, patches=None, stub=None, driver=None,
          name="envelope", cflags=(), sources=(), ldflags=("-lm",)):
    """Extract the geometry half of main.c, optionally altered, and compile it.

    `stub` and `driver` default to the ones above, which fake just enough of
    the Pebble types to compile the geometry standalone.  `raster.py` passes its
    own pair instead, so the same extraction -- same overrides, same patches --
    can be linked against the real firmware rasterizer rather than fake types.
    Everything below this docstring is shared, so an experiment behaves
    identically whichever way it is rendered.

    `overrides` maps a `#define` name to a replacement value; the define line is
    rewritten in the *extracted copy*.  `-Dname=value` will not do: the defines
    are unguarded, so the command line would collide with them.

    `patches` is a list of (old, new) text substitutions, for the questions that
    need a different function body rather than a different constant.  Each must
    match exactly once, or it is a mistake and raises rather than silently
    rendering the unmodified code.

    `main.c` is never written to; reverting an experiment is deleting a
    dictionary entry.
    """
    source = open(MAIN_C).read()
    cut = source.index("/* ------------------------------------------------"
                       "------------------------- */\n/* Geometry cache")
    body = source[:cut].replace("#include <pebble.h>", "", 1)

    # Always instrument build_stroke_polygon's own loop.  The driver used to
    # re-derive the width, which meant it printed numbers the polygon was not
    # built from -- so a patch to the width expression was invisible in the
    # reported figures while still changing the drawn shape.
    anchor = """    const float half_width =
      polygon_width * 0.5f;"""
    if body.count(anchor) != 1:
        raise SystemExit("could not find the half_width anchor to instrument")
    body = body.replace(anchor, anchor + """

    printf("C %d %.9g %.9g %.9g %.9g %.9g\\n", index,
           s_centerline[index].x, s_centerline[index].y,
           stroke_width, polygon_width, s_cumulative_length[index]);""")

    for name, value in (overrides or {}).items():
        pattern = re.compile(r"^#define[ \t]+" + re.escape(name) + r"[ \t]+.*$",
                             re.MULTILINE)
        body, count = pattern.subn(f"#define {name} {value}", body)
        if count != 1:
            raise SystemExit(f"override {name}: matched {count} define lines")

    for old, new in (patches or ()):
        if body.count(old) != 1:
            raise SystemExit(f"patch matched {body.count(old)} times, want 1:"
                             f"\n{old[:200]}")
        body = body.replace(old, new)

    path = os.path.join(directory, name + ".c")
    open(path, "w").write((STUB if stub is None else stub) + body
                          + (DRIVER if driver is None else driver))
    binary = os.path.join(directory, name)
    subprocess.run(["gcc", "-std=gnu11", "-O2", "-w", *cflags, "-o", binary,
                    path, *sources, *ldflags], check=True)
    return binary


def gather(times=None, overrides=None, patches=None):
    with tempfile.TemporaryDirectory() as directory:
        binary = build(directory, overrides, patches)
        payload = "\n".join(f"{h} {m}" for h, m in (times or TIMES)) + "\n"
        result = subprocess.run([binary], input=payload, capture_output=True,
                                text=True, check=True)
    frames, current = [], None
    for line in result.stdout.splitlines():
        field = line.split()
        if field[0] == "T":
            current = dict(hour=int(field[1]), minute=int(field[2]),
                           pivot=int(field[3]), total=float(field[4]),
                           scale=float(field[5]), centerline=[], polygon=[])
            frames.append(current)
        elif field[0] == "C":
            current["centerline"].append(
                (float(field[2]), float(field[3]), float(field[4]),
                 float(field[5])))
        else:
            current["polygon"].append((int(field[2]), int(field[3])))
    return frames


def circumradius(a, b, c):
    (ax, ay), (bx, by), (cx, cy) = a, b, c
    d = 2.0 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-12:
        return float("inf")
    ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay)
          + (cx * cx + cy * cy) * (ay - by)) / d
    uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx)
          + (cx * cx + cy * cy) * (bx - ax)) / d
    return math.hypot(ax - ux, ay - uy)


def defects(frame):
    """Cusps are judged on the *fill* polygon, since that is the thing that
    stops being simple.  Collisions are judged on the composite ink width,
    since that is what actually merges on screen."""
    points = [(x, y) for x, y, _, _ in frame["centerline"]]
    ink = [w for _, _, w, _ in frame["centerline"]]
    fill = [w for _, _, _, w in frame["centerline"]]
    n = len(points)
    cusps = [i for i in range(1, n - 1)
             if circumradius(points[i - 1], points[i], points[i + 1])
             < 0.5 * fill[i]]
    collisions = set()
    for i in range(n):
        for j in range(i + 4, n):
            gap = math.hypot(points[i][0] - points[j][0],
                             points[i][1] - points[j][1])
            if gap < 0.5 * (ink[i] + ink[j]):
                collisions.add(i)
                collisions.add(j)
    return cusps, sorted(collisions)


def separation(hour, minute):
    hand = (hour % 12) * 30.0 + minute * 0.5
    delta = abs(minute * 6.0 - hand) % 360.0
    return delta if delta <= 180.0 else 360.0 - delta


def panel(canvas, ox, oy, size, frame, index, zoom):
    canvas.rect(ox, oy, size, size, fill=S.PANEL, stroke="#242a31",
                stroke_width=0.8, rx=3)
    centre = (100.0, 114.0)
    scale = size / 200.0 * zoom

    def T(point):
        return (ox + size / 2 + (point[0] - centre[0]) * scale,
                oy + size / 2 + (point[1] - centre[1]) * scale)

    cusps, collisions = defects(frame)
    canvas.push_clip(ox, oy, size, size, f"env{index}")
    # pass 1: the filled polygon
    canvas.polygon([T(p) for p in frame["polygon"]], fill=S.INK,
                   stroke=S.INK, stroke_width=scale, opacity=0.92)
    # pass 3: the hard one-pixel core along the minute half, which is what
    # makes the minute hand visible once the fill has tapered to nothing
    tail = [T((x, y)) for x, y, _, _ in frame["centerline"][frame["pivot"]:]]
    canvas.polyline(tail, stroke=S.INK, stroke_width=scale, opacity=0.92)
    canvas.polyline([T((x, y)) for x, y, _, _ in frame["centerline"]],
                    stroke="#4fc3f7", stroke_width=0.6, opacity=0.55)
    for i in collisions:
        x, y, _, _ = frame["centerline"][i]
        canvas.circle(*T((x, y)), 1.9, fill="#f95d6a", opacity=0.95)
    for i in cusps:
        x, y, _, _ = frame["centerline"][i]
        canvas.circle(*T((x, y)), 1.2, fill="#f4d35e", opacity=0.95)
    c = T(centre)
    canvas.line(c[0] - 4, c[1], c[0] + 4, c[1], stroke=S.DIM, stroke_width=0.6)
    canvas.line(c[0], c[1] - 4, c[0], c[1] + 4, stroke=S.DIM, stroke_width=0.6)
    canvas.pop()
    hour, minute = frame["hour"], frame["minute"]
    canvas.text(ox + 4, oy + size - 14,
                f"{hour % 12 or 12}:{minute:02d}  d={separation(hour, minute):.1f}",
                size=8, fill=S.DIM)
    canvas.text(ox + 4, oy + size - 4,
                f"cusps {len(cusps)}  collisions {len(collisions)}  "
                f"cw={frame['scale']:.2f}", size=7,
                fill="#f95d6a" if collisions else S.DIM)


def sheet(path, zoom, title, size=176):
    frames = gather()
    gap, left, top = 8, 24, 128
    columns = 5
    rows = (len(frames) + columns - 1) // columns
    canvas = S.Canvas(left + columns * (size + gap) + 16,
                      top + rows * (size + gap) + 16)
    canvas.text(24, 32, title, size=17, fill=S.LABEL, weight="600")
    canvas.text(24, 52, "All three of the watchface's passes: the filled "
                "polygon from main.c, the one-pixel outline around it, and the "
                "hard one-pixel core along the minute half.", size=10,
                fill=S.DIM)
    canvas.text(24, 70, "Red = a sample whose stroke collides with a "
                "non-adjacent part of the stroke.  Yellow = a sample where half "
                "the width exceeds the radius of", size=10, fill=S.DIM)
    canvas.text(24, 86, "curvature, so the inner offset inverts and the polygon "
                "is no longer simple.  cw = waist_opening, the term meant "
                "to keep the branches apart.", size=10, fill=S.DIM)
    canvas.text(24, 104, "Measured over all 720 positions: collisions out to "
                "delta 18.5, cusps out to delta 24.5, and cw is saturated at 1 "
                "(inert) above delta 3.5.", size=10, fill=S.DIM)
    for index, frame in enumerate(frames):
        ox = left + (index % columns) * (size + gap)
        oy = top + (index // columns) * (size + gap)
        panel(canvas, ox, oy, size, frame, index, zoom)
    canvas.write(path)
    print("wrote", path)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    sheet(os.path.join(OUT, "envelope.svg"), 1.0,
          "The stroke as main.c fills it")
    sheet(os.path.join(OUT, "envelope-zoom.svg"), 4.0,
          "The stroke near the centre, 4x", size=176)
