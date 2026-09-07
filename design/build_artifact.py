#!/usr/bin/env python3
"""Build the Calligraphy pivot-study artifact page."""

import math, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pivot_study import *  # noqa

TIMES = [(12, 0), (12, 1), (12, 5), (12, 10), (12, 15), (12, 20), (12, 25), (6, 0)]
ZOOM = [(12, 0), (12, 1), (12, 5), (12, 10), (12, 15), (12, 20)]

def sep_deg(H, M):
    th, tm = angles_for(H, M)
    return math.degrees(math.pi - abs(turn_angle(th, tm)))

def pts_str(points, nd=1):
    return " ".join(f"{p[0]:.{nd}f},{p[1]:.{nd}f}" for p in points)

def panel(points, view=104.0, chrome=True, fold=True):
    p = simplify(points, 0.10)
    s = view / 104.0
    b = []
    if chrome:
        b.append('<rect class="scr" x="-100" y="-114" width="200" height="228" rx="24"/>')
        for i in range(12):
            u = ray(2 * math.pi * i / 12)
            major = i % 3 == 0
            inner = 100 - (10 if major else 5)
            b.append(f'<line class="tk" x1="{u[0]*99:.1f}" y1="{u[1]*99:.1f}" '
                     f'x2="{u[0]*inner:.1f}" y2="{u[1]*inner:.1f}" '
                     f'stroke-width="{3.0 if major else 1.5}"/>')
    else:
        b.append(f'<rect class="scr" x="{-view:.0f}" y="{-view:.0f}" width="{2*view:.0f}" '
                 f'height="{2*view:.0f}" rx="{5*s:.1f}"/>')
        for i in range(12):
            u = ray(2 * math.pi * i / 12)
            b.append(f'<line class="tk" x1="{u[0]*view*.96:.1f}" y1="{u[1]*view*.96:.1f}" '
                     f'x2="{u[0]*view*.87:.1f}" y2="{u[1]*view*.87:.1f}" stroke-width="{1.5*s:.2f}"/>')
    b.append(f'<polyline class="ln" points="{pts_str(p)}" stroke-width="{2.7*s:.2f}"/>')
    if fold:
        f = closest_point_to_origin(p)
        b.append(f'<circle class="fold" cx="{f[0]:.1f}" cy="{f[1]:.1f}" r="{7*s:.1f}" '
                 f'stroke-width="{1.5*s:.2f}"/>')
    b.append(f'<circle class="pin" cx="0" cy="0" r="{3.2*s:.2f}"/>')
    return (f'<svg viewBox="{-view:.0f} {-view:.0f} {2*view:.0f} {2*view:.0f}" '
            f'aria-hidden="true">' + "".join(b) + "</svg>")

def grid(rows, times, view=104.0, chrome=True, fold=True, badge=True):
    n = len(times)
    out = [f'<div class="rail"><div class="gr" style="--n:{n}">',
           '<div class="rh rh--head"></div>']
    for H, M in times:
        out.append(f'<div class="ch"><b>{H}:{M:02d}</b><span>{sep_deg(H,M):.0f}&deg;</span></div>')
    out.append("</div>")
    for code, name, sub, fn in rows:
        out.append(f'<div class="gr" style="--n:{n}">')
        sub_html = f'<em>{sub}</em>' if sub else ""
        out.append(f'<div class="rh"><b>{code}</b><span>{name}</span>{sub_html}</div>')
        for H, M in times:
            th, tm = angles_for(H, M)
            pl = fn(th, tm)
            off = min_distance_to_origin(pl)
            cls = "g" if off < 3 else ("a" if off < 12 else "r")
            tag = f'<span class="off {cls}">{off:.1f}</span>' if badge else ""
            out.append(f'<div class="cl">{panel(pl, view, chrome, fold)}{tag}</div>')
        out.append("</div>")
    out.append("</div>")
    return "".join(out)

# --------------------------------------------------------------------------

