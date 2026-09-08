#!/usr/bin/env python3
"""Render and analyse connector-pivot candidates for the Calligraphy watchface.

Centerline only -- this deliberately does not model the stroke, the width
profile, or Pebble's gpath rasterization.  See README.md.

    python3 tools/preview/report.py --all
"""

from __future__ import annotations

import argparse
import math
import os
from dataclasses import dataclass

import geometry as G
import svgcanvas as S

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")

DEFAULT_TIMES: tuple[tuple[int, int], ...] = (
    (12, 0),    # exact overlap
    (1, 5),     # the hairpin just off overlap
    (12, 7),
    (3, 0),
    (10, 10),
    (3, 49),    # delta = 179.5 -- near opposition, where an off-axis pivot bites
)

#: Positions this close to overlap are the accepted degenerate hairpin; their
#: unbounded curvature is by design, so tightness metrics skip them.
OVERLAP_GUARD_DEG = 20.0

#: Round 1 roster followed by round 2, de-duplicated by key.
def _all_candidates():
    seen, out = set(), []
    for candidate in G.ROUND2 + G.CANDIDATES:
        if candidate.key not in seen:
            seen.add(candidate.key)
            out.append(candidate)
    return tuple(out)

ALL_CANDIDATES = _all_candidates()

SWERVE_GATE_PX = 0.05
#: A dip deeper than this reads as the curve flattening at the pivot.
DIP_GATE = 0.02

#: Below this peak |k| the connector is straighter than a 1000 px radius -- ten
#: times the face. A straight line cannot "flatten at the pivot", and measuring
#: a dip in floating-point noise produces 100% readings from nothing, so both
#: the metric and the plots treat such positions as straight.
STRAIGHT_K = 1e-3

#: A connector whose total departure from its own chord is under half a pixel is
#: not a shape anyone can see, so a curvature dip in it is not a visible defect.
#: This matters near opposition, where the geometry is sub-pixel by design.
STRAIGHT_BOW_PX = 0.5

#: The headroom ratio s / arc_apex_ceiling is only meaningful while the ceiling
#: is an appreciable length; approaching opposition both terms vanish and the
#: ratio tends to a limit that says nothing about the shape.
HEADROOM_MIN_CEILING_PX = 2.0
CURVE_SAMPLES = 96


def label_time(hour: int, minute: int) -> str:
    display = hour % 12 or 12
    return f"{display}:{minute:02d}"


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

@dataclass
class Position:
    delta: float
    swerve: float            # px on the wrong side of the chord
    sign_changes: int        # analytic curvature sign flips
    joint_jump: float        # |dk| at the pivot, relative to peak |k|
    min_radius: float        # px, 1 / peak |k|
    depth: float             # |P - C|, px
    inside_triangle: bool
    solver_ok: bool
    turn_hour: float         # deg
    turn_minute: float       # deg
    peak_k_hour: float
    peak_k_minute: float
    curvature_dip: float     # depth of an interior |k| minimum, 0 = unimodal
    peak_at_pivot: bool      # is the single |k| maximum at the pivot?
    headroom: float          # s / arc_apex_ceiling

    @property
    def unimodal(self) -> bool:
        return self.curvature_dip <= DIP_GATE

    @property
    def turn_share(self) -> float:
        total = abs(self.turn_hour) + abs(self.turn_minute)
        return 0.5 if total < 1e-9 else abs(self.turn_hour) / total


def _sample_half(p0, p1, d0, d1, parameter_length, samples):
    """Inlined Hermite evaluation: position, d1 and d2 as flat float lists.

    The metrics sweep evaluates this several million times (candidates x stem
    configs x 720 positions), so it avoids the tuple churn of hermite_jet.
    geometry.hermite_jet stays the readable reference; test_harness.py asserts
    the two agree.
    """
    ax, ay = p0
    cx, cy = p1
    bx, by = d0[0] * parameter_length, d0[1] * parameter_length
    dx, dy = d1[0] * parameter_length, d1[1] * parameter_length

    px, py, vx, vy, wx, wy = [], [], [], [], [], []
    step = 1.0 / samples
    for i in range(samples + 1):
        t = i * step
        t2 = t * t
        t3 = t2 * t
        h0 = 2 * t3 - 3 * t2 + 1
        h1 = t3 - 2 * t2 + t
        h2 = -2 * t3 + 3 * t2
        h3 = t3 - t2
        px.append(h0 * ax + h1 * bx + h2 * cx + h3 * dx)
        py.append(h0 * ay + h1 * by + h2 * cy + h3 * dy)
        g0 = 6 * t2 - 6 * t
        g1 = 3 * t2 - 4 * t + 1
        g2 = -6 * t2 + 6 * t
        g3 = 3 * t2 - 2 * t
        vx.append(g0 * ax + g1 * bx + g2 * cx + g3 * dx)
        vy.append(g0 * ay + g1 * by + g2 * cy + g3 * dy)
        k0 = 12 * t - 6
        k1 = 6 * t - 4
        k2 = -12 * t + 6
        k3 = 6 * t - 2
        wx.append(k0 * ax + k1 * bx + k2 * cx + k3 * dx)
        wy.append(k0 * ay + k1 * by + k2 * cy + k3 * dy)
    return px, py, vx, vy, wx, wy


def _curvature_list(vx, vy, wx, wy):
    out = []
    for i in range(len(vx)):
        speed = (vx[i] * vx[i] + vy[i] * vy[i]) ** 0.5
        out.append(0.0 if speed < 1e-9
                   else (vx[i] * wy[i] - vy[i] * wx[i]) / speed ** 3)
    return out


def _turn_from(vx, vy) -> float:
    total = 0.0
    previous = None
    for i in range(len(vx)):
        if vx[i] * vx[i] + vy[i] * vy[i] < 1e-18:
            continue
        angle = math.atan2(vy[i], vx[i])
        if previous is not None:
            step = angle - previous
            while step > math.pi:
                step -= 2 * math.pi
            while step < -math.pi:
                step += 2 * math.pi
            total += step
        previous = angle
    return math.degrees(total)


