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
NU_MAX = 2.0e8


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
    family: str = "f1"
    #: Closest approach of the *dense* solved curve to the centre.  The drawn
    #: polyline can only get within half a sample spacing of this, so the two
    #: are reported separately rather than conflated.
    exact_depth: float = 0.0
    tangent_length: float = 0.0   # d, compact families only
    hump_length: float = 0.0      # H, compact families only
    clamped: bool = False         # depth target beyond the family's reach

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


def _grid(m: float, n: float, steps: int, uniform: bool = False) -> list[float]:
    """Sample positions in t, concentrated where the curvature actually is.

    A shape with concentration nu = m + n has its spike about
    sqrt(q(1-q)/nu) wide.  Stepping uniformly in t walks straight past it once
    nu is large, which silently truncated the turn and forced the old code to
    fall back to the degenerate fold (and produced nonsense curvature radii).
    Overlaying a fine grid across +/- 8 sigma of the peak resolves the spike at
    any concentration, so the concentration is no longer capped by the
    integrator -- only by the geometry.
    """
    if uniform:
        return [i / steps for i in range(steps + 1)]

    total = m + n
    peak = m / total if total > 0.0 else 0.5
    sigma = math.sqrt(max(peak * (1.0 - peak) / max(total, 1.0), 1e-18))

    coarse = [i / steps for i in range(steps + 1)]
    lo = max(0.0, peak - 8.0 * sigma)
    hi = min(1.0, peak + 8.0 * sigma)
    fine_count = steps * 4
    fine = [lo + (hi - lo) * i / fine_count for i in range(fine_count + 1)]

    merged = sorted(set(coarse) | set(fine))
    return merged


def _integrate(turn: float, m: float, n: float, steps: int,
               uniform: bool = False):
    """Unit-length curve starting at the origin heading along +x.

    Trapezoid rule over a non-uniform grid, so the spike is resolved whatever
    the concentration.  Returns points, per-sample curvature (for L = 1) and
    the chord.
    """
    shape = _shape(m, n)
    ts = _grid(m, n, steps, uniform)
    samples = [shape(t) for t in ts]

    total = 0.0
    for i in range(len(ts) - 1):
        total += 0.5 * (ts[i + 1] - ts[i]) * (samples[i] + samples[i + 1])
    if total < 1e-300:
        return None
    scale = turn / total

    x = y = 0.0
    angle = 0.0
    points = [(0.0, 0.0)]
    curvatures = [samples[0] * scale]
    for i in range(len(ts) - 1):
        h = ts[i + 1] - ts[i]
        k0 = samples[i] * scale
        k1 = samples[i + 1] * scale
        midpoint_angle = angle + 0.5 * h * k0
        x += h * math.cos(midpoint_angle)
        y += h * math.sin(midpoint_angle)
        angle += 0.5 * h * (k0 + k1)
        points.append((x, y))
        curvatures.append(k1)
    return points, curvatures, (x, y)


def _solve_peak(turn: float, need: float, nu: float, steps: int,
                uniform: bool = False) -> float | None:
    """Peak location q whose chord direction matches `need`.  Monotone in q."""
    def error(q: float) -> float | None:
        m = max(nu * q, 1.0)
        n = max(nu * (1.0 - q), 1.0)
        result = _integrate(turn, m, n, steps, uniform)
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


