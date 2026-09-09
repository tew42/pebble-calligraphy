#!/usr/bin/env python3
"""Seven connector constructions side by side: C0, C1, D1, F1, F2, F3, F4.

    python3 sheet_constructions.py

C0/C1/D1 are prescribed-pivot cubics: place a point P from a rule, then run the
two-piece minimum-bending Hermite through it.  F1-F4 are prescribed-curvature:
choose the shape of k along the arc and solve for the geometry, driven to the
same depth D1 asks for so the families are compared on equal terms.
"""
from __future__ import annotations
import math, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import geometry as G
import curvature as CV
import svgcanvas as S

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
TIMES = ((12, 0), (1, 5), (12, 7), (12, 12), (3, 0), (10, 10), (3, 49))
ZOOM_TIMES = ((12, 1), (12, 2), (12, 3), (12, 4), (12, 5), (12, 6), (12, 8))

D1 = G.CANDIDATES_BY_KEY["d1-arc-sin"]
C0 = G.CANDIDATES_BY_KEY["c0-current"]
C1 = G.CANDIDATES_BY_KEY["c1-openness"]

ROWS = (
    ("c0", "C0  cubic, current pivot rule"),
    ("c1", "C1  cubic, round-1 pivot rule"),
    ("d1", "D1  cubic, arc-apex x sin(d/2)"),
    ("f1", "F1  k = Beta hump, full support"),
    ("f2", "F2  k = trapezoid, compact"),
    ("f3", "F3  k = raised cosine, compact"),
    ("f4", "F4  k = constant, compact"),
)

#: Same three compact families, driven by their own tangent-length rule
#: d = min(r_h, r_m) sin(delta/2) instead of by an imported depth target.
ROWS_OWN = (
    ("d1", "D1  cubic  [reference]"),
    ("f2*", "F2  trapezoid"),
    ("f3*", "F3  raised cosine"),
    ("f4*", "F4  constant  ==  D1 exactly"),
)
CUBIC_RULES = {"c0": C0, "c1": C1, "d1": D1}

#: Which curvature shape, at matched depth: does a visible constant-radius
#: section read as a machined fillet?  F3 has none, F2 a third of the hump,
#: F5 two thirds, F4 all of it.
ROWS_SHAPE = (
    ("d1", "D1  cubic  [reference]"),
    ("f3", "F3  no plateau (raised cosine)"),
    ("f2", "F2  plateau 1/3 (trapezoid)"),
    ("f5", "F5  plateau 2/3 (taper 1/6)"),
    ("f4", "F4  plateau 3/3 (pure arc)"),
)

#: The recommendation, against the two it is between.
ROWS_FINAL = (
    ("d1", "D1  cubic (round-2 lead)"),
    ("f4", "F4  constant k -- pure arc, reads machined"),
    ("f3", "F3  raised cosine -- swoopiest, but runs short past d=83"),
    ("f6", "F6  adaptive taper: the smoothest k that reaches the depth"),
)

#: How much of the connector is straight: the exponent in d = min(r) sin(d/2)^p.
ROWS_SWOOP = (
    ("d1", "D1  cubic  [reference]"),
    ("f3@1.0", "F3  p = 1.0   (matches D1's depth rule)"),
    ("f3@0.75", "F3  p = 0.75"),
    ("f3@0.5", "F3  p = 0.5   (swoopier, but pops off the centre near overlap)"),
)


def build(kind, hour, minute, face, stems):
    """`kind` is a cubic key, or a hump key with optional `*` (its own tangent
    rule) or `@p` (tangent rule d = min(r) sin(delta/2)^p)."""
    if kind in CUBIC_RULES:
        return G.build_centerline(hour, minute, CUBIC_RULES[kind].rule, face, stems)
    if kind == "f1":
        return CV.build_beta_centerline(hour, minute, D1.rule, face, stems)
    if kind == "f6":
        return CV.build_compact_centerline(hour, minute, CV.adaptive_shape,
                                           D1.rule, face, stems)
    power = None
    if "@" in kind:
        kind, raw = kind.split("@")
        power = float(raw)
    own = kind.endswith("*")
    return CV.build_compact_centerline(
        hour, minute, CV.HUMP_SHAPES[kind.rstrip("*")],
        None if (own or power is not None) else D1.rule, face, stems,
        tangent_rule=(None if power is None
                      else CV.tangent_length_power(power)))


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


def annotate(cl, kind, centre):
    """Bottom-left caption for one panel."""
    drawn = G.norm(G.sub(cl.pivot, centre))
    note = f"s={drawn:.1f}"
    exact = getattr(cl, "exact_depth", None)
    if exact is not None and abs(exact - drawn) > 0.05:
        note += f"({exact:.1f})"
    note += f"  rev={reverse_turn(cl.points):.2f}d"
    if kind == "f1":
        note += "  FOLD" if cl.degenerate else f"  nu={cl.concentration:.3g}"
    elif kind[0] == "f":
        note += f"  d={cl.tangent_length:.0f}"
        if kind == "f6":
            import math as _m
            rho = CV.adaptive_taper(_m.acos(max(-1.0, min(1.0,
                                     cl.context.radial_dot))))
            note += f"  taper={rho:.2f}"
        if cl.clamped:
            note += "!"
    return note