def _curvature_dip(k_hour: list[float], k_minute: list[float],
                   bow: float = float("inf")) -> tuple[float, bool]:
    """How far |k| dips between its two flanking peaks, and whether the single
    maximum sits at the pivot.

    0.0 means unimodal -- |k| rises to one peak and falls. A positive value is
    the "W": the curve has flattened around the pivot, with the tighter bends
    pushed out to either side. Returned as a fraction of the shallower flanking
    peak, so it is scale-free.
    """
    magnitudes = [abs(v) for v in k_hour] + [abs(v) for v in k_minute[1:]]
    if max(magnitudes) < STRAIGHT_K or bow < STRAIGHT_BOW_PX:
        return 0.0, True          # effectively straight: nothing to flatten
    pivot = len(k_hour) - 1
    left = max(range(0, pivot + 1), key=lambda i: magnitudes[i])
    right = max(range(pivot, len(magnitudes)), key=lambda i: magnitudes[i])
    peak = max(range(len(magnitudes)), key=lambda i: magnitudes[i])
    at_pivot = abs(peak - pivot) <= max(2, len(magnitudes) // 50)
    if right <= left:
        return 0.0, at_pivot
    trough = min(magnitudes[left:right + 1])
    shallower = min(magnitudes[left], magnitudes[right])
    if shallower < 1e-12:
        return 0.0, at_pivot
    return 1.0 - trough / shallower, at_pivot


def measure(hour: int, minute: int, rule, face: G.Face = G.Face(),
            stems: G.Stems = G.DEFAULT_STEMS,
            samples: int = CURVE_SAMPLES) -> Position:
    cl = G.build_centerline(hour, minute, rule, face, stems)

    hpx, hpy, hvx, hvy, hwx, hwy = _sample_half(
        cl.hour_connector, cl.pivot, cl.hour_derivative, cl.guide_derivative,
        cl.hour_span, samples)
    mpx, mpy, mvx, mvy, mwx, mwy = _sample_half(
        cl.pivot, cl.minute_connector, cl.guide_derivative,
        cl.minute_derivative, cl.minute_span, samples)

    k_hour = _curvature_list(hvx, hvy, hwx, hwy)
    k_minute = _curvature_list(mvx, mvy, mwx, mwy)
    all_k = k_hour + k_minute
    peak = max(abs(v) for v in all_k) or 1e-12

    threshold = 0.02 * peak
    significant = [v for v in all_k if abs(v) > threshold]
    sign_changes = sum(
        1 for i in range(1, len(significant))
        if (significant[i] > 0) != (significant[i - 1] > 0)
    )

    # Geometric swerve: excursion to the wrong side of the chord A->B.
    ax, ay = cl.hour_connector
    chord_x = cl.minute_connector[0] - ax
    chord_y = cl.minute_connector[1] - ay
    chord_length = (chord_x * chord_x + chord_y * chord_y) ** 0.5
    if chord_length > 1e-6:
        offsets = [
            (chord_x * (py - ay) - chord_y * (px - ax)) / chord_length
            for px, py in zip(hpx + mpx, hpy + mpy)
        ]
        swerve = min(abs(max(offsets)), abs(min(offsets)))
        bow = max(abs(max(offsets)), abs(min(offsets)))
    else:
        swerve = 0.0
        bow = 0.0

    centre = cl.context.center
    a, b, p = cl.hour_connector, cl.minute_connector, cl.pivot
    s1 = G.cross(G.sub(b, a), G.sub(p, a))
    s2 = G.cross(G.sub(centre, b), G.sub(p, b))
    s3 = G.cross(G.sub(a, centre), G.sub(p, centre))
    inside = (min(s1, s2, s3) >= -1e-6) or (max(s1, s2, s3) <= 1e-6)

    dip, at_pivot = _curvature_dip(k_hour, k_minute, bow)
    ceiling = cl.context.arc_apex_ceiling
    depth = G.norm(G.sub(cl.pivot, centre))

    return Position(
        delta=G.separation_degrees(hour, minute),
        swerve=swerve,
        sign_changes=sign_changes,
        joint_jump=abs(k_hour[-1] - k_minute[0]) / peak,
        min_radius=1.0 / peak,
        depth=G.norm(G.sub(cl.pivot, centre)),
        inside_triangle=inside,
        solver_ok=cl.solver_ok,
        turn_hour=_turn_from(hvx, hvy),
        turn_minute=_turn_from(mvx, mvy),
        peak_k_hour=max(abs(v) for v in k_hour),
        peak_k_minute=max(abs(v) for v in k_minute),
        curvature_dip=dip,
        peak_at_pivot=at_pivot,
        headroom=((depth / ceiling)
                  if ceiling > HEADROOM_MIN_CEILING_PX else 0.0),
    )


@dataclass
class Summary:
    candidate: G.Candidate
    stems: G.Stems
    max_swerve: float
    swerve_failures: int
    sign_change_positions: int
    max_joint_jump: float
    min_radius: float
    min_radius_open: float
    max_depth: float
    peak_delta: float
    outside_triangle: int
    solver_fallbacks: int
    mean_turn_share: float
    worst_turn_share: float
    mean_k_ratio: float
    worst_dip: float
    dip_failures: int
    max_headroom: float
    off_pivot_peaks: int

    @property
    def passes(self) -> bool:
        return (
            self.max_swerve < SWERVE_GATE_PX
            and self.outside_triangle == 0
            and self.solver_fallbacks == 0
            and self.dip_failures == 0
        )


def summarise(candidate: G.Candidate, face: G.Face, stems: G.Stems) -> Summary:
    positions = [measure(h, m, candidate.rule, face, stems) for h, m in G.ALL_TIMES]
    open_positions = [p for p in positions if p.delta > OVERLAP_GUARD_DEG]
    wide_positions = [p for p in positions if p.delta >= 90.0]
    deepest = max(positions, key=lambda p: p.depth)

    ratios = []
    for p in open_positions:
        if p.peak_k_minute > 1e-9:
            ratios.append(p.peak_k_hour / p.peak_k_minute)

    shares = [p.turn_share for p in open_positions] or [0.5]
    return Summary(
        candidate=candidate,
        stems=stems,
        max_swerve=max(p.swerve for p in positions),
        swerve_failures=sum(1 for p in positions if p.swerve >= SWERVE_GATE_PX),
        sign_change_positions=sum(1 for p in positions if p.sign_changes > 0),
        max_joint_jump=max(p.joint_jump for p in positions),
        min_radius=min((p.min_radius for p in open_positions), default=0.0),
        min_radius_open=min((p.min_radius for p in wide_positions),
                            default=0.0),
        max_depth=deepest.depth,
        peak_delta=deepest.delta,
        outside_triangle=sum(1 for p in positions if not p.inside_triangle),
        solver_fallbacks=sum(1 for p in positions if not p.solver_ok),
        mean_turn_share=sum(shares) / len(shares),
        worst_turn_share=max(shares, key=lambda v: abs(v - 0.5)),
        mean_k_ratio=(sum(ratios) / len(ratios)) if ratios else 1.0,
        worst_dip=max(p.curvature_dip for p in positions),
        dip_failures=sum(1 for p in positions if not p.unimodal),
        max_headroom=max(p.headroom for p in positions),
        off_pivot_peaks=sum(1 for p in open_positions if not p.peak_at_pivot),
    )


# ---------------------------------------------------------------------------
# Panel drawing
# ---------------------------------------------------------------------------

PANEL_SCALE = 0.92


def draw_panel(
    cv: S.Canvas, ox: float, oy: float, face: G.Face, stems: G.Stems,
    hour: int, minute: int, main: G.Candidate,
    underlay: G.Candidate | None = None,
    overlays: tuple[tuple[G.Candidate, str], ...] = (),
    heading: str | None = None,
    footer: str | None = None,
    show_triangle: bool = True,
    scale: float | None = None,
    line_width: float = 1.4,
) -> tuple[float, float]:
    sc = PANEL_SCALE if scale is None else scale
    pw, ph = face.width * sc, face.height * sc

    def T(point):
        return (ox + point[0] * sc, oy + point[1] * sc)

    cv.rect(ox, oy, pw, ph, fill=S.PANEL, stroke="#242a31", stroke_width=0.8, rx=3)

    reference = G.build_centerline(hour, minute, main.rule, face, stems)
    centre = T(reference.context.center)

    # centre crosshair
    cv.line(centre[0] - 4, centre[1], centre[0] + 4, centre[1],
            stroke=S.DIM, stroke_width=0.5, opacity=0.7)
    cv.line(centre[0], centre[1] - 4, centre[0], centre[1] + 4,
            stroke=S.DIM, stroke_width=0.5, opacity=0.7)

    if show_triangle:
        cv.polyline(
            [T(reference.hour_connector), T(reference.minute_connector),
             T(reference.context.center)],
            stroke=S.GUIDE, stroke_width=0.5, opacity=0.85, dash="2 2", close=True,
        )

    if underlay is not None:
        under = G.build_centerline(hour, minute, underlay.rule, face, stems)
        cv.polyline([T(p) for p in under.points],
                    stroke=S.REFERENCE, stroke_width=1.5, opacity=0.9)
        cv.circle(*T(under.pivot), 1.8, fill=S.REFERENCE, opacity=0.9)

    if overlays:
        for candidate, colour in overlays:
            cl = G.build_centerline(hour, minute, candidate.rule, face, stems)
            cv.polyline([T(p) for p in cl.points], stroke=colour,
                        stroke_width=1.3, opacity=0.95)
            cv.circle(*T(cl.pivot), 1.6, fill=colour)
    else:
        cv.polyline([T(p) for p in reference.points], stroke=S.INK,
                    stroke_width=line_width)
        cv.circle(*T(reference.pivot), 2.1, fill=S.PIVOT)

    for point in (reference.hour_tip, reference.minute_tip):
        cv.circle(*T(point), 1.4, fill=S.TIP, opacity=0.8)

    if heading:
        cv.text(ox + 5, oy + 12, heading, size=9, fill=S.LABEL)
    if footer:
        cv.text(ox + 5, oy + ph - 6, footer, size=8, fill=S.DIM)

    return pw, ph


# ---------------------------------------------------------------------------
# Sheets
# ---------------------------------------------------------------------------

def sheet_compare(face, stems, times, out_path) -> None:
    rows = [G.CANDIDATES_BY_KEY[key] for key in SHAPE_ROWS]
    reference = G.CANDIDATES_BY_KEY["c0-current"]

    pw, ph = face.width * PANEL_SCALE, face.height * PANEL_SCALE
    gap, left, top = 8, 190, 128
    width = left + len(times) * (pw + gap) + 16
    height = top + len(rows) * (ph + gap) + 30
    cv = S.Canvas(width, height)

    cv.text(24, 34, "Connector pivot candidates - centerline only",
            size=17, fill=S.LABEL, weight="600")
    cv.text(24, 54,
            f"{face.name} {face.width}x{face.height}  |  stems: {stems.describe()}",
            size=10, fill=S.DIM)
    cv.text(24, 70, "white = candidate     amber = C0, the current construction "
                    "(reference underlay)     dashed = tangent triangle A-B-centre",
            size=10, fill=S.DIM)

    for column, (hour, minute) in enumerate(times):
        x = left + column * (pw + gap)
        delta = G.separation_degrees(hour, minute)
        cv.text(x + pw / 2, top - 20, label_time(hour, minute), size=12,
                fill=S.LABEL, anchor="middle", weight="600")
        cv.text(x + pw / 2, top - 7, f"delta = {delta:.1f} deg", size=9,
                fill=S.DIM, anchor="middle")

    for row, candidate in enumerate(rows):
        y = top + row * (ph + gap)
        cv.text(24, y + 20, candidate.label, size=11, fill=S.LABEL, weight="600")
        cv.text(24, y + 34, candidate.formula, size=8, fill=S.DIM)
        if candidate.role != "contender":
            cv.text(24, y + 48, f"[{candidate.role}]", size=8, fill=S.REFERENCE)
        for column, (hour, minute) in enumerate(times):
            x = left + column * (pw + gap)
            cl = G.build_centerline(hour, minute, candidate.rule, face, stems)
            depth = G.norm(G.sub(cl.pivot, cl.context.center))
            draw_panel(cv, x, y, face, stems, hour, minute, candidate,
                       underlay=reference, footer=f"s = {depth:.1f} px")

    cv.write(out_path)


ZOOM_HALF_SPAN = 34.0      # px of face shown either side of the centre
ZOOM_BOX = 176.0


def draw_zoom_panel(cv, ox, oy, face, stems, hour, minute, main,
                    underlay=None, footer=None, index=0,
                    overlays=(), dots=True) -> None:
    """The central region at high magnification -- where the pivot decision is
    actually visible.  Sample dots are drawn so that the degenerate
    self-overlapping path near hand overlap reads as doubled rather than single.
    """
    zoom = ZOOM_BOX / (2.0 * ZOOM_HALF_SPAN)
    cv.rect(ox, oy, ZOOM_BOX, ZOOM_BOX, fill=S.PANEL, stroke="#242a31",
            stroke_width=0.8, rx=3)
    cl = G.build_centerline(hour, minute, main.rule, face, stems)
    centre = cl.context.center
    cx, cy = ox + ZOOM_BOX / 2, oy + ZOOM_BOX / 2

    def T(point):
        return (cx + (point[0] - centre[0]) * zoom,
                cy + (point[1] - centre[1]) * zoom)

    cv.push_clip(ox, oy, ZOOM_BOX, ZOOM_BOX, f"zoom{index}")
    cv.line(cx - 7, cy, cx + 7, cy, stroke=S.DIM, stroke_width=0.7, opacity=0.9)
    cv.line(cx, cy - 7, cx, cy + 7, stroke=S.DIM, stroke_width=0.7, opacity=0.9)
    cv.polyline([T(cl.hour_connector), T(cl.minute_connector), T(centre)],
                stroke=S.GUIDE, stroke_width=0.7, opacity=0.9, dash="3 3",
                close=True)

    if underlay is not None:
        under = G.build_centerline(hour, minute, underlay.rule, face, stems)
        cv.polyline([T(p) for p in under.points], stroke=S.REFERENCE,
                    stroke_width=1.6, opacity=0.9)
        cv.circle(*T(under.pivot), 2.4, fill=S.REFERENCE, opacity=0.9)

    if overlays:
        for candidate, colour in overlays:
            other = G.build_centerline(hour, minute, candidate.rule, face, stems)
            cv.polyline([T(p) for p in other.points], stroke=colour,
                        stroke_width=1.4, opacity=0.95)
            cv.circle(*T(other.pivot), 2.2, fill=colour)
    else:
        cv.polyline([T(p) for p in cl.points], stroke=S.INK, stroke_width=1.5)
        if dots:
            for point in cl.points:
                cv.circle(*T(point), 0.9, fill=S.INK, opacity=0.55)
        cv.circle(*T(cl.pivot), 2.8, fill=S.PIVOT)
    cv.pop()

    if footer:
        cv.text(ox + 5, oy + ZOOM_BOX - 6, footer, size=8, fill=S.DIM)


def sheet_compare_zoom(face, stems, times, out_path) -> None:
    rows = [G.CANDIDATES_BY_KEY[key] for key in SHAPE_ROWS]
    reference = G.CANDIDATES_BY_KEY["c0-current"]
    gap, left, top = 8, 190, 128
    cv = S.Canvas(left + len(times) * (ZOOM_BOX + gap) + 16,
                  top + len(rows) * (ZOOM_BOX + gap) + 30)

    cv.text(24, 34, "Connector pivot candidates - centre region at "
            f"{ZOOM_BOX / (2 * ZOOM_HALF_SPAN):.1f}x", size=17, fill=S.LABEL,
            weight="600")
    cv.text(24, 54, f"{face.name}, +/-{ZOOM_HALF_SPAN:.0f} px around the watch "
            f"centre  |  stems: {stems.describe()}", size=10, fill=S.DIM)
    cv.text(24, 72, "white = candidate (dots are the 49 samples the device "
            "actually draws)     amber = C0 current     blue = pivot",
            size=10, fill=S.DIM)
    cv.text(24, 88, "Where the white line looks single but carries doubled "
            "dots, the path is folded back on itself - the accepted degenerate "
            "overlap.", size=10, fill=S.DIM)

    for column, (hour, minute) in enumerate(times):
        x = left + column * (ZOOM_BOX + gap)
        delta = G.separation_degrees(hour, minute)
        cv.text(x + ZOOM_BOX / 2, top - 20, label_time(hour, minute), size=12,
                fill=S.LABEL, anchor="middle", weight="600")
        cv.text(x + ZOOM_BOX / 2, top - 7, f"delta = {delta:.1f} deg", size=9,
                fill=S.DIM, anchor="middle")

    for row, candidate in enumerate(rows):
        y = top + row * (ZOOM_BOX + gap)
        cv.text(24, y + 20, candidate.label, size=11, fill=S.LABEL, weight="600")
        cv.text(24, y + 34, candidate.formula, size=8, fill=S.DIM)
        if candidate.role != "contender":
            cv.text(24, y + 48, f"[{candidate.role}]", size=8, fill=S.REFERENCE)
        for column, (hour, minute) in enumerate(times):
            x = left + column * (ZOOM_BOX + gap)
            cl = G.build_centerline(hour, minute, candidate.rule, face, stems)
            depth = G.norm(G.sub(cl.pivot, cl.context.center))
            draw_zoom_panel(cv, x, y, face, stems, hour, minute, candidate,
                            underlay=reference, footer=f"s = {depth:.1f} px",
                            index=row * len(times) + column)
    cv.write(out_path)


def sheet_tilt(face, stems, times, out_path) -> None:
    """The beta bracket, zoomed -- at face scale the variants overlap."""
    overlays = tuple(
        (candidate, S.RAMP[i % len(S.RAMP)])
        for i, candidate in enumerate(G.ROUND2_TILT)
    )
    gap, left, top = 8, 24, 116
    cv = S.Canvas(left + len(times) * (ZOOM_BOX + gap) + 16, top + ZOOM_BOX + 40)

    cv.text(24, 34, "Tilt bracket at D1's depth, centre region at "
            f"{ZOOM_BOX / (2 * ZOOM_HALF_SPAN):.1f}x", size=17, fill=S.LABEL,
            weight="600")
    cv.text(24, 54, "D1 depth throughout; only beta varies. Lower beta leans "
            "the pull toward the hour stem, higher toward the minute. All five "
            "stay unimodal, so tilt is free.", size=10, fill=S.DIM)

    bisector = G.beta_bisector(
        G.build_centerline(3, 0, G.CANDIDATES_BY_KEY["d1-arc-sin"].rule,
                           face, stems).context
    )
    for i, (candidate, colour) in enumerate(overlays):
        x = 24 + i * 78
        cv.line(x, 76, x + 16, 76, stroke=colour, stroke_width=2.4)
        cv.text(x + 21, 79, candidate.label.replace("beta = ", "b="), size=9,
                fill=S.LABEL)
    cv.text(24 + len(overlays) * 78 + 8, 79,
            f"(C1, the bisector member, sits at b={bisector:.3f})", size=9,
            fill=S.REFERENCE)

    for column, (hour, minute) in enumerate(times):
        x = left + column * (ZOOM_BOX + gap)
        delta = G.separation_degrees(hour, minute)
        cv.text(x + ZOOM_BOX / 2, top - 8,
                f"{label_time(hour, minute)}   delta = {delta:.1f}", size=10,
                fill=S.LABEL, anchor="middle")
        draw_zoom_panel(cv, x, top, face, stems, hour, minute, G.ROUND2_TILT[0],
                        overlays=overlays, index=900 + column)
    cv.write(out_path)


def sheet_stems(face, times, out_path,
                candidate_key: str = "d1-arc-sin") -> None:
    candidate = G.CANDIDATES_BY_KEY[candidate_key]
    reference = G.CANDIDATES_BY_KEY["c0-current"]
    hour, minute = (3, 0)

    pw, ph = face.width * PANEL_SCALE, face.height * PANEL_SCALE
    gap, left, top = 8, 24, 104
    columns = G.STEM_CONFIGS
    cv = S.Canvas(left + len(columns) * (pw + gap) + 16, top + ph + 56)

    cv.text(24, 34, f"Stem-geometry robustness - {candidate.label} at "
            f"{label_time(hour, minute)}", size=17, fill=S.LABEL, weight="600")
    cv.text(24, 54, "The pivot rule is homogeneous of degree 1 in the stem radii "
                    "and symmetric in them, so changing the stems should rescale "
                    "the pivot, not distort it.", size=10, fill=S.DIM)
    cv.text(24, 70, "white = candidate under that stem config     "
                    "amber = C0 under the same stem config", size=10, fill=S.DIM)

    for column, stems in enumerate(columns):
        x = left + column * (pw + gap)
        cv.text(x + pw / 2, top - 8, stems.name, size=11, fill=S.LABEL,
                anchor="middle", weight="600")
        cl = G.build_centerline(hour, minute, candidate.rule, face, stems)
        depth = G.norm(G.sub(cl.pivot, cl.context.center))
        harmonic = cl.context.harmonic_inner
        draw_panel(cv, x, top, face, stems, hour, minute, candidate,
                   underlay=reference,
                   footer=f"s={depth:.1f}  s/H={depth / harmonic:.3f}")
        cv.text(x + pw / 2, top + ph + 16,
                f"r_h={stems.hour_inner:.2f}R  r_m={stems.minute_inner:.2f}R",
                size=8, fill=S.DIM, anchor="middle")
        cv.text(x + pw / 2, top + ph + 28, f"H={harmonic:.1f} px",
                size=8, fill=S.DIM, anchor="middle")
    cv.write(out_path)


def _context_for_delta(delta_deg, face, stems):
    radius = face.max_radius
    angle = math.radians(delta_deg)
    hour_radial = (0.0, -1.0)
    minute_radial = (math.sin(angle), -math.cos(angle))
    centre = face.center
    hour_inner = radius * stems.hour_inner
    minute_inner = radius * stems.minute_inner
    return G.PivotContext(
        center=centre,
        max_radius=radius,
        hour_radial=hour_radial,
        minute_radial=minute_radial,
        hour_point=G.add(centre, G.scale(hour_radial, hour_inner)),
        minute_point=G.add(centre, G.scale(minute_radial, minute_inner)),
        hour_inner=hour_inner,
        minute_inner=minute_inner,
        hour_length=radius * stems.hour_length,
        minute_length=radius * stems.minute_length,
        radial_dot=G.clamp(G.dot(hour_radial, minute_radial), -1.0, 1.0),
    )


def sheet_profiles(face, stems, out_path) -> None:
    shown = [c for c in ALL_CANDIDATES
             if c.key not in ("c5-centre", "c1-openness-070",
                              "dc-arc-ceiling", "c4-openness-p20")]
    samples = [d * 0.5 for d in range(361)]
    series = []
    for candidate in shown:
        values = []
        for delta in samples:
            ctx = _context_for_delta(delta, face, stems)
            values.append(G.norm(G.sub(candidate.rule(ctx), ctx.center)))
        series.append((candidate, values))

    peak = max(max(values) for _, values in series) * 1.08
    plot_w, plot_h = 720, 380
    left, top = 78, 108
    cv = S.Canvas(left + plot_w + 350, top + plot_h + 76)

    cv.text(24, 34, "Pivot depth s(delta)", size=17, fill=S.LABEL, weight="600")
    cv.text(24, 54, f"{face.name}, R = {face.max_radius:.0f} px, "
            f"stems: {stems.describe()}", size=10, fill=S.DIM)
    cv.text(24, 70, "Every candidate must vanish at delta=0 (centre-pinned "
                    "overlap). Vanishing at delta=180 is what keeps the "
                    "opposition line straight.", size=10, fill=S.DIM)

    def X(delta):
        return left + delta / 180.0 * plot_w

    def Y(value):
        return top + plot_h - value / peak * plot_h

    cv.rect(left, top, plot_w, plot_h, fill="#0d0f12", stroke="#242a31",
            stroke_width=0.8)
    for delta in range(0, 181, 15):
        cv.line(X(delta), top, X(delta), top + plot_h, stroke=S.GUIDE,
                stroke_width=0.4, opacity=0.5)
        cv.text(X(delta), top + plot_h + 16, str(delta), size=9, fill=S.DIM,
                anchor="middle")
    for value in range(0, int(peak) + 1, 5):
        cv.line(left, Y(value), left + plot_w, Y(value), stroke=S.GUIDE,
                stroke_width=0.4, opacity=0.5)
        cv.text(left - 8, Y(value) + 3, str(value), size=9, fill=S.DIM,
                anchor="end")
    cv.text(left + plot_w / 2, top + plot_h + 38,
            "angle between the hands, delta (deg)", size=10, fill=S.LABEL,
            anchor="middle")
    cv.text(left - 56, top - 12, "s (px)", size=10, fill=S.LABEL)

    palette = ("#ff8a3d", "#ffffff", "#4fc3f7", "#f4d35e", "#a78bfa",
               "#4ade80", "#f472b6", "#facc15", "#38bdf8", "#fb7185")
    for i, (candidate, values) in enumerate(series):
        colour = S.REFERENCE if candidate.key == "c0-current" else palette[
            (i + 1) % len(palette)]
        width = 2.4 if candidate.key in ("c0-current", "c1-openness") else 1.4
        dash = "4 3" if candidate.role == "illustration" else None
        cv.polyline([(X(d), Y(v)) for d, v in zip(samples, values)],
                    stroke=colour, stroke_width=width, dash=dash)
        y = top + 14 + i * 17
        cv.line(left + plot_w + 16, y - 3, left + plot_w + 34, y - 3,
                stroke=colour, stroke_width=width, dash=dash)
        best = max(range(len(values)), key=lambda k: values[k])
        cv.text(left + plot_w + 40, y,
                f"{candidate.label}  ({values[best]:.1f} @ {samples[best]:.0f})",
                size=9, fill=S.LABEL)
    cv.write(out_path)


def sheet_locus(face, stems, out_path) -> None:
    shown = [c for c in ALL_CANDIDATES
             if c.role in ("reference", "contender")]
    box = 168
    zoom = 2.6
    gap, left, top, per_row = 14, 24, 104, 5
    rows = (len(shown) + per_row - 1) // per_row
    cv = S.Canvas(left + per_row * (box + gap) + 16,
                  top + rows * (box + gap + 30) + 24)

    cv.text(24, 34, "Pivot locus over a full 12 hours (all 720 minutes)",
            size=17, fill=S.LABEL, weight="600")
    cv.text(24, 54, f"Zoomed {zoom:.1f}x on the watch centre. A single smooth "
            "closed sweep reads as effortless; cusps and stalls do not.",
            size=10, fill=S.DIM)
    cv.text(24, 70, "The 11 lobes are the 11 hand overlaps per 12 hours - the "
            "locus returns to the centre at each one.", size=10, fill=S.DIM)

    for index, candidate in enumerate(shown):
        column, row = index % per_row, index // per_row
        ox = left + column * (box + gap)
        oy = top + row * (box + gap + 30)
        cv.rect(ox, oy, box, box, fill=S.PANEL, stroke="#242a31",
                stroke_width=0.8, rx=3)
        cx, cy = ox + box / 2, oy + box / 2
        cv.line(cx - 6, cy, cx + 6, cy, stroke=S.DIM, stroke_width=0.5)
        cv.line(cx, cy - 6, cx, cy + 6, stroke=S.DIM, stroke_width=0.5)

        points = []
        for hour, minute in G.ALL_TIMES:
            cl = G.build_centerline(hour, minute, candidate.rule, face, stems)
            offset = G.sub(cl.pivot, cl.context.center)
            points.append((cx + offset[0] * zoom, cy + offset[1] * zoom))
        points.append(points[0])
        colour = S.REFERENCE if candidate.key == "c0-current" else S.INK
        cv.polyline(points, stroke=colour, stroke_width=0.9, opacity=0.95)

        depth = max(G.norm(G.sub(p, (cx, cy))) for p in points) / zoom
        cv.text(ox + box / 2, oy + box + 16, candidate.label, size=10,
                fill=S.LABEL, anchor="middle", weight="600")
        cv.text(ox + box / 2, oy + box + 28, f"reach {depth:.1f} px", size=8,
                fill=S.DIM, anchor="middle")
    cv.write(out_path)



# ---------------------------------------------------------------------------
# Round 2: curvature profiles and the unimodality ceiling
# ---------------------------------------------------------------------------

ROUND2_ROWS = ("d1-arc-sin", "d2-arc-openness", "d3-arc-p075", "c3-chord-035",
               "c3o-chord-openness", "c0-current", "dc-arc-ceiling",
               "c1-openness")

#: The same roster with C0 removed -- it is the reference underlay in the shape
#: sheets rather than a row of its own.
SHAPE_ROWS = tuple(key for key in ROUND2_ROWS if key != "c0-current")

PROFILE_W, PROFILE_H = 176.0, 118.0


def curvature_profile(cl, samples: int = 200):
    """|k| against normalized arc length across the connector, and the arc
    position of the pivot."""
    a = _sample_half(cl.hour_connector, cl.pivot, cl.hour_derivative,
                     cl.guide_derivative, cl.hour_span, samples)
    b = _sample_half(cl.pivot, cl.minute_connector, cl.guide_derivative,
                     cl.minute_derivative, cl.minute_span, samples)
    magnitudes = ([abs(v) for v in _curvature_list(a[2], a[3], a[4], a[5])]
                  + [abs(v) for v in _curvature_list(b[2], b[3], b[4], b[5])][1:])
    # arc length, so the horizontal axis is geometric rather than parametric
    xs = [0.0]
    px = a[0] + b[0][1:]
    py = a[1] + b[1][1:]
    for i in range(1, len(px)):
        xs.append(xs[-1] + math.hypot(px[i] - px[i - 1], py[i] - py[i - 1]))
    total = xs[-1] or 1.0
    pivot_at = xs[samples] / total
    return [x / total for x in xs], magnitudes, pivot_at


def draw_profile_cell(cv, ox, oy, face, stems, hour, minute, candidate) -> None:
    cl = G.build_centerline(hour, minute, candidate.rule, face, stems)
    xs, ks, pivot_at = curvature_profile(cl)
    position = measure(hour, minute, candidate.rule, face, stems)

    cv.rect(ox, oy, PROFILE_W, PROFILE_H, fill=S.PANEL, stroke="#242a31",
            stroke_width=0.8, rx=3)
    inset_l, inset_r, inset_t, inset_b = 6.0, 6.0, 20.0, 16.0
    plot_w = PROFILE_W - inset_l - inset_r
    plot_h = PROFILE_H - inset_t - inset_b
    peak_k = max(ks)

    # Below this the line is straighter than the display can meaningfully show
    # (radius > 10x the face). Autoscaling such a cell turns floating-point
    # noise into a dramatic and entirely fictional shape, so say "straight".
    if peak_k < STRAIGHT_K:
        cv.rect(ox, oy, PROFILE_W, PROFILE_H, fill=S.PANEL, stroke="#242a31",
                stroke_width=0.8, rx=3)
        mid = oy + inset_t + plot_h * 0.5
        cv.line(ox + inset_l, mid, ox + inset_l + plot_w, mid, stroke=S.DIM,
                stroke_width=1.2, opacity=0.85)
        cv.text(ox + 5, oy + 13, "straight", size=8, fill=S.LABEL, weight="600")
        cv.text(ox + PROFILE_W - 5, oy + 13, f"head {position.headroom:.2f}",
                size=8, anchor="end", fill=S.DIM)
        cv.text(ox + 5, oy + PROFILE_H - 5,
                f"s={position.depth:.1f}  peak |k| < {STRAIGHT_K:g}", size=7,
                fill=S.DIM)
        return
    top = peak_k

    def X(value):
        return ox + inset_l + value * plot_w

    def Y(value):
        return oy + inset_t + plot_h - (value / top) * plot_h

    # pivot rule
    cv.line(X(pivot_at), oy + inset_t - 3, X(pivot_at), oy + inset_t + plot_h,
            stroke=S.PIVOT, stroke_width=0.8, opacity=0.75, dash="2 2")
    cv.line(ox + inset_l, Y(0), ox + inset_l + plot_w, Y(0), stroke=S.GUIDE,
            stroke_width=0.5, opacity=0.8)

    colour = S.REFERENCE if candidate.role != "contender" else S.INK
    cv.polyline([(X(x), Y(k)) for x, k in zip(xs, ks)], stroke=colour,
                stroke_width=1.4)

    verdict = "unimodal" if position.unimodal else f"W {position.curvature_dip:.0%}"
    cv.text(ox + 5, oy + 13, verdict, size=8,
            fill=S.LABEL if position.unimodal else "#f95d6a", weight="600")
    cv.text(ox + PROFILE_W - 5, oy + 13,
            f"head {position.headroom:.2f}", size=8, anchor="end",
            fill=S.DIM if position.headroom <= 1.0 else "#f95d6a")
    cv.text(ox + 5, oy + PROFILE_H - 5,
            f"s={position.depth:.1f}  peak |k|={top:.3f}", size=7, fill=S.DIM)


def sheet_curvature(face, stems, times, out_path) -> None:
    rows = [G.CANDIDATES_BY_KEY[key] for key in ROUND2_ROWS]
    gap, left, top = 8, 196, 116
    cv = S.Canvas(left + len(times) * (PROFILE_W + gap) + 16,
                  top + len(rows) * (PROFILE_H + gap) + 30)

    cv.text(24, 34, "Curvature along the connector", size=17, fill=S.LABEL,
            weight="600")
    cv.text(24, 54, "|k| against normalized arc length. Blue rule = the pivot. "
            "The requirement is one peak at the pivot, not a dip between two.",
            size=10, fill=S.DIM)
    cv.text(24, 72, "A 'W' here is the curve flattening around the pivot. "
            "'head' is s / arc-apex ceiling -- above 1.0 predicts the dip.",
            size=10, fill=S.DIM)
    cv.text(24, 90, f"{face.name}  |  stems: {stems.describe()}", size=10,
            fill=S.DIM)

    for column, (hour, minute) in enumerate(times):
        x = left + column * (PROFILE_W + gap)
        cv.text(x + PROFILE_W / 2, top - 8,
                f"{label_time(hour, minute)}   delta = "
                f"{G.separation_degrees(hour, minute):.1f}", size=10,
                fill=S.LABEL, anchor="middle")

    for row, candidate in enumerate(rows):
        y = top + row * (PROFILE_H + gap)
        cv.text(24, y + 18, candidate.label, size=11, fill=S.LABEL, weight="600")
        cv.text(24, y + 32, candidate.formula, size=8, fill=S.DIM)
        if candidate.role != "contender":
            cv.text(24, y + 46, f"[{candidate.role}]", size=8, fill=S.REFERENCE)
        for column, (hour, minute) in enumerate(times):
            draw_profile_cell(cv, left + column * (PROFILE_W + gap), y, face,
                              stems, hour, minute, candidate)
    cv.write(out_path)


# -- the empirical unimodality ceiling ------------------------------------

_TIME_BY_DELTA = sorted((G.separation_degrees(h, m), h, m)
                        for h in range(12) for m in range(60))


def time_nearest_delta(delta: float) -> tuple[int, int]:
    _, hour, minute = min(_TIME_BY_DELTA, key=lambda row: abs(row[0] - delta))
    return hour, minute


def unimodality_limit(delta: float, face: G.Face, stems: G.Stems,
                      coarse: int = 48, iterations: int = 22) -> float:
    """Smallest pivot depth on the bisector at which |k| starts to flatten.

    Recomputes the constraint from the actual solver rather than from idealized
    circle geometry, so the closed form can be checked rather than trusted.

    The search is bounded by the chord ceiling -- beyond it the pivot leaves the
    tangent triangle and the shape is no longer the thing being measured. It
    coarse-scans upward for the *first* onset before bisecting, because
    flattening is not monotone in depth: past the triangle the profile changes
    character and the dip measure stops detecting it.
    """
    hour, minute = time_nearest_delta(delta)
    top = _context_for_delta(delta, face, stems).chord_ceiling
    if top < 1e-3:
        return 0.0

    def flattens(depth: float) -> bool:
        rule = G.along_bisector(lambda ctx, _length, d=depth: d)
        return not measure(hour, minute, rule, face, stems, samples=64).unimodal

    step = top / coarse
    low = 0.0
    found = None
    for i in range(1, coarse + 1):
        probe = i * step
        if flattens(probe):
            found = probe
            break
        low = probe
    if found is None:
        return top

    high = found
    for _ in range(iterations):
        middle = 0.5 * (low + high)
        if flattens(middle):
            high = middle
        else:
            low = middle
    return 0.5 * (low + high)


def ceiling_table(face, stems, step: float = 5.0) -> list[tuple[float, float]]:
    deltas = [step * i for i in range(1, int(180.0 / step))]
    return [(d, unimodality_limit(d, face, stems)) for d in deltas]


def sheet_ceiling(face, stems, out_path, cache_path=None) -> None:
    empirical = ceiling_table(face, stems)
    if cache_path:
        import json
        with open(cache_path, "w", encoding="utf-8") as handle:
            json.dump({"face": face.name, "stems": stems.name,
                       "limit": empirical}, handle, indent=1)

    samples = [d * 1.0 for d in range(0, 181)]
    shown = [G.CANDIDATES_BY_KEY[key] for key in
             ("d1-arc-sin", "d2-arc-openness", "c3-chord-035",
              "c3o-chord-openness", "c0-current", "c1-openness")]
    series = []
    for candidate in shown:
        values = []
        for delta in samples:
            ctx = _context_for_delta(delta, face, stems)
            values.append(G.norm(G.sub(candidate.rule(ctx), ctx.center)))
        series.append((candidate.label, values, candidate.role))

    arc = [_context_for_delta(d, face, stems).arc_apex_ceiling for d in samples]
    chord = [_context_for_delta(d, face, stems).chord_ceiling for d in samples]

    peak = max(max(chord), max(v for _, vs, _ in series for v in vs)) * 1.06
    plot_w, plot_h, left, top = 720, 400, 78, 122
    cv = S.Canvas(left + plot_w + 330, top + plot_h + 76)

    cv.text(24, 34, "Where the curvature starts to flatten", size=17,
            fill=S.LABEL, weight="600")
    cv.text(24, 54, "Grey band = pivot depths that keep |k| unimodal, bisected "
            "from the solver at 5 deg steps. Cross into the band above it and "
            "the curve flattens at the pivot.", size=10, fill=S.DIM)
    cv.text(24, 72, "The round-1 chord ceiling is ~1.8x the real limit where it "
            "matters, which is why C1 flattened. min(r) tan(45-d/4) tracks it.",
            size=10, fill=S.DIM)
    cv.text(24, 90, f"{face.name}, R = {face.max_radius:.0f} px  |  stems: "
            f"{stems.describe()}", size=10, fill=S.DIM)

    def X(delta):
        return left + delta / 180.0 * plot_w

    def Y(value):
        return top + plot_h - value / peak * plot_h

    cv.rect(left, top, plot_w, plot_h, fill="#0d0f12", stroke="#242a31",
            stroke_width=0.8)
    for delta in range(0, 181, 15):
        cv.line(X(delta), top, X(delta), top + plot_h, stroke=S.GUIDE,
                stroke_width=0.4, opacity=0.45)
        cv.text(X(delta), top + plot_h + 16, str(delta), size=9, fill=S.DIM,
                anchor="middle")
    for value in range(0, int(peak) + 1, 5):
        cv.line(left, Y(value), left + plot_w, Y(value), stroke=S.GUIDE,
                stroke_width=0.4, opacity=0.45)
        cv.text(left - 8, Y(value) + 3, str(value), size=9, fill=S.DIM,
                anchor="end")
    cv.text(left + plot_w / 2, top + plot_h + 38,
            "angle between the hands, delta (deg)", size=10, fill=S.LABEL,
            anchor="middle")
    cv.text(left - 60, top - 12, "s (px)", size=10, fill=S.LABEL)

    # the unimodal region, as a filled band
    band = ([(X(d), Y(v)) for d, v in empirical]
            + [(X(empirical[-1][0]), Y(0)), (X(empirical[0][0]), Y(0))])
    cv.polyline(band, stroke="none", fill="#2a3340", opacity=0.55, close=True)
    cv.polyline([(X(d), Y(v)) for d, v in empirical], stroke="#8fa3bb",
                stroke_width=1.8)

    cv.polyline([(X(d), Y(v)) for d, v in zip(samples, arc)], stroke="#4ade80",
                stroke_width=2.0, dash="5 3")
    cv.polyline([(X(d), Y(v)) for d, v in zip(samples, chord)],
                stroke="#a78bfa", stroke_width=1.4, dash="2 4")

    legend = [("empirical unimodality limit", "#8fa3bb", 1.8, None),
              ("min(r) tan(45-d/4)  (arc apex)", "#4ade80", 2.0, "5 3"),
              ("H cos(d/2)  (round-1 chord ceiling)", "#a78bfa", 1.4, "2 4")]
    palette = ("#ffffff", "#4fc3f7", "#f4d35e", "#f472b6", "#ff8a3d", "#f95d6a")
    for i, (label, values, role) in enumerate(series):
        colour = palette[i % len(palette)]
        dash = "4 3" if role != "contender" else None
        cv.polyline([(X(d), Y(v)) for d, v in zip(samples, values)],
                    stroke=colour, stroke_width=1.6, dash=dash)
        best = max(range(len(values)), key=lambda k: values[k])
        legend.append((f"{label}  ({values[best]:.1f} @ {samples[best]:.0f})",
                       colour, 1.6, dash))
    for i, (label, colour, width, dash) in enumerate(legend):
        y = top + 16 + i * 18
        cv.line(left + plot_w + 16, y - 3, left + plot_w + 36, y - 3,
                stroke=colour, stroke_width=width, dash=dash)
        cv.text(left + plot_w + 42, y, label, size=9, fill=S.LABEL)
    cv.write(out_path)



# ---------------------------------------------------------------------------
# Round 3: animation over an hour
# ---------------------------------------------------------------------------

ANIM_FPS = 6
ANIM_FRAMES = 60          # one frame per minute of the hour


@dataclass(frozen=True)
class AnimLayout:
    """A grid of panels to animate: rows are stem configurations, columns are
    candidates.  C0 is underlaid in every cell rather than given a column."""

    name: str
    title: str
    subtitle: str
    rows: tuple[G.Stems, ...]
    columns: tuple[str, ...]
    scale: float
    row_label_width: float
    show_row_labels: bool = True


ANIM_LAYOUTS: tuple[AnimLayout, ...] = (
    AnimLayout(
        name="anim-current",
        title="Pivot finalists over one hour",
        subtitle="white = candidate     amber = current construction",
        rows=(G.STEMS_BY_NAME["current"],),
        columns=("d1-arc-sin", "d3-arc-p075", "c3-chord-035"),
        scale=1.30,
        row_label_width=24.0,
        show_row_labels=False,
    ),
    AnimLayout(
        name="anim-stems",
        title="Finalists across stem geometries",
        subtitle="white = candidate     amber = current construction",
        rows=tuple(G.STEMS_BY_NAME[name] for name in
                   ("current", "symmetric", "strong-asym", "short")),
        columns=("d1-arc-sin", "c3-chord-035"),
        scale=0.86,
        row_label_width=132.0,
    ),
)

ANIM_LAYOUTS_BY_NAME = {layout.name: layout for layout in ANIM_LAYOUTS}


def animation_frame(face, layout: AnimLayout, hour: int, minute: int) -> S.Canvas:
    reference = G.CANDIDATES_BY_KEY["c0-current"]
    candidates = [G.CANDIDATES_BY_KEY[key] for key in layout.columns]
    pw = face.width * layout.scale
    ph = face.height * layout.scale
    gap = 10.0
    left = layout.row_label_width
    top = 118.0

    cv = S.Canvas(left + len(layout.columns) * (pw + gap) + 16,
                  top + len(layout.rows) * (ph + gap) + 6)

    delta = G.separation_degrees(hour, minute)
    cv.text(24, 32, layout.title, size=15, fill=S.LABEL, weight="600")
    cv.text(24, 50, layout.subtitle, size=10, fill=S.DIM)

    # Time and separation readout, plus a bar so the phase of the hour is
    # readable at a glance while the loop runs.
    cv.text(cv.width - 24, 32, label_time(hour, minute), size=20,
            fill=S.LABEL, anchor="end", weight="600")
    cv.text(cv.width - 24, 50, f"delta = {delta:5.1f} deg", size=11,
            fill=S.PIVOT, anchor="end")

    bar_x, bar_w, bar_y = 24.0, cv.width - 220.0, 64.0
    cv.rect(bar_x, bar_y, bar_w, 4, fill="#242a31", rx=2)
    cv.rect(bar_x, bar_y, bar_w * (minute / (ANIM_FRAMES - 1)), 4,
            fill=S.PIVOT, rx=2, opacity=0.9)
    for mark, tag in ((0.0, "overlap"), (32.7 / 59.0, "opposition")):
        cv.line(bar_x + bar_w * mark, bar_y - 4, bar_x + bar_w * mark,
                bar_y + 8, stroke=S.TIP, stroke_width=0.8, opacity=0.8)
        cv.text(bar_x + bar_w * mark, bar_y + 19, tag, size=8, fill=S.DIM,
                anchor="middle" if mark > 0.05 else "start")

    for column, candidate in enumerate(candidates):
        x = left + column * (pw + gap)
        cv.text(x + pw / 2, top - 10, candidate.label, size=11, fill=S.LABEL,
                anchor="middle", weight="600")

    for row, stems in enumerate(layout.rows):
        y = top + row * (ph + gap)
        if layout.show_row_labels:
            cv.text(20, y + ph / 2 - 4, stems.name, size=11, fill=S.LABEL,
                    weight="600")
            cv.text(20, y + ph / 2 + 10,
                    f"r {stems.hour_inner:.2f}/{stems.minute_inner:.2f}R",
                    size=8, fill=S.DIM)
        for column, candidate in enumerate(candidates):
            x = left + column * (pw + gap)
            cl = G.build_centerline(hour, minute, candidate.rule, face, stems)
            depth = G.norm(G.sub(cl.pivot, cl.context.center))
            draw_panel(cv, x, y, face, stems, hour, minute, candidate,
                       underlay=reference, footer=f"s = {depth:.1f} px",
                       show_triangle=False, scale=layout.scale,
                       line_width=1.9)
    return cv


def write_animation_frames(face, layout: AnimLayout, hour: int, out_dir,
                           fps: int = ANIM_FPS) -> int:
    directory = os.path.join(out_dir, "anim", layout.name)
    os.makedirs(directory, exist_ok=True)
    for old in os.listdir(directory):
        if old.endswith(".svg"):
            os.remove(os.path.join(directory, old))

    first = animation_frame(face, layout, hour, 0)
    for minute in range(ANIM_FRAMES):
        canvas = animation_frame(face, layout, hour, minute)
        canvas.write(os.path.join(directory, f"frame-{minute:04d}.svg"))

    with open(os.path.join(directory, "manifest.txt"), "w",
              encoding="utf-8") as handle:
        handle.write(
            f"name {layout.name}\n"
            f"frames {ANIM_FRAMES}\n"
            f"fps {fps}\n"
            f"hour {hour}\n"
            f"width {int(first.width)}\n"
            f"height {int(first.height)}\n"
        )
    return ANIM_FRAMES


FILMSTRIP_KEYS = ("d1-arc-sin", "d3-arc-p075", "c3-chord-035")


def sheet_filmstrip(face, stems, hour, out_path, step: int = 5) -> None:
    """A static contact sheet of the same hour, for frame-by-frame study and in
    case a GIF will not play wherever these end up being viewed."""
    minutes = list(range(0, 60, step))
    rows = [G.CANDIDATES_BY_KEY[key] for key in FILMSTRIP_KEYS]
    reference = G.CANDIDATES_BY_KEY["c0-current"]
    scale = 0.56
    pw, ph = face.width * scale, face.height * scale
    gap, left, top = 5, 172, 96
    cv = S.Canvas(left + len(minutes) * (pw + gap) + 16,
                  top + len(rows) * (ph + gap) + 24)

    cv.text(24, 32, f"The {label_time(hour, 0)} hour, every {step} minutes",
            size=16, fill=S.LABEL, weight="600")
    cv.text(24, 50, "white = candidate     amber = current construction     "
            f"{face.name}, stems: {stems.describe()}", size=10, fill=S.DIM)
    cv.text(24, 68, "delta runs 0 -> 180 -> 35.5 deg over the hour, so overlap "
            "and near-opposition both appear once.", size=10, fill=S.DIM)

    for column, minute in enumerate(minutes):
        x = left + column * (pw + gap)
        cv.text(x + pw / 2, top - 16, label_time(hour, minute), size=9,
                fill=S.LABEL, anchor="middle", weight="600")
        cv.text(x + pw / 2, top - 5,
                f"{G.separation_degrees(hour, minute):.0f}", size=8,
                fill=S.DIM, anchor="middle")

    for row, candidate in enumerate(rows):
        y = top + row * (ph + gap)
        cv.text(16, y + 16, candidate.label, size=10, fill=S.LABEL,
                weight="600")
        cv.text(16, y + 28, candidate.formula[:26], size=7, fill=S.DIM)
        cv.text(16, y + 38, candidate.formula[26:], size=7, fill=S.DIM)
        for column, minute in enumerate(minutes):
            draw_panel(cv, left + column * (pw + gap), y, face, stems, hour,
                       minute, candidate, underlay=reference,
                       show_triangle=False, scale=scale, line_width=1.5)
    cv.write(out_path)


# ---------------------------------------------------------------------------
# Metrics report
# ---------------------------------------------------------------------------

def write_metrics(face, out_path) -> list[Summary]:
    everything: list[Summary] = []
    lines = [
        "# Pivot candidate metrics",
        "",
        f"Face: **{face.name} {face.width}x{face.height}**, "
        f"R = {face.max_radius:.0f} px. All 720 clock positions per row.",
        "",
        "Columns:",
        "",
        "- **swerve** - worst excursion to the wrong side of the chord A-B, in px.",
        "  This is the meaningful no-swerve test; the gate is "
        f"< {SWERVE_GATE_PX} px.",
        "- **k flips** - positions with an analytic curvature sign change. Kept for",
        "  transparency, but a flip carrying 0.02% of the turning is invisible, so",
        "  read it alongside the swerve column, not instead of it.",
        "- **joint dk** - curvature discontinuity at the pivot, relative to peak |k|.",
        "  The minimum-bending solve makes this zero; a non-zero value is a bug.",
        f"- **min R** - tightest radius of curvature, px, excluding positions within",
        f"  {OVERLAP_GUARD_DEG:.0f} deg of overlap (the accepted degenerate hairpin).",
        "- **minR90** - same, but only for delta >= 90 deg. Unambiguous and directly",
        "  comparable between candidates; the column above is always set by the",
        "  lowest-delta position still in range, so it mostly restates the guard.",
        "- **s max** - deepest pivot excursion and the delta at which it occurs.",
        "- **turn share** - fraction of the total turn taken by the hour half;",
        "  0.500 is symmetric. Mean over the 720, then the worst case.",
        "- **k_h/k_m** - mean ratio of peak curvature between the two halves.",
        "  Above 1 means the hour half turns tighter.",
        "- **dip** - worst interior dip in |k|, as a fraction of the flanking",
        "  peaks. 0 is unimodal; a positive value is the curve flattening at the",
        f"  pivot. **fail** counts positions dipping more than {DIP_GATE:.0%}.",
        "- **head** - worst s / arc-apex ceiling, over positions where the",
        f"  ceiling exceeds {HEADROOM_MIN_CEILING_PX:.0f} px. Crossing ~1.0 is what",
        "  predicts the dip, which is the evidence that the arc apex is the right",
        "  length scale. Note the D family reports ~1.00 because its nu tends to 1",
        "  as delta approaches 180, where the ceiling and the geometry are both",
        "  sub-pixel; through the mid range its headroom is ~0.85.",
        "- **out** / **fb** - pivots outside the tangent triangle / solver fallbacks.",
        "",
    ]

    lines += [
        "## Opposition behaviour",
        "",
        "An off-centre pivot at opposition only forces an inflection if the "
        "offset has a",
        "component *perpendicular* to the hands' axis. An offset **along** the "
        "axis moves the",
        "pivot off the centre and still leaves curvature identically zero. "
        "So the two",
        "readings of \"not constrained to the centre\" are not actually in "
        "conflict -- only a",
        "perpendicular bow is.",
        "",
        "| candidate | s @ 180 | perp @ 180 | s @ 179.5 | perp @ 179.5 | "
        "perp < 0.5 px |",
        "|---|---:|---:|---:|---:|:--:|",
    ]
    for candidate in ALL_CANDIDATES:
        row = []
        for hour, minute in ((6, 0), (3, 49)):
            cl = G.build_centerline(hour, minute, candidate.rule, face,
                                    G.DEFAULT_STEMS)
            offset = G.sub(cl.pivot, cl.context.center)
            row.append((G.norm(offset),
                        abs(G.cross(cl.context.hour_radial, offset))))
        straight = row[1][1] < 0.5   # half a pixel: invisible
        lines.append(
            f"| {candidate.label} | {row[0][0]:.2f} | {row[0][1]:.3f} | "
            f"{row[1][0]:.2f} | {row[1][1]:.3f} | "
            f"{'yes' if straight else 'NO'} |"
        )
    lines.append("")

    for stems in G.STEM_CONFIGS:
        lines += [
            f"## stems: `{stems.name}` - {stems.describe()}",
            "",
            "| candidate | dip | fail | head | swerve | minR90 | s max | @ delta "
            "| turn share | k_h/k_m | out | fb | gate |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|:--:|",
        ]
        for candidate in ALL_CANDIDATES:
            s = summarise(candidate, face, stems)
            everything.append(s)
            lines.append(
                f"| {candidate.label} | {s.worst_dip * 100:.0f}% | "
                f"{s.dip_failures} | {s.max_headroom:.2f} | "
                f"{s.max_swerve:.4f} | {s.min_radius_open:.1f} | "
                f"{s.max_depth:.1f} | {s.peak_delta:.0f} | "
                f"{s.mean_turn_share:.3f} | {s.mean_k_ratio:.2f} | "
                f"{s.outside_triangle} | {s.solver_fallbacks} | "
                f"{'pass' if s.passes else 'FAIL'} |"
            )
        lines.append("")

    with open(out_path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    return everything


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_time(text: str) -> tuple[int, int]:
    hour, minute = text.split(":")
    return int(hour), int(minute)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true", help="every output")
    parser.add_argument("--grid", action="store_true")
    parser.add_argument("--zoom", action="store_true")
    parser.add_argument("--curvature", action="store_true")
    parser.add_argument("--ceiling", action="store_true")
    parser.add_argument("--anim", action="store_true",
                        help="emit per-frame SVGs; then run ./render_anim.sh")
    parser.add_argument("--filmstrip", action="store_true")
    parser.add_argument("--anim-hour", type=int, default=12)
    parser.add_argument("--anim-fps", type=int, default=ANIM_FPS)
    parser.add_argument("--tilt", action="store_true")
    parser.add_argument("--stems", action="store_true")
    parser.add_argument("--profiles", action="store_true")
    parser.add_argument("--locus", action="store_true")
    parser.add_argument("--metrics", action="store_true")
    parser.add_argument("--times", default=None,
                        help="comma-separated H:MM list, e.g. 12:00,3:00,6:00")
    parser.add_argument("--stem-config", default="current",
                        choices=[s.name for s in G.STEM_CONFIGS])
    parser.add_argument("--out", default=OUT_DIR)
    args = parser.parse_args()

    if not any((args.all, args.grid, args.zoom, args.curvature,
                args.ceiling, args.anim, args.filmstrip, args.tilt,
                args.stems, args.profiles, args.locus, args.metrics)):
        args.all = True

    face = G.Face()
    stems = G.STEMS_BY_NAME[args.stem_config]
    times = (tuple(parse_time(t) for t in args.times.split(","))
             if args.times else DEFAULT_TIMES)
    os.makedirs(args.out, exist_ok=True)

    def path(name):
        return os.path.join(args.out, name)

    if args.all or args.grid:
        sheet_compare(face, stems, times, path("compare-grid.svg"))
        print("wrote compare-grid.svg")
    if args.all or args.zoom:
        sheet_compare_zoom(face, stems, times, path("compare-zoom.svg"))
        print("wrote compare-zoom.svg")
    if args.all or args.curvature:
        sheet_curvature(face, stems, times, path("curvature-profiles.svg"))
        print("wrote curvature-profiles.svg")
    if args.all or args.ceiling:
        sheet_ceiling(face, stems, path("ceiling.svg"), path("ceiling.json"))
        print("wrote ceiling.svg, ceiling.json")
    if args.all or args.tilt:
        sheet_tilt(face, stems, times, path("tilt-grid.svg"))
        print("wrote tilt-grid.svg")
    if args.all or args.stems:
        sheet_stems(face, times, path("stems-grid.svg"))
        print("wrote stems-grid.svg")
    if args.all or args.profiles:
        sheet_profiles(face, stems, path("profiles.svg"))
        print("wrote profiles.svg")
    if args.all or args.locus:
        sheet_locus(face, stems, path("pivot-locus.svg"))
        print("wrote pivot-locus.svg")
    if args.all or args.filmstrip:
        sheet_filmstrip(face, stems, args.anim_hour, path("anim-filmstrip.svg"))
        print("wrote anim-filmstrip.svg")
    if args.all or args.anim:
        for layout in ANIM_LAYOUTS:
            count = write_animation_frames(face, layout, args.anim_hour,
                                           args.out, args.anim_fps)
            print(f"wrote {count} frames to anim/{layout.name}/ "
                  f"-- now run ./render_anim.sh {layout.name}")
    if args.all or args.metrics:
        write_metrics(face, path("metrics.md"))
        print("wrote metrics.md")


if __name__ == "__main__":
    main()