def _attempt(A, B, u_in, u_out, nu, steps, centre, uniform=False):
    if uniform:
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

    q = _solve_peak(turn, need, nu, steps, uniform)
    if q is None:
        return None
    m = max(nu * q, 1.0)
    n = max(nu * (1.0 - q), 1.0)
    result = _integrate(turn, m, n, steps, uniform)
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
    uniform_integrator: bool = False,
) -> BetaCenterline | None:
    """Build the sweep with the connector's curvature prescribed, driven to the
    depth that `depth_rule` (a pivot rule, e.g. D1) asks for."""
    reference = G.build_centerline(hours, minutes, depth_rule, face, stems)
    ctx = reference.context
    centre = ctx.center
    A, B = reference.hour_connector, reference.minute_connector
    u_in = G.scale(ctx.hour_radial, -1.0)
    u_out = ctx.minute_radial
    depth_target = G.norm(G.sub(reference.pivot, centre))

    def finish(points, curvatures, q, nu, L, degenerate, exact=None,
               clamped=False):
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
            family="f1",
            exact_depth=(min(G.norm(G.sub(p, centre)) for p in points)
                         if exact is None else exact),
            clamped=clamped,
        )

    # Depth falls monotonically as concentration rises, so bisect on nu.
    lo, hi = NU_MIN, NU_MAX
    best_lo = _attempt(A, B, u_in, u_out, lo, SEARCH_STEPS, centre, uniform_integrator)
    best_hi = _attempt(A, B, u_in, u_out, hi, SEARCH_STEPS, centre, uniform_integrator)
    if best_lo is None and best_hi is None:
        points = _degenerate_fold(A, B, centre, connector_samples)
        return finish(points, [0.0] * len(points), 0.5, math.inf, 0.0, True)

    if best_hi is not None and best_hi["depth"] > depth_target:
        # even maximum concentration cannot reach the centre: use the fold
        points = _degenerate_fold(A, B, centre, connector_samples)
        return finish(points, [0.0] * len(points), 0.5, math.inf, 0.0, True)

    limited = False
    if best_lo is not None and best_lo["depth"] < depth_target:
        # nu = 2 is the gentlest Beta whose curvature still vanishes at both
        # ends (m, n >= 1), so the family has a *maximum* reachable depth and
        # runs out of it at wide separations.  Take the gentlest and say so.
        chosen = best_lo
        limited = True
    else:
        for _ in range(30):
            mid = math.sqrt(lo * hi)
            probe = _attempt(A, B, u_in, u_out, mid, SEARCH_STEPS, centre, uniform_integrator)
            if probe is None:
                lo = mid
                continue
            if probe["depth"] > depth_target:
                lo = mid
            else:
                hi = mid
        chosen = _attempt(A, B, u_in, u_out, hi, SEARCH_STEPS, centre, uniform_integrator)
        if chosen is None:
            points = _degenerate_fold(A, B, centre, connector_samples)
            return finish(points, [0.0] * len(points), 0.5, math.inf, 0.0, True)

    fine = _attempt(A, B, u_in, u_out, chosen["nu"], FINAL_STEPS, centre,
                     uniform_integrator)
    chosen = fine or chosen
    pts = chosen["points"]
    ks = chosen["curvatures"]
    exact = chosen["depth"]
    drawn, drawn_k = _resample_by_turn(pts, ks, connector_samples)
    return finish(drawn, drawn_k, chosen["q"], chosen["nu"], chosen["L"], False,
                  exact=exact, clamped=limited)


# ---------------------------------------------------------------------------
# Compact-support families (F2, F3, F4)
# ---------------------------------------------------------------------------
#
# F1 spreads k over the whole connector, so k can only reach zero *at* the
# junctions -- asymptotically.  A deep pivot then demands enormous
# concentration, which is what made it numerically awkward near overlap.
#
# The compact families invert that: k is exactly zero over a straight lead-in,
# rises through a single hump, and returns to exactly zero for a straight
# lead-out.  Because both stem tangent lines are radial they meet at the watch
# centre C, so those straight runs lie *along* the radials and the whole
# connector is literally a corner-rounding of the tangent triangle (A, C, B).
#
# That gives the construction for free.  A hump with a symmetric shape is
# mirror-symmetric about its own midpoint, so it leaves and rejoins the two
# radial lines at the *same* distance d from C.  Hence
#
#     straight lengths     alpha = r_h - d,  beta = r_m - d
#     hump chord           |SE|  = 2 d sin(delta/2)  =  H * g(Omega)
#     depth (apex to C)    s     = d cos(delta/2) - H * sigma(Omega)
#
# where H is the hump's arc length and g, sigma are the chord length and
# sagitta of the *unit-length* hump -- pure shape constants at a given turn.
# Eliminating H leaves the depth exactly proportional to d:
#
#     s = d * [ cos(delta/2) - 2 sin(delta/2) sigma(Omega) / g(Omega) ]
#
# so the single dial d is a *division*, not a root find.  There is no
# concentration to diverge, no spike to resolve, and the overlap case needs no
# special handling: the depth target goes to zero, so d and H go to zero and the
# curve becomes the fold A -> C -> B on its own.
#
# For F4 (constant k) g and sigma are closed form and the bracket collapses to
# cos(d/2)/(1 + sin(d/2)) -- i.e. F4's reachable depth range is exactly
# [0, arc_apex_ceiling], the bound geometry.py already derived.

#: Samples across the hump when integrating the Frenet equations.  The hump has
#: no spike by construction, so a fixed uniform grid suffices.
HUMP_STEPS = 240


@dataclass(frozen=True)
class HumpShape:
    """A symmetric, non-negative shape for k across the turning region."""

    key: str
    label: str
    phi: object                  # callable: [0,1] -> >= 0
    breaks: tuple[float, ...] = ()   # interior kinks, sampled exactly
    smooth_join: bool = True     # does phi vanish at both ends?
    #: (chord, sagitta) of the unit hump in closed form, when one exists.
    exact_gs: object = None


