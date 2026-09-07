#!/usr/bin/env python3
"""Render the pivot study as a standalone HTML page (centreline only)."""

import math, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pivot_study import *  # noqa

TIMES = [(12, 0), (12, 1), (12, 5), (12, 10), (12, 15), (12, 20), (12, 25), (6, 0)]
ZOOM_TIMES = [(12, 0), (12, 1), (12, 5), (12, 10), (12, 15), (12, 20)]

def label(H, M):
    th, tm = angles_for(H, M)
    return f"{H}:{M:02d}", f"{math.degrees(math.pi - abs(turn_angle(th, tm))):.0f}°"

CANDIDATES = [
    ("A0", "Shipping build", "bisector guide, offset 0.15·R·f(Δ)", m_current),
    ("A1", "Guide pinned to the centre", "same solver, guide point = pin", m_guide_center),
    ("A1s", "Guide at centre, symmetric stems", "both stems end at 0.50·R", m_guide_center_symmetric),
    ("B1", "Corner conic, w = tan(Θ/2)", "rational quadratic, apex = pin", m_conic),
    ("B1p", "Corner conic, w = tan²(Θ/2)", "same family, tighter hug", lambda a, b: m_conic_pow(a, b, 2.0)),
    ("B2", "Cubic, handles reach the pin", "control points at the centre (λ = 1)", m_cubic_reach),
    ("B2o", "Cubic, handles overshoot", "λ = 4/3, handles pass the centre", m_cubic_overshoot),
    ("C1", "Swing, window h = 0.2 × hour hand", "signed radius, turn spread over |u| < h", make_swing(12.0)),
    ("C2", "Swing, window h = 0.25·R", "same, wider turn window", make_swing(25.0)),
    ("Cκ", "Swing, constant fold radius", "h = 1.5·ρ₀·|Θ|, ρ₀ = 5 px", make_swing_constant_fold(5.0)),
    ("CΔ", "Swing, window h = 0.40·R·Δ/180°", "rounding read straight off the hand angle", make_swing_by_separation(40.0)),
    ("C0", "Swing, hard pivot (h = 0)", "two straight radial legs", m_swing_hard),
    ("E1", "Shrinking corner", "biarc, stems run in to r ∝ Δ", make_shrinking_corner()),
    ("D1", "Winding loop", "swing with one extra revolution", make_loop(18.0)),
]

CONTROLS = [
    ("X1", "Circular biarc", "equal-tangent G1 arc pair", m_biarc),
    ("X2", "Euler-spiral corner", "G2 clothoid, closure-solved", m_clothoid),
]

ZOOM_ROWS = [
    ("A0", "Shipping build", m_current),
    ("A1", "Guide at centre", m_guide_center),
    ("B1p", "Corner conic tan²", lambda a, b: m_conic_pow(a, b, 2.0)),
    ("C1", "Swing h = 12 px", make_swing(12.0)),
    ("Cκ", "Swing, const. fold radius", make_swing_constant_fold(5.0)),
    ("CΔ", "Swing, h ∝ Δ", make_swing_by_separation(40.0)),
    ("D1", "Winding loop", make_loop(18.0)),
    ("X2", "Euler-spiral (control)", m_clothoid),
]

CHART_METHODS = [
    ("A0 shipping", m_current),
    ("B1 corner conic", m_conic),
    ("B1p conic tan²", lambda a, b: m_conic_pow(a, b, 2.0)),
    ("E1 shrinking corner", make_shrinking_corner()),
    ("C1 swing", make_swing(12.0)),
    ("CΔ swing h∝Δ", make_swing_by_separation(40.0)),
    ("X1 biarc", m_biarc),
    ("X2 clothoid", m_clothoid),
]

def head_row(times, cols):
    h = f'<div class="grid" style="--n:{cols}"><div class="rowhead"></div>'
    for H, M in times:
        t, d = label(H, M)
        h += f'<div class="colhead"><b>{t}</b><span>{d}</span></div>'
    return h + "</div>"

def method_rows(rows, times, view=104.0, size=112, chrome=True, show_off=True):
    out = []
    for key, name, sub, fn in rows:
        r = [f'<div class="grid" style="--n:{len(times)}">',
             f'<div class="rowhead"><b>{key}</b><span>{name}</span><em>{sub}</em></div>']
        for H, M in times:
            th, tm = angles_for(H, M)
            pts = fn(th, tm)
            off = min_distance_to_origin(pts)
            cls = "ok" if off < 3.0 else ("warn" if off < 12.0 else "bad")
            badge = f'<span class="off {cls}">{off:.1f}</span>' if show_off else ""
            r.append(f'<div class="cell">{panel_svg(pts, size=size, view=view, chrome=chrome)}{badge}</div>')
        r.append("</div>")
        out.append("".join(r))
    return "\n".join(out)

def build_chart():
    series = []
    for name, fn in CHART_METHODS:
        data = []
        for i in range(0, 181):
            d = math.radians(i)
            th, tm = 0.0, d          # separation d, hour hand at 12
            data.append((i, min_distance_to_origin(fn(th, tm))))
        series.append((name, data))
    legend = "".join(f'<span class="lg l{i}">{n}</span>' for i, (n, _) in enumerate(series))
    return offset_chart_svg(series), legend

