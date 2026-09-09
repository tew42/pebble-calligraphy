#!/usr/bin/env python3
"""Draw D1's worst reversed-curvature lobe and worst reverse turn, by stem ratio.

    python3 sheet_d1worst.py

Section 28 of the design notes says D1's defect depends only on |log(r_m/r_h)|
and is never zero.  Those are numbers; this is what they look like.  For each
ratio the sheet finds the hand position that maximises each defect, draws the
connector with the reversed-curvature run picked out in red, and zooms on it
with a monotone-curvature construction (F6) overlaid so the deviation can be
read in pixels rather than degrees.

Stems are chosen with a fixed geometric mean, so only the ratio varies and both
radii stay inside the face.
"""
from __future__ import annotations
import math, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import geometry as G
import curvature as CV
import svgcanvas as S

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
RULE = G.CANDIDATES_BY_KEY["d1-arc-sin"].rule
RATIOS = (1.00, 1.20, 1.50, 2.00, 2.50)
GEOMETRIC_MEAN = 0.49
K_SAMPLES = 120
ZOOM = 7.0
#: Near overlap the hairpin's curvature is unbounded by design.
GUARD_DEG = 20.0


def stems_for(ratio):
    root = math.sqrt(ratio)
    r_h, r_m = GEOMETRIC_MEAN / root, GEOMETRIC_MEAN * root
    return G.Stems(name=f"ratio {ratio:.2f}", hour_inner=r_h, minute_inner=r_m,
                   hour_length=max(0.60, r_h + 0.05),
                   minute_length=max(0.90, r_m + 0.05))


def dense(cl):
    """Connector points and analytic curvature, on a fine parameter grid."""
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


def reversed_run(ks):
    """Indices whose curvature opposes the dominant sign, and the lobe size."""
    peak = max(abs(k) for k in ks) or 1.0
    dominant = 1.0 if sum(ks) > 0.0 else -1.0
    idx = [i for i, k in enumerate(ks) if k * dominant < 0.0]
    lobe = max((abs(ks[i]) for i in idx), default=0.0) / peak
    return idx, lobe


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


def separation_from(cl):
    return math.degrees(math.acos(max(-1.0, min(1.0, cl.context.radial_dot))))


def worst_positions(stems, face):
    """The position with the largest visible deviation, and the one with the
    largest reverse turn.

    The reversed-curvature *lobe* is deliberately not used to pick a position.
    It is scale-free, which makes it comparable across stem ratios, but it is
    not weighted by visibility: its maximum sits out near opposition where peak
    curvature has fallen to a 400 px radius, so a 28% lobe there is a tenth of
    a pixel of actual deviation.  The pixel separation from a
    monotone-curvature construction is what the eye gets.
    """
    best_sep = (0.0, None)
    best_turn = (0.0, None)
    best_lobe = (0.0, None)
    for hour in range(12):
        for minute in range(60):
            cl = G.build_centerline(hour, minute, RULE, face, stems)
            rv = reverse_turn(cl.points)
            if rv > best_turn[0]:
                best_turn = (rv, (hour, minute))
            ref = CV.build_compact_centerline(hour, minute, CV.adaptive_shape,
                                              RULE, face, stems)
            sp = separation_px(cl.points, ref.points)
            if sp > best_sep[0]:
                best_sep = (sp, (hour, minute))
            if separation_from(cl) >= GUARD_DEG:
                _, lobe = reversed_run(dense(cl)[1])
                if lobe > best_lobe[0]:
                    best_lobe = (lobe, (hour, minute))
    return best_sep, best_turn, best_lobe


def _point_to_polyline(p, b):
    def seg(q, r):
        d = G.sub(r, q); L = G.dot(d, d)
        if L < 1e-18:
            return G.norm(G.sub(p, q))
        u = max(0.0, min(1.0, G.dot(G.sub(p, q), d) / L))
        return G.norm(G.sub(p, G.add(q, G.scale(d, u))))
    return min(seg(b[i], b[i + 1]) for i in range(len(b) - 1))


def separation_px(a, b):
    """Max distance from any vertex of a to the polyline b."""
    return max(_point_to_polyline(p, b) for p in a)


def separation_site(a, b):
    """Where that maximum happens -- what to centre a zoom on."""
    worst = max(range(len(a)), key=lambda i: _point_to_polyline(a[i], b))
    return a[worst], _point_to_polyline(a[worst], b)


