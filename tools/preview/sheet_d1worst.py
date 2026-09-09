#!/usr/bin/env python3
"""D1's worst reverse turn, drawn, by stem ratio and by stem size.

    python3 sheet_d1worst.py

The reverse bend is the only defect in this exercise a person can see, so it is
what a stem-ratio budget has to be set against.  Two facts shape the sheet:

- The reverse turn in *degrees* is exactly scale-invariant -- it depends only on
  r_m/r_h, not on how big the stems are.
- The lateral deviation it produces in *pixels* is not, because it is a length.
  The same 2.77 degrees is 0.61 px of deviation at moderate stems and 0.87 px at
  the largest stems that fit inside the hands.

So each ratio is drawn twice: once at a moderate stem size and once at the
largest that fits, which is the case a budget has to survive.
"""
from __future__ import annotations
import math, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import geometry as G
import curvature as CV
import svgcanvas as S

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
RULE = G.CANDIDATES_BY_KEY["d1-arc-sin"].rule

#: (ratio, note).  1.55 and 1.77 are where the worst turn crosses 3 and 4 deg.
RATIOS = ((1.00, "symmetric"), (1.20, "the current design"),
          (1.55, "3 deg cutoff"), (1.77, "4 deg cutoff"),
          (2.00, ""), (2.50, ""))

GEOMETRIC_MEAN = 0.49
#: Current hand lengths, and how far up a hand its stem may start.
HOUR_LENGTH, MINUTE_LENGTH, FILL = 0.60, 0.90, 0.95
K_SAMPLES = 120


def moderate_stems(ratio):
    root = math.sqrt(ratio)
    return build_stems(GEOMETRIC_MEAN / root, GEOMETRIC_MEAN * root)


def largest_stems(ratio):
    r_h = min(FILL * HOUR_LENGTH, FILL * MINUTE_LENGTH / ratio)
    return build_stems(r_h, r_h * ratio)


def build_stems(r_h, r_m):
    return G.Stems(name=f"{r_h:.3f}/{r_m:.3f}", hour_inner=r_h,
                   minute_inner=r_m,
                   hour_length=max(HOUR_LENGTH, r_h / FILL),
                   minute_length=max(MINUTE_LENGTH, r_m / FILL))


def turn_series(points):
    out = []
    for i in range(1, len(points) - 1):
        a = G.sub(points[i], points[i - 1]); b = G.sub(points[i + 1], points[i])
        na, nb = G.norm(a), G.norm(b)
        out.append(0.0 if na < 1e-9 or nb < 1e-9 else
                   math.degrees(math.atan2(G.cross(a, b) / (na * nb),
                                           G.dot(a, b) / (na * nb))))
    return out


def reverse_turn(points):
    t = turn_series(points); total = sum(t)
    return sum(abs(v) for v in t if abs(v) > 0.02 and (v > 0) != (total > 0))


def reversed_run(points):
    """Vertices of the drawn line whose turn opposes the overall direction,
    as the longest contiguous run, plus the vertex that turns back hardest."""
    t = turn_series(points); total = sum(t)
    against = [abs(v) > 0.02 and (v > 0) != (total > 0) for v in t]
    runs, run = [], []
    for i, flag in enumerate(against):
        if flag:
            run.append(i + 1)
        elif run:
            runs.append(run); run = []
    if run:
        runs.append(run)
    if not runs:
        return [], None
    best = max(runs, key=lambda r: sum(abs(t[i - 1]) for i in r))
    return best, max(best, key=lambda i: abs(t[i - 1]))


def _point_to_polyline(p, b):
    def seg(q, r):
        d = G.sub(r, q); L = G.dot(d, d)
        if L < 1e-18:
            return G.norm(G.sub(p, q))
        u = max(0.0, min(1.0, G.dot(G.sub(p, q), d) / L))
        return G.norm(G.sub(p, G.add(q, G.scale(d, u))))
    return min(seg(b[i], b[i + 1]) for i in range(len(b) - 1))


def worst_turn_position(stems, face):
    best = (0.0, None)
    for hour in range(12):
        for minute in range(60):
            cl = G.build_centerline(hour, minute, RULE, face, stems)
            rv = reverse_turn(cl.points)
            if rv > best[0]:
                best = (rv, (hour, minute))
    return best