CSS = """
:root{--bg:#fbfaf7;--fg:#1b1a18;--mut:#77726a;--line:#1b1a18;--tick:#c3bcb0;
 --pin:#c8511f;--rule:#e2ddd4;--scr:#f1eee8;--ok:#2f6b41;--warn:#8a6a12;--bad:#a33a20;}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){
 --bg:#131313;--fg:#eeece7;--mut:#9a948b;--line:#f4f1ea;--tick:#3d3c38;
 --pin:#ff8a5c;--rule:#2b2a27;--scr:#1c1c1a;--ok:#6fbc86;--warn:#d6a83c;--bad:#ee7a58;}}
:root[data-theme=dark]{--bg:#131313;--fg:#eeece7;--mut:#9a948b;--line:#f4f1ea;
 --tick:#3d3c38;--pin:#ff8a5c;--rule:#2b2a27;--scr:#1c1c1a;--ok:#6fbc86;--warn:#d6a83c;--bad:#ee7a58;}
body{background:var(--bg);color:var(--fg);margin:0;padding:26px 20px 60px;
 font:14px/1.55 ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
.wrap{max-width:1160px;margin:0 auto}
h1{font-size:1.45rem;margin:0 0 .3em;letter-spacing:-.01em}
h2{font-size:.82rem;margin:2.6em 0 .6em;letter-spacing:.1em;text-transform:uppercase;color:var(--mut)}
p{max-width:72ch}
.note{color:var(--mut);font-size:.85rem;max-width:72ch}
.scroll{overflow-x:auto;padding-bottom:4px}
.grid{display:grid;grid-template-columns:200px repeat(var(--n),112px);align-items:center;
 min-width:calc(200px + var(--n)*112px)}
.colhead{text-align:center;padding:6px 0 10px;line-height:1.25}
.colhead b{display:block;font-size:.82rem}
.colhead span{display:block;font-size:.72rem;color:var(--mut);font-variant-numeric:tabular-nums}
.rowhead{padding:8px 14px 8px 0;border-top:1px solid var(--rule);height:100%;
 display:flex;flex-direction:column;justify-content:center}
.rowhead b{font-size:.7rem;color:var(--mut);letter-spacing:.08em}
.rowhead span{font-size:.85rem;font-weight:600;line-height:1.3}
.rowhead em{font-size:.72rem;color:var(--mut);font-style:normal;line-height:1.35;margin-top:2px}
.cell{position:relative;border-top:1px solid var(--rule);display:flex;justify-content:center}
.off{position:absolute;right:5px;bottom:5px;font-size:.66rem;font-variant-numeric:tabular-nums}
.ok{color:var(--ok)}.warn{color:var(--warn)}.bad{color:var(--bad);font-weight:700}
svg .scr{fill:var(--scr)}
svg .face{fill:none;stroke:var(--tick);stroke-width:.8;opacity:.55}
svg .tk{stroke:var(--tick);stroke-linecap:round}
svg .ln{fill:none;stroke:var(--line);stroke-linejoin:round;stroke-linecap:round}
svg .pin{fill:var(--pin)}
svg .fold{fill:none;stroke:var(--pin);opacity:.8}
.chart{height:212px;display:block}
.chart .grid{stroke:var(--rule);stroke-width:1;display:block}
.chart .axis{fill:var(--mut);font-size:10px}
.chart polyline{fill:none;stroke-width:2}
.chart .s0{stroke:#c8511f}.chart .s1{stroke:#2f6b9e}.chart .s2{stroke:#4f9bd6;stroke-dasharray:5 3}
.chart .s3{stroke:#8a5ea8}.chart .s4{stroke:#2f8b52;stroke-width:2.6}
.chart .s5{stroke:#9a948b;stroke-dasharray:3 3}.chart .s6{stroke:#b0a898;stroke-dasharray:3 3}
.chart .s7{stroke:#c0b8a8;stroke-dasharray:3 3}
.lg{font-size:.75rem;margin-right:13px;white-space:nowrap;display:inline-block}
.lg::before{content:"";display:inline-block;width:14px;height:2px;vertical-align:middle;margin-right:5px}
.l0::before{background:#c8511f}.l1::before{background:#2f6b9e}.l2::before{background:#4f9bd6}
.l3::before{background:#8a5ea8}.l4::before{background:#2f8b52}.l5::before{background:#9a948b}
.l6::before{background:#b0a898}
.l7::before{background:#c0b8a8}
"""

def main():
    chart, legend = build_chart()
    html = f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Calligraphy pivot study</title><style>{CSS}</style></head><body><div class="wrap">
<h1>Calligraphy &mdash; central-segment constructions</h1>
<p class="note">Centreline only, no width envelope. Orange dot = true watch centre.
Ring = the curve's closest approach to it; the number is that distance in pixels
(R&nbsp;=&nbsp;100, emery/gabbro). Columns give clock time and the angle between the hands.</p>

<h2>Candidates</h2>
<div class="scroll">{head_row(TIMES, len(TIMES))}
{method_rows(CANDIDATES, TIMES)}</div>

<h2>Reference: smooth-curvature families (why they fail)</h2>
<div class="scroll">{head_row(TIMES, len(TIMES))}
{method_rows(CONTROLS, TIMES)}</div>

<h2>The fold, magnified (central 80 &times; 80 px)</h2>
<div class="scroll">{head_row(ZOOM_TIMES, len(ZOOM_TIMES))}
{method_rows([(k, n, "", f) for k, n, f in ZOOM_ROWS], ZOOM_TIMES, view=40.0, chrome=False, show_off=False)}</div>

<h2>Pivot offset vs. hand separation</h2>
<div>{chart}</div><div>{legend}</div>
<p class="note">The separation angle sweeps 0&deg;&nbsp;&rarr;&nbsp;180&deg; and back once every
65&nbsp;min&nbsp;27&nbsp;s, so this curve is the whole story: the shipping build's pivot
wanders out to 12.9&nbsp;px and back eleven times per 12&nbsp;hours.</p>
</div></body></html>"""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out", "study.html")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w").write(html)
    print(path)

if __name__ == "__main__":
    main()
