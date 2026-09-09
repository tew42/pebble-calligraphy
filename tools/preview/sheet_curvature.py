#!/usr/bin/env python3
"""Signed curvature along the connector, for all seven constructions.

    python3 sheet_curvature.py

The design requirement is stated on k, so this is the sheet the families
actually differ in.  Each cell plots k against arc length from the hour stem
junction to the minute stem junction, on a per-cell scale (the magnitudes
differ by orders of magnitude near overlap).  Zero is the mid grey line, so a
profile that crosses it is swerving; a profile with a notch in the middle is the
W flattening.
"""
from __future__ import annotations
import math, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import geometry as G
import curvature as CV
import svgcanvas as S
from sheet_constructions import ROWS, CUBIC_RULES, TIMES, D1

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
SAMPLES = 400


def profile(kind, hour, minute, face, stems):
    """(arc positions normalised to [0,1], signed curvature) along the connector."""
    if kind in CUBIC_RULES:
        cl = G.build_centerline(hour, minute, CUBIC_RULES[kind].rule, face, stems)
        pts, ks = [], []
        for half, (p0, p1, d0, d1, span) in (
            ("h", (cl.hour_connector, cl.pivot, cl.hour_derivative,
                   cl.guide_derivative, cl.hour_span)),
            ("m", (cl.pivot, cl.minute_connector, cl.guide_derivative,
                   cl.minute_derivative, cl.minute_span)),
        ):
            start = 1 if half == "m" else 0
            for i in range(start, SAMPLES // 2 + 1):
                t = i / (SAMPLES // 2)
                p, _, _ = G.hermite_jet(p0, p1, d0, d1, span, t)
                pts.append(p)
                ks.append(G.curvature(p0, p1, d0, d1, span, t))
        return pts, ks

    if kind == "f1":
        cl = CV.build_beta_centerline(hour, minute, D1.rule, face, stems, SAMPLES)
    else:
        own = kind.endswith("*")
        cl = CV.build_compact_centerline(
            hour, minute, CV.HUMP_SHAPES[kind.rstrip("*")],
            None if own else D1.rule, face, stems, SAMPLES)
    lo, hi = G.HOUR_STEM_SEGMENTS, len(cl.points) - G.MINUTE_STEM_SEGMENTS
    pts = cl.points[lo:hi]
    return pts, [abs(k) for k in cl.curvatures[:len(pts)]]


def cell(cv, ox, oy, w, h, kind, hour, minute, face, stems, index):
    cv.rect(ox, oy, w, h, fill=S.PANEL, stroke="#242a31", stroke_width=0.8, rx=3)
    pts, ks = profile(kind, hour, minute, face, stems)
    if len(pts) < 3:
        return
    # Plot every profile with its dominant sign upward, so the shapes are
    # comparable and a genuine sign change still shows as a dip below zero.
    if sum(ks) < 0.0:
        ks = [-k for k in ks]
    arc = [0.0]
    for i in range(1, len(pts)):
        arc.append(arc[-1] + G.norm(G.sub(pts[i], pts[i - 1])))
    span = arc[-1] or 1.0
    peak = max(abs(k) for k in ks) or 1.0

    mid = oy + h / 2
    cv.line(ox + 2, mid, ox + w - 2, mid, stroke=S.GUIDE, stroke_width=0.6)
    cv.push_clip(ox, oy, w, h, f"kc{index}")
    poly = [(ox + 4 + (w - 8) * a / span, mid - (h / 2 - 14) * k / peak)
            for a, k in zip(arc, ks)]
    cv.polyline(poly, stroke=S.INK, stroke_width=1.5)
    cv.pop()
    crossings = sum(1 for i in range(1, len(ks))
                    if ks[i - 1] * ks[i] < 0.0 and abs(ks[i]) > 1e-4 * peak)
    cv.text(ox + 4, oy + h - 3,
            f"kmax={peak:.3g}  L={span:.0f}px  cross={crossings}", size=7,
            fill="#f95d6a" if crossings else S.DIM)


def sheet(stem_names, path):
    face = G.Face()
    cw, ch, gap, left, top = 168, 92, 8, 232, 138
    cv = S.Canvas(left + len(TIMES) * (cw + gap) + 16,
                  top + len(stem_names) * (len(ROWS) * (ch + gap) + 34) + 10)
    cv.text(24, 32, "Curvature along the connector", size=17, fill=S.LABEL,
            weight="600")
    cv.text(24, 52, "Signed k from the hour stem junction (left) to the minute "
            "stem junction (right); grey line is zero, vertical scale is "
            "per-cell.", size=10, fill=S.DIM)
    cv.text(24, 70, "Requirement: k single-signed (no crossing), zero at both "
            "ends, one maximum with no notch in the middle.  cross = sign "
            "changes; kmax in 1/px.", size=10, fill=S.DIM)
    cv.text(24, 88, "The F rows are flat-zero over the straight radial lead-ins "
            "by construction, so their k reaches the junctions exactly rather "
            "than asymptotically.", size=10, fill=S.DIM)

    for col, (hour, minute) in enumerate(TIMES):
        cv.text(left + col * (cw + gap) + cw / 2, top - 8,
                f"{hour % 12 or 12}:{minute:02d}   d={G.separation_degrees(hour, minute):.1f}",
                size=10, fill=S.LABEL, anchor="middle", weight="600")

    idx, y = 0, top
    for name in stem_names:
        stems = G.STEMS_BY_NAME[name]
        cv.text(24, y - 26, f"stems: {name}   {stems.describe()}", size=11,
                fill=S.PIVOT, weight="600")
        for kind, label in ROWS:
            cv.text(24, y + 16, label, size=10, fill=S.LABEL, weight="600")
            for col, (hour, minute) in enumerate(TIMES):
                cell(cv, left + col * (cw + gap), y, cw, ch, kind, hour, minute,
                     face, stems, idx)
                idx += 1
            y += ch + gap
        y += 34
    cv.write(path)
    print("wrote", path)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    for name in ("current", "strong-asym"):
        sheet([name], os.path.join(OUT, f"curvature-{name}.svg"))
