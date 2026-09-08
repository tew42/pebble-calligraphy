#!/usr/bin/env python3
"""Visual comparison: D1 cubic, C3 cubic, and the curvature-prescribed build.

    python3 sheet_constructions.py
"""
from __future__ import annotations
import math, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import geometry as G
import curvature as CV
import svgcanvas as S

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
TIMES = ((12, 0), (1, 5), (12, 7), (12, 12), (3, 0), (10, 10), (3, 49))
D1 = G.CANDIDATES_BY_KEY["d1-arc-sin"]
C3 = G.CANDIDATES_BY_KEY["c3-chord-035"]


def build(kind, hour, minute, face, stems):
    if kind == "beta":
        return CV.build_beta_centerline(hour, minute, D1.rule, face, stems)
    return G.build_centerline(hour, minute, (D1 if kind == "d1" else C3).rule,
                              face, stems)


ROWS = (("d1", "D1 cubic (current lead)"),
        ("c3", "C3 cubic"),
        ("beta", "Beta curvature -> D1 depth"))


def turns(points):
    out = []
    for i in range(1, len(points) - 1):
        a = G.sub(points[i], points[i - 1]); b = G.sub(points[i + 1], points[i])
        na, nb = G.norm(a), G.norm(b)
        out.append(0.0 if na < 1e-9 or nb < 1e-9 else
                   math.degrees(math.atan2(G.cross(a, b) / (na * nb),
                                           G.dot(a, b) / (na * nb))))
    return out


def reverse_turn(points):
    t = turns(points); total = sum(t)
    return sum(abs(v) for v in t if abs(v) > 0.02 and (v > 0) != (total > 0))


def panel(cv, ox, oy, face, stems, hour, minute, kind, scale, index):
    box_w, box_h = face.width * scale, face.height * scale
    cv.rect(ox, oy, box_w, box_h, fill=S.PANEL, stroke="#242a31",
            stroke_width=0.8, rx=3)
    ref = G.build_centerline(hour, minute, D1.rule, face, stems)
    centre = ref.context.center
    cl = build(kind, hour, minute, face, stems)

    def T(p):
        return (ox + p[0] * scale, oy + p[1] * scale)

    cv.push_clip(ox, oy, box_w, box_h, f"cc{index}")
    for tip in (ref.hour_tip, ref.minute_tip):
        cv.line(*T(centre), *T(tip), stroke=S.GUIDE, stroke_width=0.5,
                opacity=0.7, dash="2 3")
    c = T(centre)
    cv.line(c[0] - 5, c[1], c[0] + 5, c[1], stroke=S.DIM, stroke_width=0.6)
    cv.line(c[0], c[1] - 5, c[0], c[1] + 5, stroke=S.DIM, stroke_width=0.6)
    if kind != "d1":
        base = G.build_centerline(hour, minute, D1.rule, face, stems)
        cv.polyline([T(p) for p in base.points], stroke=S.REFERENCE,
                    stroke_width=1.3, opacity=0.85)
    cv.polyline([T(p) for p in cl.points], stroke=S.INK, stroke_width=1.7)
    cv.circle(*T(cl.pivot), 2.0, fill=S.PIVOT)
    cv.pop()

    depth = G.norm(G.sub(cl.pivot, centre))
    rv = reverse_turn(cl.points)
    note = f"s={depth:.1f}  rev={rv:.2f}d"
    if kind == "beta":
        note += "  FOLD" if cl.degenerate else f"  nu={cl.concentration:.0f}"
    cv.text(ox + 4, oy + box_h - 5, note, size=7,
            fill="#f95d6a" if rv > 0.5 else S.DIM)


def sheet(stem_names, path, scale=0.86):
    face = G.Face()
    gap, left, top = 8, 210, 118
    pw, ph = face.width * scale, face.height * scale
    blocks = len(stem_names)
    cv = S.Canvas(left + len(TIMES) * (pw + gap) + 16,
                  top + blocks * (len(ROWS) * (ph + gap) + 34) + 10)
    cv.text(24, 32, "Connector constructions compared", size=17, fill=S.LABEL,
            weight="600")
    cv.text(24, 52, "white = construction     amber = D1 cubic reference     "
            "dashed = the two hand radials     blue = closest approach to centre",
            size=10, fill=S.DIM)
    cv.text(24, 70, "The Beta row prescribes curvature (C0, zero at both stem "
            "junctions, single-signed, one maximum) and solves for geometry, "
            "driven to D1's depth.", size=10, fill=S.DIM)
    cv.text(24, 88, "rev = reverse turn in the drawn line; red if above 0.5 deg."
            "  nu = curvature concentration.", size=10, fill=S.DIM)

    for col, (hour, minute) in enumerate(TIMES):
        x = left + col * (pw + gap)
        cv.text(x + pw / 2, top - 8,
                f"{hour % 12 or 12}:{minute:02d}   d={G.separation_degrees(hour, minute):.0f}",
                size=10, fill=S.LABEL, anchor="middle", weight="600")

    idx = 0
    y = top
    for name in stem_names:
        stems = G.STEMS_BY_NAME[name]
        cv.text(24, y - 6, f"stems: {name}   {stems.describe()}", size=11,
                fill=S.PIVOT, weight="600")
        for kind, label in ROWS:
            cv.text(24, y + 18, label, size=10, fill=S.LABEL, weight="600")
            for col, (hour, minute) in enumerate(TIMES):
                panel(cv, left + col * (pw + gap), y, face, stems, hour, minute,
                      kind, scale, idx)
                idx += 1
            y += ph + gap
        y += 34
    cv.write(path)
    print("wrote", path)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    sheet(["current", "strong-asym"], os.path.join(OUT, "constructions.svg"))