def panel(cv, ox, oy, face, stems, hour, minute, kind, scale, index,
          zoom=1.0):
    box_w, box_h = face.width * scale, face.height * scale
    cv.rect(ox, oy, box_w, box_h, fill=S.PANEL, stroke="#242a31",
            stroke_width=0.8, rx=3)
    ref = G.build_centerline(hour, minute, D1.rule, face, stems)
    centre = ref.context.center
    cl = build(kind, hour, minute, face, stems)

    def T(p):
        return (ox + box_w / 2 + (p[0] - centre[0]) * scale * zoom,
                oy + box_h / 2 + (p[1] - centre[1]) * scale * zoom)

    cv.push_clip(ox, oy, box_w, box_h, f"cc{index}")
    for tip in (ref.hour_tip, ref.minute_tip):
        cv.line(*T(centre), *T(tip), stroke=S.GUIDE, stroke_width=0.5,
                opacity=0.7, dash="2 3")
    c = T(centre)
    cv.line(c[0] - 5, c[1], c[0] + 5, c[1], stroke=S.DIM, stroke_width=0.6)
    cv.line(c[0], c[1] - 5, c[0], c[1] + 5, stroke=S.DIM, stroke_width=0.6)
    if kind != "c0":
        base = G.build_centerline(hour, minute, C0.rule, face, stems)
        cv.polyline([T(p) for p in base.points], stroke=S.REFERENCE,
                    stroke_width=1.3, opacity=0.8)
    cv.polyline([T(p) for p in cl.points], stroke=S.INK, stroke_width=1.7)
    cv.circle(*T(cl.pivot), 2.0, fill=S.PIVOT)
    cv.pop()

    rv = reverse_turn(cl.points)
    cv.text(ox + 4, oy + box_h - 5, annotate(cl, kind, centre), size=7,
            fill="#f95d6a" if rv > 0.5 else S.DIM)


def sheet(stem_names, path, times=TIMES, scale=0.86, zoom=1.0, title=None,
          rows=ROWS):
    face = G.Face()
    gap, left, top = 8, 232, 152
    pw, ph = face.width * scale, face.height * scale
    blocks = len(stem_names)
    cv = S.Canvas(left + len(times) * (pw + gap) + 16,
                  top + blocks * (len(rows) * (ph + gap) + 34) + 10)
    cv.text(24, 32, title or "Connector constructions compared", size=17,
            fill=S.LABEL, weight="600")
    cv.text(24, 52, "white = construction     amber = C0 current, as reference "
            "underlay     dashed = the two hand radials     blue dot = closest "
            "approach to centre", size=10, fill=S.DIM)
    cv.text(24, 70, "C0/C1/D1 place a pivot then interpolate.  F1-F4 prescribe "
            "k(s) and solve for geometry, all driven to D1's depth so the "
            "families differ only in the shape of k.", size=10, fill=S.DIM)
    cv.text(24, 88, "s = depth of the drawn line's closest approach; (x) = the "
            "dense solved curve's, where the 30-segment render cannot resolve "
            "it.   rev = reverse turn, red above 0.5 deg.", size=10, fill=S.DIM)
    cv.text(24, 106, "nu = curvature concentration (F1).   d = tangent length "
            "from the centre (F2-F4); ! = the depth target is beyond that "
            "family's reach and d is clamped to min(r_h, r_m).",
            size=10, fill=S.DIM)

    for col, (hour, minute) in enumerate(times):
        x = left + col * (pw + gap)
        cv.text(x + pw / 2, top - 8,
                f"{hour % 12 or 12}:{minute:02d}   d={G.separation_degrees(hour, minute):.1f}",
                size=10, fill=S.LABEL, anchor="middle", weight="600")

    idx = 0
    y = top
    for name in stem_names:
        stems = G.STEMS_BY_NAME[name]
        cv.text(24, y - 28, f"stems: {name}   {stems.describe()}", size=11,
                fill=S.PIVOT, weight="600")
        for kind, label in rows:
            cv.text(24, y + 18, label, size=10, fill=S.LABEL, weight="600")
            for col, (hour, minute) in enumerate(times):
                panel(cv, left + col * (pw + gap), y, face, stems, hour, minute,
                      kind, scale, idx, zoom)
                idx += 1
            y += ph + gap
        y += 34
    cv.write(path)
    print("wrote", path)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    for name in ("current", "strong-asym"):
        sheet([name], os.path.join(OUT, f"constructions-{name}.svg"))
        sheet([name], os.path.join(OUT, f"final-{name}.svg"), rows=ROWS_FINAL,
              title="The recommendation: F6 adaptive taper")
        sheet([name], os.path.join(OUT, f"final-zoom-{name}.svg"),
              rows=ROWS_FINAL, times=ZOOM_TIMES, zoom=2.6,
              title="The recommendation, 2.6x on the centre")
        sheet([name], os.path.join(OUT, f"shapes-{name}.svg"), rows=ROWS_SHAPE,
              title="Which curvature shape, at matched depth")
        sheet([name], os.path.join(OUT, f"shapes-zoom-{name}.svg"),
              rows=ROWS_SHAPE, times=ZOOM_TIMES, zoom=2.6,
              title="Which curvature shape, 2.6x on the centre")
        sheet([name], os.path.join(OUT, f"swoop-{name}.svg"), rows=ROWS_SWOOP,
              title="How much of the connector is straight: the exponent p")
        sheet([name], os.path.join(OUT, f"constructions-zoom-{name}.svg"),
              times=ZOOM_TIMES, zoom=2.6,
              title="Near overlap, 2.6x on the centre: d = 5.5 to 44 degrees")
    sheet(["current", "strong-asym"], os.path.join(OUT, "constructions-own-d.svg"),
          rows=ROWS_OWN,
          title="Compact families on their own dial: d = min(r_h, r_m) sin(d/2)")