def _trapezoid_phi(rho: float):
    def phi(t: float) -> float:
        if t <= 0.0 or t >= 1.0:
            return 0.0
        if t < rho:
            return t / rho
        if t > 1.0 - rho:
            return (1.0 - t) / rho
        return 1.0
    return phi


_RHO = 1.0 / 3.0

F2 = HumpShape("f2", "F2 trapezoid k (clothoid-arc-clothoid)",
               _trapezoid_phi(_RHO), breaks=(_RHO, 1.0 - _RHO))
F3 = HumpShape("f3", "F3 raised-cosine k (compact support)",
               lambda t: 0.0 if t <= 0.0 or t >= 1.0
               else 0.5 * (1.0 - math.cos(2.0 * math.pi * t)))
def _arc_gs(turn: float) -> tuple[float, float]:
    """A unit-length circular arc turning `turn`: chord and sagitta."""
    return (2.0 * math.sin(0.5 * turn) / turn,
            (1.0 - math.cos(0.5 * turn)) / turn)


F4 = HumpShape("f4", "F4 constant k (straight-arc-straight)",
               lambda t: 0.0 if t <= 0.0 or t >= 1.0 else 1.0,
               smooth_join=False, exact_gs=_arc_gs)

HUMP_SHAPES = {shape.key: shape for shape in (F2, F3, F4)}


_hump_cache: dict = {}


def _hump_unit(shape: HumpShape, turn: float, steps: int = HUMP_STEPS):
    """The unit-arc-length hump in its own frame: starts at the origin heading
    along +x, turns by `turn`, has arc length 1.

    Returns (points, curvatures, g, sigma) where g is the chord length and sigma
    the sagitta (chord-to-apex distance).  Both are shape constants at a given
    turn, so the result is cached.
    """
    key = (shape.key, round(turn, 12), steps)
    hit = _hump_cache.get(key)
    if hit is not None:
        return hit

    if shape.key == "f4":
        # Constant k needs no quadrature at all: it is a circular arc of unit
        # arc length, so radius = 1/turn and every quantity is closed form.
        # This is the whole point of F4 as the cheap baseline.
        radius = 1.0 / turn
        points = [(radius * math.sin(turn * i / steps),
                   radius * (1.0 - math.cos(turn * i / steps)))
                  for i in range(steps + 1)]
        g, sigma = _arc_gs(turn)
        result = (points, [turn] * (steps + 1), g, sigma)
        _hump_cache[key] = result
        return result

    ts = sorted(set([i / steps for i in range(steps + 1)]) | set(shape.breaks))
    phis = [shape.phi(t) for t in ts]

    total = 0.0
    for i in range(len(ts) - 1):
        total += 0.5 * (ts[i + 1] - ts[i]) * (phis[i] + phis[i + 1])
    if total < 1e-300:
        return None
    scale = turn / total                      # k for unit arc length

    x = y = angle = 0.0
    points = [(0.0, 0.0)]
    curvatures = [phis[0] * scale]
    for i in range(len(ts) - 1):
        h = ts[i + 1] - ts[i]
        k0, k1 = phis[i] * scale, phis[i + 1] * scale
        mid = angle + 0.5 * h * k0
        x += h * math.cos(mid)
        y += h * math.sin(mid)
        angle += 0.5 * h * (k0 + k1)
        points.append((x, y))
        curvatures.append(k1)

    chord = points[-1]
    g = math.hypot(*chord)
    if g < 1e-12:
        return None
    # Symmetric shape => the apex is the sample at t = 0.5.
    apex = min(range(len(ts)), key=lambda i: abs(ts[i] - 0.5))
    ux, uy = chord[0] / g, chord[1] / g
    px, py = points[apex]
    sigma = abs(px * (-uy) + py * ux)
    if shape.exact_gs is not None:
        # Quadrature is accurate to ~1e-6 here, but the depth bracket is a
        # difference of comparable terms near opposition, so that noise decides
        # whether the family reports itself out of range.  Use the exact values
        # where they exist.
        g, sigma = shape.exact_gs(turn)

    result = (points, curvatures, g, sigma)
    _hump_cache[key] = result
    return result


def depth_bracket(shape: HumpShape, ctx: G.PivotContext) -> float | None:
    """s / d -- how much pivot depth one unit of tangent length buys."""
    turn = math.pi - math.acos(max(-1.0, min(1.0, ctx.radial_dot)))
    if turn < 1e-9:
        return None
    unit = _hump_unit(shape, turn)
    if unit is None:
        return None
    _, _, g, sigma = unit
    return ctx.half_cos - 2.0 * ctx.half_sin * sigma / g


