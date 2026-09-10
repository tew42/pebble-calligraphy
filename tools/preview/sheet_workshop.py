#!/usr/bin/env python3
"""Mock-ups for the four open envelope questions.

    python3 tools/preview/sheet_workshop.py

Each sheet varies one thing and holds everything else, and every variant is
compiled out of `main.c` through `sheet_envelope.build`'s override/patch
mechanism, so what is drawn is the real code with one constant or one function
body changed. `main.c` is never written to.

  workshop-clearance.svg  does the branch-clearance squeeze do anything wanted?
  workshop-pressure.svg   is the pressure envelope's intent worth having?
  workshop-easing.svg     held body then taper, or one continuous modulation?
  workshop-tangent.svg     what the bisector tangent costs, now and if widened
"""
from __future__ import annotations

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import svgcanvas as S
from sheet_envelope import OUT, gather, separation

CENTRE = (100.0, 114.0)


# --- the patches ----------------------------------------------------------

SMOOTHSTEP = ("  return\n    position *\n    position *\n"
              "    (3.0f - 2.0f * position);")

EASINGS = {
    "linear": "  return position;",
    "smoothstep (shipped)": None,
    "smootherstep": ("  return position * position * position *\n"
                     "    (position * (position * 6.0f - 15.0f) + 10.0f);"),
    "half-cosine": ("  return 0.5f * (1.0f - cosf(3.14159265f * position));"),
}

#: The waist term, as shipped, and the two ways of changing it.
WAIST_SHIPPED = """  const float effective_middle_width =
    interpolate_float(
      1.0f,
      MIDDLE_WIDTH,
      smooth_unit(center_width_scale)
    );"""
WAIST_DELETED = """  const float effective_middle_width =
    MIDDLE_WIDTH;"""

CLEARANCE_DIVISOR = "      branch_clearance /\n      MIDDLE_WIDTH,"

#: The contraction runs from the swell breakpoint all the way to the pivot.
#: Holding the body first, by starting the contraction later, is a different
#: lever from re-easing it -- and a much bigger one, because any easing between
#: two widths 3 px apart can only move the result by about 0.3 px.
CONTRACTION_START = """    const float contraction_position =
      (
        hour_position -
        HOUR_SWELL_POSITION
      ) /
      (
        1.0f -
        HOUR_SWELL_POSITION
      );"""


def hold_body(until):
    return (CONTRACTION_START, f"""    const float contraction_position =
      (hour_position - {until}f) / (1.0f - {until}f);""")

#: The pressure envelope, as shipped, and re-centred on the pivot so its two
#: lobes carry equal weight.
ENVELOPE_SHIPPED = """    const float body_envelope =
      4.0f *
      position *
      (1.0f - position);"""
ENVELOPE_PIVOTED = """    const float body_envelope =
      position <= pivot_position
        ? (pivot_position > 0.0f ? position / pivot_position : 0.0f)
        : (pivot_position < 1.0f
             ? (1.0f - position) / (1.0f - pivot_position)
             : 0.0f);"""


# --- geometry helpers -----------------------------------------------------

def unit(a, b):
    d = (b[0] - a[0], b[1] - a[1])
    n = math.hypot(*d)
    return (0.0, -1.0) if n < 1e-9 else (d[0] / n, d[1] / n)


def polygon_from(points, widths, tangents):
    """Rebuild the stroke polygon the way build_stroke_polygon does."""
    n = len(points)
    left = [None] * n
    right = [None] * n
    for i in range(n):
        t = tangents[i]
        nx, ny = -t[1], t[0]
        half = max(0.0, widths[i]) * 0.5
        left[i] = (points[i][0] + nx * half, points[i][1] + ny * half)
        right[i] = (points[i][0] - nx * half, points[i][1] - ny * half)
    left[-1] = right[-1] = points[-1]          # the minute tip collapse
    return left + right[::-1]