def dense(cl):
    pts, ks = [], []
    for i in range(K_SAMPLES + 1):
        t = i / K_SAMPLES
        p, _, _ = G.hermite_jet(cl.hour_connector, cl.pivot, cl.hour_derivative,
                                cl.guide_derivative, cl.hour_span, t)
        pts.append(p)
        ks.append(G.curvature(cl.hour_connector, cl.pivot, cl.hour_derivative,
                              cl.guide_derivative, cl.hour_span, t))
    for i in range(1, K_SAMPLES + 1):
        t = i / K_SAMPLES
        p, _, _ = G.hermite_jet(cl.pivot, cl.minute_connector,
                                cl.guide_derivative, cl.minute_derivative,
                                cl.minute_span, t)
        pts.append(p)
        ks.append(G.curvature(cl.pivot, cl.minute_connector,
                              cl.guide_derivative, cl.minute_derivative,
                              cl.minute_span, t))
    return pts, ks


def draw(cv, ox, oy, w, h, hour, minute, stems, face, index, window=None):
    """`window` in face pixels; None draws the whole face."""
    cv.rect(ox, oy, w, h, fill=S.PANEL, stroke="#242a31", stroke_width=0.8, rx=3)
    cl = G.build_centerline(hour, minute, RULE, face, stems)
    ref = CV.build_compact_centerline(hour, minute, CV.adaptive_shape, RULE,
                                      face, stems)
    run, hardest = reversed_run(cl.points)
    centre = face.center
    if window is None:
        focus, scale = centre, min(w / face.width, h / face.height)
    else:
        focus = cl.points[hardest] if hardest is not None else centre
        scale = min(w, h) / window

    def T(p):
        return (ox + w / 2 + (p[0] - focus[0]) * scale,
                oy + h / 2 + (p[1] - focus[1]) * scale)

    cv.push_clip(ox, oy, w, h, f"dw{index}")
    for tip in (cl.hour_tip, cl.minute_tip):
        cv.line(*T(centre), *T(tip), stroke=S.GUIDE, stroke_width=0.5,
                opacity=0.7, dash="2 3")
    c = T(centre)
    cv.line(c[0] - 5, c[1], c[0] + 5, c[1], stroke=S.DIM, stroke_width=0.6)
    cv.line(c[0], c[1] - 5, c[0], c[1] + 5, stroke=S.DIM, stroke_width=0.6)
    cv.polyline([T(p) for p in ref.points], stroke=S.REFERENCE,
                stroke_width=1.4, opacity=0.9)
    cv.polyline([T(p) for p in cl.points], stroke=S.INK, stroke_width=1.6)
    if len(run) > 1:
        cv.polyline([T(cl.points[i]) for i in run], stroke="#f95d6a",
                    stroke_width=3.0)
    cv.pop()
    gap = (max(_point_to_polyline(cl.points[i], ref.points) for i in run)
           if run else 0.0)
    return reverse_turn(cl.points), gap


def profile(cv, ox, oy, w, h, hour, minute, stems, face, index):
    cv.rect(ox, oy, w, h, fill=S.PANEL, stroke="#242a31", stroke_width=0.8, rx=3)
    cl = G.build_centerline(hour, minute, RULE, face, stems)
    pts, ks = dense(cl)
    if sum(ks) < 0.0:
        ks = [-k for k in ks]
    arc = [0.0]
    for i in range(1, len(pts)):
        arc.append(arc[-1] + G.norm(G.sub(pts[i], pts[i - 1])))
    span = arc[-1] or 1.0
    peak = max(abs(k) for k in ks) or 1.0
    mid = oy + h * 0.62
    cv.line(ox + 2, mid, ox + w - 2, mid, stroke=S.GUIDE, stroke_width=0.6)
    cv.push_clip(ox, oy, w, h, f"dp{index}")
    poly = [(ox + 4 + (w - 8) * a / span, mid - (h * 0.5 - 10) * k / peak)
            for a, k in zip(arc, ks)]
    cv.polyline(poly, stroke=S.INK, stroke_width=1.4)
    neg = [(x, y) for (x, y), k in zip(poly, ks) if k < 0.0]
    if len(neg) > 1:
        cv.polyline(neg, stroke="#f95d6a", stroke_width=2.4)
    cv.pop()
    cv.text(ox + 4, oy + h - 4, f"kmax={peak:.4f}", size=7, fill=S.DIM)