CANDIDATES = [
    ("A0", "Shipping build", "guide point on the bisector, offset 0.15&middot;R&middot;f(&Delta;)", m_current),
    ("A1", "Guide pinned to the centre", "same bending solver, guide point = the pin", m_guide_center),
    ("A1s", "Guide at the pin, symmetric stems", "both stems end at 0.50&middot;R", m_guide_center_symmetric),
    ("B1", "Corner conic, w = tan(&Theta;/2)", "rational quadratic, apex = the pin", m_conic),
    ("B1p", "Corner conic, w = tan&sup2;(&Theta;/2)", "same family, tighter hug", lambda a, b: m_conic_pow(a, b, 2.0)),
    ("B2", "Cubic, handles reach the pin", "both control points at the centre (&lambda; = 1)", m_cubic_reach),
    ("B2o", "Cubic, handles overshoot", "&lambda; = 4/3 &mdash; the hull now contains the pin", m_cubic_overshoot),
    ("C1", "Swing, fixed window h = 12 px", "signed radius; turn spread over |u| &lt; h", make_swing(12.0)),
    ("C&kappa;", "Swing, constant fold radius", "h = 1.5&middot;&rho;&#8320;&middot;|&Theta;|, &rho;&#8320; = 5 px", make_swing_constant_fold(5.0)),
    ("C&Delta;", "Swing, window h &prop; &Delta;", "h = 0.40&middot;R&middot;&Delta;/180&deg;", make_swing_by_separation(40.0)),
    ("C0", "Swing, hard pivot (h = 0)", "two straight radial legs, corner on the pin", m_swing_hard),
    ("E1", "Shrinking corner", "biarc, but the stems run in to r &prop; &Delta;", make_shrinking_corner()),
    ("D1", "Winding loop", "swing carrying one extra revolution", make_loop(18.0)),
]

CONTROLS = [
    ("X1", "Circular biarc", "equal-tangent G&sup1; arc pair", m_biarc),
    ("X2", "Euler-spiral corner", "G&sup2; clothoid, closure-solved", m_clothoid),
]

ZOOM_ROWS = [
    ("A0", "Shipping build", "", m_current),
    ("A1", "Guide at the pin", "", m_guide_center),
    ("B1p", "Corner conic tan&sup2;", "", lambda a, b: m_conic_pow(a, b, 2.0)),
    ("C1", "Swing, h = 12 px", "", make_swing(12.0)),
    ("C&Delta;", "Swing, h &prop; &Delta;", "", make_swing_by_separation(40.0)),
    ("D1", "Winding loop", "", make_loop(18.0)),
    ("X2", "Euler spiral (control)", "", m_clothoid),
]

CHART = [
    ("A0", "Shipping build", m_current, "s0"),
    ("B1", "Corner conic tan", m_conic, "s1"),
    ("B1p", "Corner conic tan&sup2;", lambda a, b: m_conic_pow(a, b, 2.0), "s2"),
    ("E1", "Shrinking corner", make_shrinking_corner(), "s3"),
    ("X1", "Circular biarc", m_biarc, "s4"),
    ("C&Delta;", "Swing / guide at pin", make_swing_by_separation(40.0), "s5"),
]

def chart_svg():
    W, H = 900, 320
    L, Rm, T, B = 52, 22, 24, 46
    iw, ih = W - L - Rm, H - T - B
    ymax = 50.0
    def X(a): return L + iw * a / 180.0
    def Y(v): return T + ih * (1.0 - min(v, ymax) / ymax)
    p = [f'<svg viewBox="0 0 {W} {H}" class="chart" role="img" '
         f'aria-label="Pivot offset against hand separation for each construction">']
    p.append(f'<rect class="band" x="{L}" y="{Y(3):.1f}" width="{iw}" height="{T+ih-Y(3):.1f}"/>')
    for v in (0, 10, 20, 30, 40, 50):
        p.append(f'<line class="gl" x1="{L}" y1="{Y(v):.1f}" x2="{L+iw}" y2="{Y(v):.1f}"/>')
        p.append(f'<text class="ax" x="{L-9}" y="{Y(v)+4:.1f}" text-anchor="end">{v}</text>')
    for a in range(0, 181, 30):
        p.append(f'<line class="gl gl--v" x1="{X(a):.1f}" y1="{T}" x2="{X(a):.1f}" y2="{T+ih}"/>')
        p.append(f'<text class="ax" x="{X(a):.1f}" y="{T+ih+18}" text-anchor="middle">{a}&#176;</text>')
    p.append(f'<text class="axl" x="{L+iw/2:.0f}" y="{H-8}" text-anchor="middle">'
             f'angle between the hands</text>')
    p.append(f'<text class="axl" x="{L-9}" y="{T-6}" text-anchor="end">px</text>')
    p.append(f'<text class="bandl" x="{L+iw-8}" y="{T+ih-8}" text-anchor="end">'
             f'C&Delta; &middot; on the pin (&lt; 3 px)</text>')
    for code, name, fn, cls in CHART:
        data = [(a, min_distance_to_origin(fn(0.0, math.radians(a)))) for a in range(0, 181)]
        pts = " ".join(f"{X(a):.1f},{Y(v):.1f}" for a, v in data)
        p.append(f'<polyline class="ser {cls}" points="{pts}"/>')
        # label each trace at its own peak, nudged clear of the curve
        pa, pv = max(data, key=lambda d: d[1])
        if code not in ("A0", "C&Delta;"):
            anchor = "start" if pa < 120 else "end"
            dx = 8 if anchor == "start" else -8
            p.append(f'<text class="lbl {cls}" x="{X(pa)+dx:.1f}" y="{Y(pv)-13:.1f}" '
                     f'text-anchor="{anchor}">{code}</text>')
    # peak callout for the shipping build
    data = [(a, min_distance_to_origin(m_current(0.0, math.radians(a)))) for a in range(0, 181)]
    pa, pv = max(data, key=lambda d: d[1])
    p.append(f'<circle class="dot s0" cx="{X(pa):.1f}" cy="{Y(pv):.1f}" r="4.5"/>')
    p.append(f'<text class="call" x="{X(pa)-11:.1f}" y="{Y(pv)+16:.1f}" text-anchor="end">'
             f'A0 peak {pv:.1f} px</text>')
    p.append("</svg>")
    return "".join(p)

