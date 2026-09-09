#!/usr/bin/env python3
"""Numbers behind the seven-construction comparison.

    python3 families_report.py            # all 720 hand combinations
    python3 families_report.py --quick    # one hour, for a fast check

Writes out/families.md.  F1 is sampled rather than swept: its nested bisection
costs about four orders of magnitude more than the others.
"""
from __future__ import annotations
import math, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import geometry as G
import curvature as CV
from sheet_constructions import CUBIC_RULES, D1, turns, reverse_turn
from sheet_curvature import profile

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
FAMILIES = ("c0", "c1", "d1", "f1", "f2*", "f3*", "f4*")
LABELS = {"c0": "C0 cubic (current)", "c1": "C1 cubic", "d1": "D1 cubic",
          "f1": "F1 Beta", "f2*": "F2 trapezoid", "f3*": "F3 raised cosine",
          "f4*": "F4 constant"}
#: Full overlap and quadrature are the two cases the aesthetic spec pins down.
OVERLAP_MAX_PX = 2.0


def combos(quick):
    if quick:
        return [(12, m) for m in range(60)]
    return [(h, m) for h in range(12) for m in range(60)]


def build(kind, hour, minute, face, stems):
    if kind in CUBIC_RULES:
        return G.build_centerline(hour, minute, CUBIC_RULES[kind].rule, face, stems)
    if kind == "f1":
        return CV.build_beta_centerline(hour, minute, D1.rule, face, stems)
    return CV.build_compact_centerline(hour, minute,
                                       CV.HUMP_SHAPES[kind.rstrip("*")],
                                       None, face, stems)


def measure(kind, stems, quick):
    face = G.Face()
    worst_rev = 0.0
    worst_junction = 0.0
    crossings = 0
    overlap_depth = 0.0
    quad_depth, quad_gap = 0.0, 1e9
    ticks = combos(True) if kind == "f1" else combos(quick)
    for hour, minute in ticks:
        cl = build(kind, hour, minute, face, stems)
        worst_rev = max(worst_rev, reverse_turn(cl.points))
        _, ks = profile(kind, hour, minute, face, stems)
        peak = max(abs(k) for k in ks) or 1.0
        worst_junction = max(worst_junction,
                             max(abs(ks[0]), abs(ks[-1])) / peak)
        crossings += sum(1 for i in range(1, len(ks))
                         if ks[i - 1] * ks[i] < 0.0 and abs(ks[i]) > 1e-4 * peak)
        delta = G.separation_degrees(hour, minute)
        depth = getattr(cl, "exact_depth", None) or G.norm(
            G.sub(cl.pivot, cl.context.center))
        if delta < 1e-9:
            overlap_depth = max(overlap_depth, depth)
        if abs(delta - 90.0) < quad_gap:
            quad_gap, quad_depth = abs(delta - 90.0), depth
    return dict(rev=worst_rev, junction=worst_junction, cross=crossings,
                overlap=overlap_depth, quad=quad_depth, n=len(ticks))


def main(quick):
    os.makedirs(OUT, exist_ok=True)
    lines = ["# Connector families: measured",
             "",
             "`rev` = worst reverse turn in the drawn line, degrees (0 = never "
             "swerves).  `k(end)` = curvature at the stem junctions as a "
             "fraction of that connector's peak (0 = meets the straight stem "
             "with no curvature step).  `cross` = total sign changes of k over "
             "all hand positions.  `overlap` = depth at exact overlap, which "
             f"the spec caps at {OVERLAP_MAX_PX:.0f} px.  `d=90` = depth at "
             "quadrature, which the spec wants clearly non-zero.",
             ""]
    for name in ("current", "strong-asym", "short", "long", "symmetric",
                 "swapped"):
        stems = G.STEMS_BY_NAME[name]
        lines += [f"## stems: {name} -- {stems.describe()}", "",
                  "| family | rev | k(end) | cross | overlap | d=90 |",
                  "|---|---|---|---|---|---|"]
        for kind in FAMILIES:
            m = measure(kind, stems, quick)
            ok = "" if m["overlap"] <= OVERLAP_MAX_PX else " !"
            lines.append(
                f"| {LABELS[kind]} | {m['rev']:.2f} | {m['junction']:.3f} | "
                f"{m['cross']} | {m['overlap']:.2f}{ok} | {m['quad']:.2f} |")
        lines.append("")
        print("\n".join(lines[-(len(FAMILIES) + 4):]))
    path = os.path.join(OUT, "families.md")
    open(path, "w").write("\n".join(lines) + "\n")
    print("wrote", path)


if __name__ == "__main__":
    main("--quick" in sys.argv)