def tangent_length_rule(ctx: G.PivotContext) -> float:
    """d = min(r_h, r_m) sin(delta/2) -- the compact families' own dial.

    Driving these families by a *depth* target imported from a pivot rule works,
    but each family converts tangent length into depth at its own rate, so a
    target tuned for one of them is out of reach for another (F3 runs out of
    stem at delta ~= 90).  Stating the rule on d instead removes that: it is the
    same one-line rule for every member, it can never ask for more stem than
    exists, and the resulting depth is a *consequence* of the shape rather than
    something imposed on it.

    It also has the right limits without any special casing: d -> 0 at overlap
    (so the connector folds exactly through the centre), d -> min(r) at
    opposition (so both straight runs vanish and the whole connector is one
    hump), and it scales with the stems, so it survives a change of stem length
    or symmetry.  For F4 it reproduces D1's depth rule identically, which is not
    a coincidence: D1's arc-apex ceiling *is* F4's geometry.
    """
    return min(ctx.hour_inner, ctx.minute_inner) * ctx.half_sin


def build_compact_centerline(
    hours: int, minutes: int,
    shape: HumpShape,
    depth_rule=None,
    face: G.Face = G.Face(),
    stems: G.Stems = G.DEFAULT_STEMS,
    connector_samples: int = G.CONNECTOR_SEGMENTS,
) -> BetaCenterline:
    """Straight-in / single-hump / straight-out connector.  Closed form.

    With `depth_rule` given, the tangent length is solved so the closest
    approach matches that rule's pivot depth.  With `depth_rule` None the
    family's own rule (`tangent_length_rule`) sets the tangent length directly
    and the depth follows from the shape.
    """
    rule = depth_rule or G.CANDIDATES_BY_KEY["d1-arc-sin"].rule
    reference = G.build_centerline(hours, minutes, rule, face, stems)
    ctx = reference.context
    centre = ctx.center
    A, B = reference.hour_connector, reference.minute_connector
    u_in = G.scale(ctx.hour_radial, -1.0)
    u_out = ctx.minute_radial
    target = G.norm(G.sub(reference.pivot, centre))

    sign = 1.0 if G.cross(u_in, u_out) >= 0.0 else -1.0
    delta = math.acos(max(-1.0, min(1.0, ctx.radial_dot)))
    turn = sign * (math.pi - delta)

    r_h, r_m = ctx.hour_inner, ctx.minute_inner
    d_max = min(r_h, r_m)

    unit = _hump_unit(shape, abs(turn)) if abs(turn) > 1e-9 else None
    bracket = None
    if unit is not None:
        _, _, g, sigma = unit
        bracket = ctx.half_cos - 2.0 * ctx.half_sin * sigma / g

    if depth_rule is None:
        d = tangent_length_rule(ctx)
    elif bracket is None or bracket <= 1e-9:
        d = 0.0
    else:
        d = target / bracket
    clamped = d > d_max
    d = min(d, d_max)

    # Hump arc length from the chord it has to span.
    if unit is None:
        H = 0.0
    else:
        _, _, g, _ = unit
        H = 2.0 * d * ctx.half_sin / g

    S = G.add(centre, G.scale(ctx.hour_radial, d))
    E = G.add(centre, G.scale(u_out, d))

    # Sample each piece on its own so S and E are exact vertices.  Uniform
    # spacing is exact on the straights and adequate on the hump, whose whole
    # length *is* the turning region -- there is no spike to chase, which is
    # the numerical dividend of compact support.  The hump always takes at
    # least half the samples because it holds all of the direction change; at
    # overlap H collapses to zero and every sample goes to the two radial runs,
    # leaving the fold vertex exactly on the centre.
    alpha, beta = r_h - d, r_m - d
    total_length = alpha + H + beta
    if H <= 1e-9 or total_length < 1e-12:
        n_hump = 0
    else:
        n_hump = max(2, int(round(connector_samples *
                                  (0.5 + 0.5 * H / total_length))))
        n_hump = min(n_hump, connector_samples - 2)
    rest = connector_samples - n_hump
    share = alpha / (alpha + beta) if (alpha + beta) > 1e-12 else 0.5
    n_h = max(1, min(rest - 1, int(round(rest * share))))
    n_m = rest - n_h

    points: list[G.Vec] = []
    kappas: list[float] = []
    for i in range(n_h + 1):
        points.append(G.add(A, G.scale(G.sub(S, A), i / n_h)))
        kappas.append(0.0)

    if n_hump:
        unit_points, unit_k, _, _ = unit
        start = math.atan2(u_in[1], u_in[0])
        ca, sa = math.cos(start), math.sin(start)
        last = len(unit_points) - 1
        for i in range(1, n_hump + 1):
            j = min(last, int(round(last * i / n_hump)))
            px, py = unit_points[j]
            py *= sign                # mirror for a right-hand turn
            points.append((S[0] + H * (px * ca - py * sa),
                           S[1] + H * (px * sa + py * ca)))
            kappas.append(abs(unit_k[j]) / H)
        points[-1] = E
        kappas[-1] = 0.0

    for i in range(1, n_m + 1):
        points.append(G.add(E, G.scale(G.sub(B, E), i / n_m)))
        kappas.append(0.0)

    # Closest approach of the *true* curve.  With a hump present, symmetry puts
    # it at the apex and the closed form gives it directly.  Without one -- at
    # exact overlap, and at exact opposition where the turn vanishes -- the
    # connector is straight pieces, so measure point-to-segment: both cases run
    # through the centre and must read zero.
    if unit is not None and H > 1e-9 and bracket is not None:
        exact_depth = d * bracket
    else:
        exact_depth = min(_segment_distance(points[i], points[i + 1], centre)
                          for i in range(len(points) - 1))
    drawn = points
    drawn_k = kappas

    pivot_index = min(range(len(drawn)),
                      key=lambda i: G.norm(G.sub(drawn[i], centre)))
    stem_h = [G.add(reference.hour_tip,
                    G.scale(G.sub(A, reference.hour_tip), i / G.HOUR_STEM_SEGMENTS))
              for i in range(G.HOUR_STEM_SEGMENTS)]
    stem_m = [G.add(B, G.scale(G.sub(reference.minute_tip, B),
                               i / G.MINUTE_STEM_SEGMENTS))
              for i in range(1, G.MINUTE_STEM_SEGMENTS + 1)]
    return BetaCenterline(
        points=stem_h + drawn + stem_m,
        hour_tip=reference.hour_tip, minute_tip=reference.minute_tip,
        hour_connector=A, minute_connector=B,
        pivot=drawn[pivot_index], context=ctx,
        peak=0.5, concentration=(0.0 if H <= 0.0 else abs(turn) / H),
        arc_length=(r_h - d) + H + (r_m - d),
        curvatures=drawn_k,
        degenerate=(H <= 1e-9),
        family=shape.key, exact_depth=exact_depth,
        tangent_length=d, hump_length=H, clamped=clamped,
    )