def bisector_tangents(points):
    n = len(points)
    out = []
    for i in range(n):
        if i == 0:
            out.append(unit(points[0], points[1]))
        elif i == n - 1:
            out.append(unit(points[-2], points[-1]))
        else:
            a = unit(points[i - 1], points[i])
            b = unit(points[i], points[i + 1])
            s = (a[0] + b[0], a[1] + b[1])
            m = math.hypot(*s)
            out.append(b if m < 1e-9 else (s[0] / m, s[1] / m))
    return out


def dense_tangents(coarse_points, dense_points):
    """Near-exact tangents: central differences on a 4x-denser sampling of the
    same curve, evaluated at whichever dense sample is nearest each coarse one."""
    out = []
    for p in coarse_points:
        j = min(range(len(dense_points)),
                key=lambda k: (dense_points[k][0] - p[0]) ** 2
                + (dense_points[k][1] - p[1]) ** 2)
        lo = max(0, j - 1)
        hi = min(len(dense_points) - 1, j + 1)
        out.append(unit(dense_points[lo], dense_points[hi]))
    return out


# --- drawing --------------------------------------------------------------

def panel(cv, ox, oy, w, h, frame, index, zoom, polygon=None, profile=False):
    cv.rect(ox, oy, w, h, fill=S.PANEL, stroke="#242a31", stroke_width=0.8, rx=3)
    scale = min(w, h) / 200.0 * zoom
    pts = [(x, y) for x, y, _, _ in frame["centerline"]]
    ink = [iw for _, _, iw, _ in frame["centerline"]]

    def T(p):
        return (ox + w / 2 + (p[0] - CENTRE[0]) * scale,
                oy + h / 2 + (p[1] - CENTRE[1]) * scale)

    cv.push_clip(ox, oy, w, h, f"ws{index}")
    poly = polygon if polygon is not None else frame["polygon"]
    cv.polygon([T(p) for p in poly], fill=S.INK, stroke=S.INK,
               stroke_width=scale, opacity=0.92)
    cv.polyline([T(p) for p in pts[frame["pivot"]:]], stroke=S.INK,
                stroke_width=scale, opacity=0.92)
    c = T(CENTRE)
    cv.line(c[0] - 4, c[1], c[0] + 4, c[1], stroke=S.DIM, stroke_width=0.6)
    cv.line(c[0], c[1] - 4, c[0], c[1] + 4, stroke=S.DIM, stroke_width=0.6)
    if profile:
        # the width profile itself, along the bottom of the cell
        top, base, span = oy + h - 40.0, oy + h - 8.0, w - 8.0
        peak = max(ink) or 1.0
        arc = [0.0]
        for i in range(1, len(pts)):
            arc.append(arc[-1] + math.hypot(pts[i][0] - pts[i - 1][0],
                                            pts[i][1] - pts[i - 1][1]))
        total = arc[-1] or 1.0
        cv.line(ox + 4, base, ox + 4 + span, base, stroke=S.GUIDE,
                stroke_width=0.5)
        cv.polyline([(ox + 4 + span * a / total, base - (base - top) * v / peak)
                     for a, v in zip(arc, ink)], stroke="#4fc3f7",
                    stroke_width=1.2)
    cv.pop()