def draw(cv, ox, oy, w, h, hour, minute, stems, face, index, zoom=1.0,
         focus_on="separation"):
    cv.rect(ox, oy, w, h, fill=S.PANEL, stroke="#242a31", stroke_width=0.8, rx=3)
    cl = G.build_centerline(hour, minute, RULE, face, stems)
    ref = CV.build_compact_centerline(hour, minute, CV.adaptive_shape, RULE,
                                      face, stems)
    pts, ks = dense(cl)
    idx, lobe = reversed_run(ks)
    centre = face.center
    if zoom <= 1.0:
        focus = centre
    elif focus_on == "separation":
        focus, _ = separation_site(pts, ref.points)
    else:
        focus = pts[idx[len(idx) // 2]] if idx else centre
    scale = min(w / face.width, h / face.height) * zoom

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
                stroke_width=1.3, opacity=0.85)
    cv.polyline([T(p) for p in pts], stroke=S.INK, stroke_width=1.6)
    if idx:
        runs, run = [], [idx[0]]
        for i in idx[1:]:
            if i == run[-1] + 1:
                run.append(i)
            else:
                runs.append(run); run = [i]
        runs.append(run)
        for r in runs:
            if len(r) > 1:
                cv.polyline([T(pts[i]) for i in r], stroke="#f95d6a",
                            stroke_width=2.6)
    cv.pop()
    return lobe, reverse_turn(cl.points), separation_px(pts, ref.points)


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
    poly = [(ox + 4 + (w - 8) * a / span, mid - (h * 0.5 - 8) * k / peak)
            for a, k in zip(arc, ks)]
    cv.polyline(poly, stroke=S.INK, stroke_width=1.4)
    neg = [(x, y) for (x, y), k in zip(poly, ks) if k < 0.0]
    if len(neg) > 1:
        cv.polyline(neg, stroke="#f95d6a", stroke_width=2.2)
    cv.pop()
    cv.text(ox + 4, oy + h - 4, f"kmax={peak:.4f}", size=7, fill=S.DIM)


def sheet(path):
    face = G.Face()
    pw, ph, gap, left, top = 150, 172, 8, 178, 148
    cols = 6
    cv = S.Canvas(left + cols * (pw + gap) + 16,
                  top + len(RATIOS) * (ph + gap + 26) + 16)
    cv.text(24, 32, "D1's worst case, by stem ratio", size=17, fill=S.LABEL,
            weight="600")
    cv.text(24, 52, "white = D1     amber = F6, monotone curvature at the same "
            f"depth     red = where D1's curvature has reversed     zooms are "
            f"{ZOOM:.0f}x", size=10, fill=S.DIM)
    cv.text(24, 70, f"Stems keep a geometric mean of {GEOMETRIC_MEAN:.2f}R, so "
            "only the ratio changes.  Reverse turn and lobe are exactly "
            "scale-invariant; the pixel gap scales with the radii.",
            size=10, fill=S.DIM)
    cv.text(24, 88, "Left three: where D1 and F6 sit furthest apart.  Right "
            "three: the largest reverse turn.  The lobe is reported but never "
            "used to pick a position -- it peaks near", size=10, fill=S.DIM)
    cv.text(24, 104, "opposition, where the curve is nearly straight and a 28% "
            "lobe amounts to a tenth of a pixel.", size=10, fill=S.DIM)

    heads = ("worst visible deviation", f"same, {ZOOM:.0f}x on the widest gap",
             "curvature there",
             "worst reverse turn", f"same, {ZOOM:.0f}x on the reversed run",
             "curvature there")
    for i, head in enumerate(heads):
        cv.text(left + i * (pw + gap) + pw / 2, top - 8, head, size=9,
                fill=S.LABEL, anchor="middle", weight="600")

    index = 0
    y = top
    for ratio in RATIOS:
        stems = stems_for(ratio)
        (sep, at_sep), (rev, at_rev), (lobe, at_lobe) = worst_positions(
            stems, face)
        cv.text(24, y + 16, f"r_m/r_h = {ratio:.2f}", size=11, fill=S.PIVOT,
                weight="600")
        if abs(ratio - 1.20) < 1e-9:
            cv.text(24, y + 30, "(the current design)", size=9, fill=S.PIVOT)
        cv.text(24, y + 44, f"r_h={stems.hour_inner:.3f}R", size=9, fill=S.DIM)
        cv.text(24, y + 57, f"r_m={stems.minute_inner:.3f}R", size=9, fill=S.DIM)
        cv.text(24, y + 75, f"worst gap {sep:.2f} px", size=9, fill="#f95d6a")
        cv.text(24, y + 89, f"worst turn {rev:.2f} deg", size=9, fill="#f95d6a")
        cv.text(24, y + 103, f"worst lobe {100*lobe:.1f}%", size=9, fill=S.DIM)
        for col, (pos, zoom, kind, focus) in enumerate((
                (at_sep, 1.0, "draw", "separation"),
                (at_sep, ZOOM, "draw", "separation"),
                (at_sep, 0, "profile", ""),
                (at_rev, 1.0, "draw", "lobe"),
                (at_rev, ZOOM, "draw", "lobe"),
                (at_rev, 0, "profile", ""))):
            ox = left + col * (pw + gap)
            hour, minute = pos
            if kind == "profile":
                profile(cv, ox, y, pw, ph, hour, minute, stems, face, index)
            else:
                lb, rv, sp = draw(cv, ox, y, pw, ph, hour, minute, stems, face,
                                  index, zoom, focus)
                cv.text(ox + 4, y + ph - 14,
                        f"{hour % 12 or 12}:{minute:02d}  "
                        f"d={G.separation_degrees(hour, minute):.0f}", size=7,
                        fill=S.DIM)
                cv.text(ox + 4, y + ph - 4,
                        f"lobe {100*lb:.1f}%  rev {rv:.2f}d  sep {sp:.2f}px",
                        size=7, fill=S.DIM)
            index += 1
        y += ph + gap + 26
    cv.write(path)
    print("wrote", path)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    sheet(os.path.join(OUT, "d1-worst.svg"))
