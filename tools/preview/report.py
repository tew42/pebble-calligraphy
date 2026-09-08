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

SWERVE_GATE_PX = 0.05
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
    else:
        swerve = 0.0

    centre = cl.context.center
    a, b, p = cl.hour_connector, cl.minute_connector, cl.pivot
    s1 = G.cross(G.sub(b, a), G.sub(p, a))
    s2 = G.cross(G.sub(centre, b), G.sub(p, b))
    s3 = G.cross(G.sub(a, centre), G.sub(p, centre))
    inside = (min(s1, s2, s3) >= -1e-6) or (max(s1, s2, s3) <= 1e-6)

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

    @property
    def passes(self) -> bool:
        return (
            self.max_swerve < SWERVE_GATE_PX
            and self.outside_triangle == 0
            and self.solver_fallbacks == 0
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
) -> tuple[float, float]:
    sc = PANEL_SCALE
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
                    stroke_width=1.4)
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
    rows = [c for c in G.CANDIDATES if c.key != "c0-current"]
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
    rows = [c for c in G.CANDIDATES if c.key != "c0-current"]
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
        for i, candidate in enumerate(G.TILT_SWEEP)
    )
    gap, left, top = 8, 24, 116
    cv = S.Canvas(left + len(times) * (ZOOM_BOX + gap) + 16, top + ZOOM_BOX + 40)

    cv.text(24, 34, "C10 - tilt bracket at fixed depth, centre region at "
            f"{ZOOM_BOX / (2 * ZOOM_HALF_SPAN):.1f}x", size=17, fill=S.LABEL,
            weight="600")
    cv.text(24, 54, "mu = sin^2(delta/2) throughout; only beta varies. Lower "
            "beta leans the pull toward the hour stem, higher toward the minute.",
            size=10, fill=S.DIM)

    bisector = G.beta_bisector(
        G.build_centerline(3, 0, G.CANDIDATES_BY_KEY["c1-openness"].rule,
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
        draw_zoom_panel(cv, x, top, face, stems, hour, minute, G.TILT_SWEEP[0],
                        overlays=overlays, index=900 + column)
    cv.write(out_path)


def sheet_stems(face, times, out_path,
                candidate_key: str = "c1-openness") -> None:
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
    shown = [c for c in G.CANDIDATES
             if c.key not in ("c5-centre", "c1-openness-070")]
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
    shown = [c for c in G.CANDIDATES if c.role in ("reference", "contender")]
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
    for candidate in G.CANDIDATES:
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
            "| candidate | swerve | k flips | joint dk | min R | minR90 | s max "
            "| @ delta | turn share | worst | k_h/k_m | out | fb | gate |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|:--:|",
        ]
        for candidate in G.CANDIDATES:
            s = summarise(candidate, face, stems)
            everything.append(s)
            lines.append(
                f"| {candidate.label} | {s.max_swerve:.4f} | "
                f"{s.sign_change_positions} | {s.max_joint_jump:.2e} | "
                f"{s.min_radius:.2f} | {s.min_radius_open:.2f} | "
                f"{s.max_depth:.1f} | {s.peak_delta:.0f} | "
                f"{s.mean_turn_share:.3f} | {s.worst_turn_share:.3f} | "
                f"{s.mean_k_ratio:.2f} | {s.outside_triangle} | "
                f"{s.solver_fallbacks} | {'pass' if s.passes else 'FAIL'} |"
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

    if not any((args.all, args.grid, args.zoom, args.tilt, args.stems,
                args.profiles, args.locus, args.metrics)):
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
    if args.all or args.metrics:
        write_metrics(face, path("metrics.md"))
        print("wrote metrics.md")


if __name__ == "__main__":
    main()