def sheet(path, window=26.0):
    face = G.Face()
    pw, ph, gap, left, top = 148, 168, 8, 192, 156
    cv = S.Canvas(left + 6 * (pw + gap) + 60, top + len(RATIOS) * (ph + gap + 24) + 16)
    cv.text(24, 32, "D1's worst reverse turn, by stem ratio and stem size",
            size=17, fill=S.LABEL, weight="600")
    cv.text(24, 52, "white = D1     amber = F6, monotone curvature at the same "
            "depth     red = the run where the drawn line turns back",
            size=10, fill=S.DIM)
    cv.text(24, 70, "The turn in degrees is exactly scale-invariant: it depends "
            "only on r_m/r_h.  The deviation in pixels is not, so each ratio is "
            "shown at a moderate", size=10, fill=S.DIM)
    cv.text(24, 86, f"stem size (geometric mean {GEOMETRIC_MEAN:.2f}R) and at the "
            f"largest stems that fit inside hands of {HOUR_LENGTH:.2f}R and "
            f"{MINUTE_LENGTH:.2f}R.", size=10, fill=S.DIM)
    cv.text(24, 104, f"Zoom panels show a {window:.0f} px window centred on the "
            "hardest reversing vertex -- that is where the defect is, not where "
            "the two curves are furthest apart.", size=10, fill=S.DIM)

    heads = ("moderate stems: whole face", f"same, {window:.0f} px window",
             "curvature",
             "largest stems: whole face", f"same, {window:.0f} px window",
             "curvature")
    for i, head in enumerate(heads):
        cv.text(left + i * (pw + gap) + pw / 2, top - 8, head, size=9,
                fill=S.LABEL, anchor="middle", weight="600")

    index, y = 0, top
    for ratio, note in RATIOS:
        cv.text(24, y + 16, f"r_m/r_h = {ratio:.2f}", size=11, fill=S.PIVOT,
                weight="600")
        if note:
            cv.text(24, y + 30, f"({note})", size=9, fill=S.PIVOT)
        row = []
        for variant, stems in (("moderate", moderate_stems(ratio)),
                               ("largest", largest_stems(ratio))):
            rv, pos = worst_turn_position(stems, face)
            row.append((stems, pos, rv))
        cv.text(24, y + 50, f"turn {row[0][2]:.2f} deg", size=9, fill="#f95d6a")
        cv.text(24, y + 64, f"r_h={row[0][0].hour_inner:.3f} "
                f"r_m={row[0][0].minute_inner:.3f}", size=8, fill=S.DIM)
        cv.text(24, y + 82, f"r_h={row[1][0].hour_inner:.3f} "
                f"r_m={row[1][0].minute_inner:.3f}", size=8, fill=S.DIM)
        col = 0
        for stems, pos, rv in row:
            hour, minute = pos
            for kind in ("full", "zoom", "profile"):
                ox = left + col * (pw + gap)
                if kind == "profile":
                    profile(cv, ox, y, pw, ph, hour, minute, stems, face, index)
                else:
                    turn, px = draw(cv, ox, y, pw, ph, hour, minute, stems,
                                    face, index,
                                    None if kind == "full" else window)
                    cv.text(ox + 4, y + ph - 14,
                            f"{hour % 12 or 12}:{minute:02d}  "
                            f"d={G.separation_degrees(hour, minute):.0f}",
                            size=7, fill=S.DIM)
                    cv.text(ox + 4, y + ph - 4,
                            f"turn {turn:.2f}d   deviation {px:.2f}px", size=7,
                            fill=S.DIM)
                index += 1
                col += 1
        y += ph + gap + 24
    cv.write(path)
    print("wrote", path)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    sheet(os.path.join(OUT, "d1-worst.svg"))
