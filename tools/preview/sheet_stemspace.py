#!/usr/bin/env python3
"""Where in (r_h, r_m) does D1 keep single-signed, single-peaked curvature?

    python3 sheet_stemspace.py

D1's connector depends on the stems only through the two inner radii: the rule
reads `min(r_h, r_m)` and `cos(delta)`, and the minimum-bending spans follow
from the pivot.  The hand *tips* do not enter it at all.  So the whole design
space for this question is two numbers, and it can be mapped exhaustively.

Three defects are measured independently, because they are not the same thing:

  swerve   k changes sign somewhere along the connector -- the curve bends back
  dip      |k| has a local minimum between two peaks -- the W flattening
  rev      the drawn line's turn reverses, in degrees (the visible symptom)

Each cell is the worst/share over a sweep of hand positions.
"""
from __future__ import annotations
import math, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import geometry as G
import svgcanvas as S

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
RULE = G.CANDIDATES_BY_KEY["d1-arc-sin"].rule

#: Stated floor: a stem may not start closer than a tenth of the face radius.
R_MIN, R_MAX, R_STEP = 0.10, 0.90, 0.05
K_SAMPLES = 40

#: Below this peak |k| the connector is straighter than a 1000 px radius, so a
#: dip in it is floating-point noise rather than a visible flattening.  Same
#: guard report.py uses, and for the same reason.
STRAIGHT_K = 1e-3
#: A dip shallower than this does not read as a flattening.
DIP_GATE = 0.02
#: Near overlap the hairpin's curvature is unbounded by design.
OVERLAP_GUARD_DEG = 20.0


def radii():
    n = int(round((R_MAX - R_MIN) / R_STEP)) + 1
    return [R_MIN + i * R_STEP for i in range(n)]


def profile(cl):
    ks = [G.curvature(cl.hour_connector, cl.pivot, cl.hour_derivative,
                      cl.guide_derivative, cl.hour_span, i / K_SAMPLES)
          for i in range(K_SAMPLES + 1)]
    ks += [G.curvature(cl.pivot, cl.minute_connector, cl.guide_derivative,
                       cl.minute_derivative, cl.minute_span, i / K_SAMPLES)
           for i in range(1, K_SAMPLES + 1)]
    return ks


def defects(ks):
    """(size of the reversed curvature lobe, size of the dip at the pivot).

    Both as a fraction of peak |k|, so both are scale-free.  A *binary* "does
    k change sign" flag turned out to be nearly useless: on the current stems
    D1's reversed lobe is real at a third of hand positions but never exceeds
    2.5% of peak, whereas under strongly asymmetric stems it reaches 25%.  The
    magnitude is the thing that decides whether anyone can see it.
    """
    peak = max(abs(k) for k in ks)
    if peak < STRAIGHT_K:
        return 0.0, 0.0
    dominant = 1.0 if sum(ks) > 0.0 else -1.0
    against = [abs(k) for k in ks if k * dominant < 0.0]
    lobe = max(against) / peak if against else 0.0

    mags = [abs(k) for k in ks]
    tops = [i for i in range(1, len(mags) - 1)
            if mags[i] >= mags[i - 1] and mags[i] >= mags[i + 1]]
    if not tops:
        return lobe, 0.0
    best = max(tops, key=lambda i: mags[i])
    dip = 0.0
    for other in tops:
        if other == best or mags[other] < 1e-12:
            continue
        a, b = min(other, best), max(other, best)
        trough = min(mags[a:b + 1])
        dip = max(dip, 1.0 - trough / mags[other])
    return lobe, dip


def turns(points):
    out = []
    for i in range(1, len(points) - 1):
        a = G.sub(points[i], points[i - 1]); b = G.sub(points[i + 1], points[i])
        na, nb = G.norm(a), G.norm(b)
        out.append(0.0 if na < 1e-9 or nb < 1e-9 else
                   math.degrees(math.atan2(G.cross(a, b) / (na * nb),
                                           G.dot(a, b) / (na * nb))))
    return out


