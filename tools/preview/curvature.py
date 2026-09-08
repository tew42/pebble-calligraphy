"""Curvature-prescribed connector: choose k(s), then solve for the geometry.

Every earlier construction interpolated geometry and hoped the curvature came
out right.  The design requirement is stated on k, so here k is the primitive:

    k(s) = (Omega / L) * t^m (1-t)^n / integral(t^m (1-t)^n),   t = s/L

which is non-negative (single-signed), zero at both stem junctions for
m, n >= 1, has exactly one maximum at t = m/(m+n), is continuous, and turns by
exactly Omega = pi - delta.  All structural, none of it tuned.

Because k scales as 1/L, changing L yields a geometrically *similar* curve.  So
the solve decouples:

    q  = m/(m+n)  -- peak location, set by the required chord DIRECTION
    L             -- set by the chord LENGTH, one division
    nu = m + n    -- concentration, set by the required pivot DEPTH

Concentration is the dial that trades centre-passage against curvature
continuity: large nu drives the curve close to the centre with a tight fold
(the accepted degeneracy near overlap), moderate nu gives a broad off-centre
bend.  Pinning the depth at both ends of the delta range therefore *determines*
nu rather than leaving it free.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import geometry as G

#: Integration steps for the search passes and for the final sampling.
SEARCH_STEPS = 96
FINAL_STEPS = 320

#: A shape with concentration nu has its spike about 1/sqrt(nu) wide, so the
#: integration has to be refined with nu or the spike is simply missed.
def _steps_for(nu: float, base: int) -> int:
    return max(base, int(14.0 * math.sqrt(max(nu, 1.0))))

#: Concentration ladder bounds.  Near overlap the depth target drives nu up
#: without limit; past this we hand over to the degenerate fold instead.
NU_MIN = 2.0
NU_MAX = 60000.0


@dataclass(frozen=True)
class BetaCenterline:
    """Attribute-compatible with geometry.Centerline for the drawing code."""

    points: list[G.Vec]
    hour_tip: G.Vec
    minute_tip: G.Vec
    hour_connector: G.Vec
    minute_connector: G.Vec
    pivot: G.Vec
    context: G.PivotContext
    peak: float          # q
    concentration: float # nu
    arc_length: float    # L
    curvatures: list[float]
    degenerate: bool = False

    @property
    def depth(self) -> float:
        return G.norm(G.sub(self.pivot, self.context.center))


def _shape(m: float, n: float):
    """t^m (1-t)^n, evaluated in log space and scaled to a peak of 1.

    Direct evaluation underflows to zero for large exponents (t**4000 == 0.0 for
    any t < 1), which silently produced an all-zero curvature.  Working in logs
    relative to the peak keeps it exact for any concentration; the absolute
    scale does not matter because the integration pass normalises anyway.
    """
    peak = m / (m + n) if (m + n) > 0.0 else 0.5
    log_peak = m * math.log(peak) + n * math.log1p(-peak)

    def value(t: float) -> float:
        if t <= 0.0 or t >= 1.0:
            return 0.0
        exponent = m * math.log(t) + n * math.log1p(-t) - log_peak
        return math.exp(exponent) if exponent > -700.0 else 0.0

    return value


def _integrate(turn: float, m: float, n: float, steps: int):
    """Unit-length curve starting at the origin heading along +x.

    Returns points, the per-sample curvature (for L = 1) and the chord.
    """
    shape = _shape(m, n)
    # normalise the shape so that its integral over [0,1] is 1
    total = 0.0
    h = 1.0 / steps
    samples = [shape(i * h) for i in range(steps + 1)]
    for i in range(steps):
        total += 0.5 * h * (samples[i] + samples[i + 1])
    if total < 1e-300:
        return None
    scale = turn / total

    x = y = 0.0
    angle = 0.0
    points = [(0.0, 0.0)]
    curvatures = [samples[0] * scale]
    for i in range(steps):
        k0 = samples[i] * scale
        k1 = samples[i + 1] * scale
        midpoint_angle = angle + 0.5 * h * k0
        x += h * math.cos(midpoint_angle)
        y += h * math.sin(midpoint_angle)
        angle += 0.5 * h * (k0 + k1)
        points.append((x, y))
        curvatures.append(k1)
    return points, curvatures, (x, y)


def _solve_peak(turn: float, need: float, nu: float, steps: int) -> float | None:
    """Peak location q whose chord direction matches `need`.  Monotone in q."""
    def error(q: float) -> float | None:
        m = max(nu * q, 1.0)
        n = max(nu * (1.0 - q), 1.0)
        result = _integrate(turn, m, n, steps)
        if result is None:
            return None
        _, _, chord = result
        if math.hypot(*chord) < 1e-12:
            return None
        got = math.atan2(chord[1], chord[0])
        return (got - need + math.pi) % (2 * math.pi) - math.pi

    low, high = 1e-4, 1.0 - 1e-4
    e_low, e_high = error(low), error(high)
    if e_low is None or e_high is None or e_low * e_high > 0.0:
        return None
    for _ in range(44):
        mid = 0.5 * (low + high)
        e_mid = error(mid)
        if e_mid is None:
            return None
        if e_low * e_mid <= 0.0:
            high = mid
        else:
            low, e_low = mid, e_mid
    return 0.5 * (low + high)


def _place(origin: G.Vec, start_angle: float, unit_points, scale: float):
    ca, sa = math.cos(start_angle), math.sin(start_angle)
    return [(origin[0] + scale * (px * ca - py * sa),
             origin[1] + scale * (px * sa + py * ca)) for px, py in unit_points]


def _attempt(A, B, u_in, u_out, nu, steps, centre):
    steps = _steps_for(nu, steps)
    start = math.atan2(u_in[1], u_in[0])
    end = math.atan2(u_out[1], u_out[0])
    turn = (end - start + math.pi) % (2 * math.pi) - math.pi
    if abs(turn) < 1e-9:
        return None
    chord = G.sub(B, A)
    chord_length = G.norm(chord)
    if chord_length < 1e-9:
        return None
    need = (math.atan2(chord[1], chord[0]) - start + math.pi) % (2 * math.pi) - math.pi

    q = _solve_peak(turn, need, nu, steps)
    if q is None:
        return None
    m = max(nu * q, 1.0)
    n = max(nu * (1.0 - q), 1.0)
    result = _integrate(turn, m, n, steps)
    if result is None:
        return None
    unit_points, unit_k, unit_chord = result
    unit_length = math.hypot(*unit_chord)
    if unit_length < 1e-12:
        return None
    L = chord_length / unit_length
    placed = _place(A, start, unit_points, L)
    depth = min(G.norm(G.sub(p, centre)) for p in placed)
    return dict(q=q, nu=nu, L=L, points=placed,
                curvatures=[k / L for k in unit_k], depth=depth)


def _degenerate_fold(A, B, centre, steps):
    """Straight in to the centre, reverse, straight out.  The accepted overlap
    construction, and the limit of this family as concentration diverges."""
    half = steps // 2
    inward = [G.add(A, G.scale(G.sub(centre, A), i / half)) for i in range(half + 1)]
    outward = [G.add(centre, G.scale(G.sub(B, centre), i / (steps - half)))
               for i in range(1, steps - half + 1)]
    return inward + outward


def build_beta_centerline(
    hours: int, minutes: int,
    depth_rule,
    face: G.Face = G.Face(),
    stems: G.Stems = G.DEFAULT_STEMS,
    connector_samples: int = G.CONNECTOR_SEGMENTS,
) -> BetaCenterline | None:
    """Build the sweep with the connector's curvature prescribed, driven to the
    depth that `depth_rule` (a pivot rule, e.g. D1) asks for."""
    reference = G.build_centerline(hours, minutes, depth_rule, face, stems)
    ctx = reference.context
    centre = ctx.center
    A, B = reference.hour_connector, reference.minute_connector
    u_in = G.scale(ctx.hour_radial, -1.0)
    u_out = ctx.minute_radial
    target = G.norm(G.sub(reference.pivot, centre))

    def finish(points, curvatures, q, nu, L, degenerate):
        pivot_index = min(range(len(points)),
                          key=lambda i: G.norm(G.sub(points[i], centre)))
        stem_h = [G.add(reference.hour_tip,
                        G.scale(G.sub(A, reference.hour_tip), i / G.HOUR_STEM_SEGMENTS))
                  for i in range(G.HOUR_STEM_SEGMENTS)]
        stem_m = [G.add(B, G.scale(G.sub(reference.minute_tip, B),
                                   i / G.MINUTE_STEM_SEGMENTS))
                  for i in range(1, G.MINUTE_STEM_SEGMENTS + 1)]
        return BetaCenterline(
            points=stem_h + points + stem_m,
            hour_tip=reference.hour_tip, minute_tip=reference.minute_tip,
            hour_connector=A, minute_connector=B,
            pivot=points[pivot_index], context=ctx,
            peak=q, concentration=nu, arc_length=L,
            curvatures=curvatures, degenerate=degenerate,
        )

    # Depth falls monotonically as concentration rises, so bisect on nu.
    lo, hi = NU_MIN, NU_MAX
    best_lo = _attempt(A, B, u_in, u_out, lo, SEARCH_STEPS, centre)
    best_hi = _attempt(A, B, u_in, u_out, hi, SEARCH_STEPS, centre)
    if best_lo is None and best_hi is None:
        points = _degenerate_fold(A, B, centre, connector_samples)
        return finish(points, [0.0] * len(points), 0.5, math.inf, 0.0, True)

    if best_hi is not None and best_hi["depth"] > target:
        # even maximum concentration cannot reach the centre: use the fold
        points = _degenerate_fold(A, B, centre, connector_samples)
        return finish(points, [0.0] * len(points), 0.5, math.inf, 0.0, True)

    if best_lo is not None and best_lo["depth"] < target:
        chosen = best_lo          # already shallower than asked; take the gentlest
    else:
        for _ in range(30):
            mid = math.sqrt(lo * hi)
            probe = _attempt(A, B, u_in, u_out, mid, SEARCH_STEPS, centre)
            if probe is None:
                lo = mid
                continue
            if probe["depth"] > target:
                lo = mid
            else:
                hi = mid
        chosen = _attempt(A, B, u_in, u_out, hi, SEARCH_STEPS, centre)
        if chosen is None:
            points = _degenerate_fold(A, B, centre, connector_samples)
            return finish(points, [0.0] * len(points), 0.5, math.inf, 0.0, True)

    fine = _attempt(A, B, u_in, u_out, chosen["nu"], FINAL_STEPS, centre)
    chosen = fine or chosen
    step = (len(chosen["points"]) - 1) / connector_samples
    idx = [round(i * step) for i in range(connector_samples + 1)]
    return finish([chosen["points"][i] for i in idx],
                  [chosen["curvatures"][i] for i in idx],
                  chosen["q"], chosen["nu"], chosen["L"], False)