def _segment_distance(p, q, target) -> float:
    """Distance from `target` to the segment pq."""
    d = G.sub(q, p)
    length_sq = G.dot(d, d)
    if length_sq < 1e-18:
        return G.norm(G.sub(target, p))
    t = max(0.0, min(1.0, G.dot(G.sub(target, p), d) / length_sq))
    return G.norm(G.sub(target, G.add(p, G.scale(d, t))))


def _resample_by_turn(points, kappas, count):
    """Re-sample a dense polyline onto `count` segments, allocating half the
    samples by arc length and half by accumulated turning.

    Uniform arc length is the wrong measure here.  Near overlap the entire turn
    happens inside a window far narrower than one drawn segment, so a
    uniformly-spaced polyline chords straight across the fold: the *drawn* curve
    then misses the centre by over a pixel even though the true curve passes
    through it.  Weighting by turning as well puts samples where the direction
    is actually changing, at no extra cost.  The 50/50 split is structural, not
    an aesthetic dial.
    """
    n = len(points)
    if n < 3:
        return list(points), list(kappas)
    arc = [0.0]
    ang = [0.0]
    for i in range(1, n):
        step = G.norm(G.sub(points[i], points[i - 1]))
        arc.append(arc[-1] + step)
        ang.append(ang[-1] + 0.5 * step * (abs(kappas[i]) + abs(kappas[i - 1])))
    span_a, span_t = arc[-1], ang[-1]
    if span_a < 1e-12:
        return list(points), list(kappas)
    w = [(0.5 * a / span_a + 0.5 * t / span_t) if span_t > 1e-12 else a / span_a
         for a, t in zip(arc, ang)]

    out_p, out_k = [], []
    j = 0
    for i in range(count + 1):
        want = w[-1] * i / count
        while j + 1 < n - 1 and w[j + 1] < want:
            j += 1
        seg = w[j + 1] - w[j]
        f = 0.0 if seg < 1e-15 else (want - w[j]) / seg
        f = max(0.0, min(1.0, f))
        out_p.append(G.add(points[j], G.scale(G.sub(points[j + 1], points[j]), f)))
        out_k.append(kappas[j] + (kappas[j + 1] - kappas[j]) * f)
    return out_p, out_k