def scan(r_h, r_m, face, hours):
    stems = G.Stems(name="scan", hour_inner=r_h, minute_inner=r_m,
                    hour_length=min(0.99, r_h + 0.02),
                    minute_length=min(0.99, r_m + 0.02))
    n = 0
    worst_lobe = worst_dip = worst_rev = 0.0
    for hour in hours:
        for minute in range(60):
            delta = G.separation_degrees(hour, minute)
            cl = G.build_centerline(hour, minute, RULE, face, stems)
            t = turns(cl.points)
            total = sum(t)
            worst_rev = max(worst_rev, sum(abs(v) for v in t
                                           if abs(v) > 0.02
                                           and (v > 0) != (total > 0)))
            if delta < OVERLAP_GUARD_DEG:
                continue
            n += 1
            lobe, dip = defects(profile(cl))
            worst_lobe = max(worst_lobe, lobe)
            worst_dip = max(worst_dip, dip)
    return dict(rev=worst_rev, lobe=100.0 * worst_lobe,
                dip=100.0 * worst_dip)


def grid(hours=(12, 1, 2, 3)):
    face = G.Face()
    rs = radii()
    return rs, {(i, j): scan(rh, rm, face, hours)
                for i, rh in enumerate(rs) for j, rm in enumerate(rs)}


def ramp(value, worst):
    """Green at zero, through amber, to red at `worst`."""
    if value <= 0.0:
        return "#1f6f4a"
    f = min(1.0, value / worst) ** 0.5
    r = int(60 + 195 * f); g = int(150 - 90 * f); b = int(80 - 40 * f)
    return f"#{r:02x}{g:02x}{b:02x}"


def sheet(path):
    rs, cells = grid()
    metrics = (("rev", "worst reverse turn in the drawn line (deg)", 8.0, "{:.1f}"),
               ("lobe", "largest reversed k lobe (% of peak |k|)", 25.0, "{:.1f}"),
               ("dip", "deepest dip in |k| at the pivot (% of peak)", 25.0, "{:.0f}"))
    cell, gap, left, top = 30, 2, 150, 150
    span = len(rs) * (cell + gap)
    cv = S.Canvas(left + len(metrics) * (span + 70) + 20, top + span + 90)
    cv.text(24, 32, "D1: the clean region in stem space", size=17,
            fill=S.LABEL, weight="600")
    cv.text(24, 52, "D1's connector depends on the stems only through the two "
            "inner radii r_h and r_m (as fractions of the face radius); the "
            "hand tips do not enter it.", size=10, fill=S.DIM)
    cv.text(24, 70, "Each cell sweeps 240 hand positions.  Green = defect "
            "absent everywhere.  Curvature metrics skip separations under "
            f"{OVERLAP_GUARD_DEG:.0f} deg, where the hairpin is intended.",
            size=10, fill=S.DIM)
    cv.text(24, 88, "x = r_h (hour stem start), y = r_m (minute stem start).  "
            "The diagonal is symmetric stems.", size=10, fill=S.DIM)

    for m, (key, label, worst, fmt) in enumerate(metrics):
        ox = left + m * (span + 70)
        cv.text(ox, top - 24, label, size=10, fill=S.LABEL, weight="600")
        for i, rh in enumerate(rs):
            for j, rm in enumerate(rs):
                v = cells[(i, j)][key]
                x = ox + i * (cell + gap)
                y = top + (len(rs) - 1 - j) * (cell + gap)
                cv.rect(x, y, cell, cell, fill=ramp(v, worst), rx=2)
                cv.text(x + cell / 2, y + cell / 2 + 3, fmt.format(v), size=7,
                        fill="#0d0f12" if v <= 0.0 else "#ffffff",
                        anchor="middle")
        for i, r in enumerate(rs):
            if i % 2 == 0:
                cv.text(ox + i * (cell + gap) + cell / 2, top + span + 14,
                        f"{r:.2f}", size=8, fill=S.DIM, anchor="middle")
                cv.text(ox - 6, top + (len(rs) - 1 - i) * (cell + gap)
                        + cell / 2 + 3, f"{r:.2f}", size=8, fill=S.DIM,
                        anchor="end")
    cv.write(path)
    print("wrote", path)
    return rs, cells


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    rs, cells = sheet(os.path.join(OUT, "stemspace.svg"))
    for name, gate in (("lobe", 1.0), ("lobe", 5.0), ("dip", 2.0)):
        ok = [(rs[i], rs[j]) for (i, j), c in cells.items() if c[name] <= gate]
        ratios = [rm / rh for rh, rm in ok]
        print(f"{name} <= {gate}%: {len(ok)} of {len(cells)} cells" +
              (f", r_m/r_h in [{min(ratios):.2f}, {max(ratios):.2f}]"
               if ok else ""))
    best = min(cells.values(), key=lambda c: c["rev"])
    print(f"lowest reverse turn anywhere in the space: {best['rev']:.2f} deg")