def sheet(path, title, notes, times, variants, zoom=1.0, size=150,
          profile=False, label_width=268, metric="width"):
    """`variants` is a list of (label, overrides, patches, extra) where extra is
    an optional callable(frame, dense) -> polygon for a Python-built variant."""
    gap, top = 8, 116 + 16 * len(notes)
    cv = S.Canvas(label_width + len(times) * (size + gap) + 16,
                  top + len(variants) * (size + gap) + 16)
    cv.text(24, 32, title, size=17, fill=S.LABEL, weight="600")
    for i, line in enumerate(notes):
        cv.text(24, 52 + 16 * i, line, size=10, fill=S.DIM)
    for col, (hour, minute) in enumerate(times):
        cv.text(label_width + col * (size + gap) + size / 2, top - 8,
                f"{hour % 12 or 12}:{minute:02d}  d="
                f"{separation(hour, minute):.1f}", size=9, fill=S.LABEL,
                anchor="middle", weight="600")
    index = 0
    baseline = None
    for row, variant in enumerate(variants):
        label, overrides, patches, extra = variant
        y = top + row * (size + gap)
        cv.text(24, y + 16, label, size=10, fill=S.LABEL, weight="600")
        frames = gather(times=times, overrides=overrides, patches=patches)
        dense = None
        if extra is not None:
            dense = gather(times=times, overrides={
                "HOUR_STEM_SEGMENTS": "32", "CONNECTOR_SEGMENTS": "120",
                "MINUTE_STEM_SEGMENTS": "40"})
        polys = [(extra(f, d) if extra is not None else f["polygon"])
                 for f, d in zip(frames, dense or frames)]
        if metric == "polygon":
            # for the tangent question the widths are identical by design and
            # the whole difference is in where the offset vertices land
            measured = polys
            def worst_of(a, b):
                return max(math.hypot(p[0] - q[0], p[1] - q[1])
                           for p, q in zip(a, b))
            unit_label = "outline moves by up to"
        else:
            measured = [[w for _, _, w, _ in f["centerline"]] for f in frames]
            def worst_of(a, b):
                return max(abs(x - y) for x, y in zip(a, b))
            unit_label = "width differs from row 1 by up to"
        if baseline is None:
            baseline = measured
            cv.text(24, y + 32, "(baseline for the deltas below)", size=8,
                    fill=S.DIM)
        else:
            worst = max(worst_of(a, b) for a, b in zip(measured, baseline))
            cv.text(24, y + 32, f"{unit_label} {worst:.3f} px",
                    size=8, fill=S.DIM if worst < 0.5 else "#f4d35e")
        for col, frame in enumerate(frames):
            ox = label_width + col * (size + gap)
            poly = polys[col] if extra is not None else None
            panel(cv, ox, y, size, size, frame, index, zoom, poly, profile)
            peak = max(iw for _, _, iw, _ in frame["centerline"])
            waist = frame["centerline"][frame["pivot"]][2]
            cv.text(ox + 4, y + size - 4,
                    f"peak {peak:.2f}  waist {waist:.2f}", size=7, fill=S.DIM)
            index += 1
    cv.write(path)
    print("wrote", path)


# --- the four questions ---------------------------------------------------

NEAR = ((12, 0), (12, 1), (12, 2), (12, 3), (12, 4), (12, 5))
WIDE = ((12, 7), (12, 12), (3, 0), (10, 10), (3, 40))


def clearance_sheet():
    sheet(
        os.path.join(OUT, "workshop-clearance.svg"),
        "1. Branch clearance: does the squeeze do anything wanted?",
        ["The waist is squeezed toward 1 px as the hands close. As shipped the "
         "term saturates at delta 3.5, so it acts only in the first column or "
         "two.",
         "Row 3 keeps the same formula but retunes the divisor so it acts out "
         "to about delta 26 -- what the mechanism appears to have been for.",
         "Self-overlap is not a defect, so the question is whether the squeeze "
         "is desirable at all, not whether it prevents a collision."],
        NEAR,
        [("as shipped", None, None, None),
         ("deleted", None, [(WAIST_SHIPPED, WAIST_DELETED)], None),
         ("divisor retuned, acts to d~26", None,
          [(CLEARANCE_DIVISOR, "      branch_clearance /\n      20.0f,")],
          None)],
        zoom=6.0, size=176)


def pressure_sheet():
    sheet(
        os.path.join(OUT, "workshop-pressure.svg"),
        "2. Pressure envelope: is the intent worth having?",
        ["Intent: a loaded pen lays more ink into a turn than out of it. The "
         "term thickens before the pivot and thins after, fading to nothing at "
         "both tips.",
         "As shipped it moves any width by at most 0.133 px -- invisible. The "
         "lower rows are the same term amplified.",
         "The last row also re-centres the 4p(1-p) envelope on the pivot; as "
         "shipped it peaks at arc-midpoint, so the thinning lobe outweighs the "
         "thickening one."],
        WIDE,
        [("off (PRESSURE_VARIATION 0)", {"PRESSURE_VARIATION": "0.0f"}, None, None),
         ("shipped (0.20)", None, None, None),
         ("1.0", {"PRESSURE_VARIATION": "1.0f"}, None, None),
         ("2.0", {"PRESSURE_VARIATION": "2.0f"}, None, None),
         ("2.0, envelope centred on pivot",
          {"PRESSURE_VARIATION": "2.0f"},
          [(ENVELOPE_SHIPPED, ENVELOPE_PIVOTED)], None)],
        zoom=1.35, size=256, profile=True)