def label_chart_legend():
    return "".join(
        f'<span class="lg {c}"><i></i>{code} &middot; {n}</span>' for code, n, _, c in CHART)

def diagram_svg():
    th, tm = math.radians(-41), math.radians(41)
    A, Bp = on_clock(th, R_A), on_clock(tm, R_B)
    ht, mt = on_clock(th, HOUR_LENGTH), on_clock(tm, MINUTE_LENGTH)
    curve = simplify(make_swing_by_separation(40.0)(th, tm), 0.08)
    d = []
    d.append('<circle class="dface" cx="0" cy="0" r="100"/>')
    for i in range(12):
        u = ray(2 * math.pi * i / 12)
        d.append(f'<line class="tk" x1="{u[0]*99:.1f}" y1="{u[1]*99:.1f}" '
                 f'x2="{u[0]*91:.1f}" y2="{u[1]*91:.1f}" stroke-width="1.6"/>')
    # tangent lines, both of which run through the pin
    for P, ang in ((A, th), (Bp, tm)):
        far = on_clock(ang, -22.0)
        d.append(f'<line class="tan" x1="{P[0]:.1f}" y1="{P[1]:.1f}" '
                 f'x2="{far[0]:.1f}" y2="{far[1]:.1f}"/>')
    # apex angle arc
    rr = 30.0
    a0 = math.atan2(ray(th)[1], ray(th)[0])
    a1 = math.atan2(ray(tm)[1], ray(tm)[0])
    d.append(f'<path class="arc" d="M {rr*math.cos(a0):.1f} {rr*math.sin(a0):.1f} '
             f'A {rr} {rr} 0 0 1 {rr*math.cos(a1):.1f} {rr*math.sin(a1):.1f}"/>')
    d.append(f'<polyline class="ln" points="{pts_str(curve)}" stroke-width="3"/>')
    for P in (A, Bp):
        d.append(f'<circle class="knot" cx="{P[0]:.1f}" cy="{P[1]:.1f}" r="3.6"/>')
    d.append('<circle class="pin" cx="0" cy="0" r="4"/>')
    lab = [
        (ht[0] - 6, ht[1] - 9, "end", "hour tip 0.60&middot;R"),
        (mt[0] + 6, mt[1] - 9, "start", "minute tip 0.90&middot;R"),
        (A[0] - 8, A[1] + 4, "end", "A &middot; 0.45&middot;R"),
        (Bp[0] + 8, Bp[1] + 4, "start", "B &middot; 0.54&middot;R"),
        (0, rr + 15, "middle", "&Delta;"),
        (10, -8, "start", "pin"),
    ]
    for x, y, anc, t in lab:
        d.append(f'<text class="dl" x="{x:.1f}" y="{y:.1f}" text-anchor="{anc}">{t}</text>')
    return ('<svg viewBox="-138 -122 276 232" class="diagram" role="img" aria-label="The two '
            'stem tangent lines both pass through the watch centre, making the connector a '
            'corner-rounding problem whose apex is the pin">' + "".join(d) + "</svg>")

def main():
    here = os.path.dirname(os.path.abspath(__file__))
    tpl = open(os.path.join(here, "page_template.html")).read()
    html = (tpl
            .replace("__DIAGRAM__", diagram_svg())
            .replace("__GRID__", grid(CANDIDATES, TIMES))
            .replace("__CONTROLS__", grid(CONTROLS, TIMES))
            .replace("__ZOOM__", grid(ZOOM_ROWS, ZOOM, view=40.0, chrome=False,
                                      fold=False, badge=False))
            .replace("__CHART__", chart_svg())
            .replace("__LEGEND__", label_chart_legend()))
    out = os.path.join(here, "out", "pivot-study.html")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    open(out, "w").write(html)
    print(out, len(html), "bytes")

if __name__ == "__main__":
    main()