def easing_sheet():
    rows = []
    for label, patch in EASINGS.items():
        rows.append((label, None,
                     None if patch is None else [(SMOOTHSTEP, patch)], None))
    # the other lever: hold the body before contracting at all
    rows.append(("body held to 40% of the hour side", None,
                 [hold_body("0.40")], None))
    rows.append(("body held to 70%", None, [hold_body("0.70")], None))
    sheet(
        os.path.join(OUT, "workshop-easing.svg"),
        "3. Contraction and taper: held body, or continuous modulation?",
        ["All four width blends are eased lerps. Smoothstep has zero slope at "
         "both ends of every segment, so the width is momentarily flat at each "
         "breakpoint.",
         "Blue trace along the bottom of each cell is the width profile itself "
         "-- the plateaus are visible there before they are visible in the "
         "stroke.",
         "Caveat: smooth_unit is shared with the clearance term, so rows 1-4 "
         "also change that. It is inert at these separations.",
         "Rows 5-6 change the breakpoint instead of the easing -- holding the "
         "body before contracting. Any easing between two widths 3 px apart "
         "can only move the width ~0.3 px; the breakpoint is the real lever."],
        WIDE, rows, zoom=1.35, size=256, profile=True)


def tangent_sheet():
    def exact(frame, dense_frame):
        pts = [(x, y) for x, y, _, _ in frame["centerline"]]
        ink = [w for _, _, _, w in frame["centerline"]]
        dpts = [(x, y) for x, y, _, _ in dense_frame["centerline"]]
        return polygon_from(pts, ink, dense_tangents(pts, dpts))

    def shipped(frame, _dense):
        pts = [(x, y) for x, y, _, _ in frame["centerline"]]
        ink = [w for _, _, _, w in frame["centerline"]]
        return polygon_from(pts, ink, bisector_tangents(pts))

    triple = {"HOUR_TIP_WIDTH": "9.0f", "HOUR_BODY_WIDTH": "18.0f",
              "MIDDLE_WIDTH": "9.0f", "MINUTE_TIP_WIDTH": "3.0f"}
    times = ((12, 1), (12, 2), (12, 3), (12, 5), (12, 8))
    notes = [
        "The envelope reconstructs its tangent by finite difference from the "
        "49 drawn points, rather than using the Hermite derivative the "
        "centerline already computed.",
        "'near-exact' rebuilds the polygon from tangents derived off a "
        "4x-denser sampling of the same curve. Both rows here share identical "
        "widths, so the whole difference is where the offset lands.",
        "The error is an angle, so its cost in pixels scales with the width -- "
        "which is why it matters only if question 1 resolves toward merging "
        "harder. The companion sheet is the same at 3x widths."]
    sheet(os.path.join(OUT, "workshop-tangent.svg"),
          "4a. Bisector tangent at shipped widths", notes, times,
          [("shipped bisector", None, None, shipped),
           ("near-exact tangent", None, None, exact)],
          zoom=4.5, metric="polygon")
    sheet(os.path.join(OUT, "workshop-tangent-wide.svg"),
          "4b. The same at 3x widths -- what merging harder would cost",
          notes[:1] + ["All widths tripled, nothing else changed. The tangent "
                       "error is unchanged in angle, so its cost in pixels "
                       "roughly triples."],
          times,
          [("bisector, 3x widths", triple, None, shipped),
           ("near-exact, 3x widths", triple, None, exact)],
          zoom=4.5, metric="polygon")


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    which = sys.argv[1:] or ["clearance", "pressure", "easing", "tangent"]
    if "clearance" in which:
        clearance_sheet()
    if "pressure" in which:
        pressure_sheet()
    if "easing" in which:
        easing_sheet()
    if "tangent" in which:
        tangent_sheet()
