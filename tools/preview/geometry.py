"""Pure-Python port of the Calligraphy watchface centerline construction.

Models the CENTERLINE ONLY -- the path the pen travels, before it is expanded
into a stroke.  Nothing here reproduces Pebble's `gpath` rasterization, the
width profile, or the antialiasing passes; see tools/preview/README.md.

Mirrors src/c/main.c: point_on_clock (:341) through build_centerline (:1038),
including the four-unknown minimum-bending-energy tangent solve (:733) and its
Gauss-Jordan solver (:527).  Stem radii and hand lengths are parameters rather
than constants so the same code can be swept over alternative stem geometries.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Sequence

# ---------------------------------------------------------------------------
# Pebble constants (docs/c/Foundation/Math)
# ---------------------------------------------------------------------------

TRIG_MAX_ANGLE = 0x10000
TRIG_MAX_RATIO = 0xFFFF

# Topology, from src/c/main.c:32-53.
HOUR_STEM_SEGMENTS = 8
CONNECTOR_SEGMENTS = 30
MINUTE_STEM_SEGMENTS = 10
CENTERLINE_POINT_COUNT = (
    HOUR_STEM_SEGMENTS + CONNECTOR_SEGMENTS + MINUTE_STEM_SEGMENTS + 1
)
CONNECTOR_FIRST_INDEX = HOUR_STEM_SEGMENTS
CONNECTOR_LAST_INDEX = HOUR_STEM_SEGMENTS + CONNECTOR_SEGMENTS

# Epsilons, from src/c/main.c:82-86.
VECTOR_EPSILON = 1e-4
SOLVER_EPSILON = 1e-5
MIN_PARAMETER_LENGTH = 1e-3
SOLVER_REGULARIZATION = 1e-4
MAX_SOLVER_RESULT_MAGNITUDE = 100.0

Vec = tuple[float, float]


# ---------------------------------------------------------------------------
# Vector helpers
# ---------------------------------------------------------------------------

def add(a: Vec, b: Vec) -> Vec:
    return (a[0] + b[0], a[1] + b[1])


def sub(a: Vec, b: Vec) -> Vec:
    return (a[0] - b[0], a[1] - b[1])


def scale(a: Vec, k: float) -> Vec:
    return (a[0] * k, a[1] * k)


def dot(a: Vec, b: Vec) -> float:
    return a[0] * b[0] + a[1] * b[1]


def cross(a: Vec, b: Vec) -> float:
    return a[0] * b[1] - a[1] * b[0]


def norm(a: Vec) -> float:
    return math.hypot(a[0], a[1])


def unit(a: Vec) -> Vec:
    length = norm(a)
    if length < VECTOR_EPSILON:
        return (0.0, -1.0)
    return (a[0] / length, a[1] / length)


def clamp(value: float, low: float, high: float) -> float:
    return low if value < low else high if value > high else value


def safe_parameter_length(length: float) -> float:
    return length if length > MIN_PARAMETER_LENGTH else MIN_PARAMETER_LENGTH


# ---------------------------------------------------------------------------
# Clock geometry
# ---------------------------------------------------------------------------

def sin_lookup(angle: int) -> int:
    """Emulates the SDK's integer sine table.

    The firmware reads a precomputed table; this rounds an exact sine to the
    same fixed-point resolution.  Any disagreement is well under 1/65535 of a
    hand length, i.e. far below a pixel.
    """
    return round(math.sin(2.0 * math.pi * angle / TRIG_MAX_ANGLE) * TRIG_MAX_RATIO)


def cos_lookup(angle: int) -> int:
    return sin_lookup(angle + TRIG_MAX_ANGLE // 4)


def point_on_clock(center: Vec, pebble_angle: int, length: float) -> Vec:
    """src/c/main.c:341 -- y is negated, so angle 0 is 12 o'clock, clockwise."""
    coordinate_scale = length / float(TRIG_MAX_RATIO)
    return (
        center[0] + sin_lookup(pebble_angle) * coordinate_scale,
        center[1] - cos_lookup(pebble_angle) * coordinate_scale,
    )


def minute_to_pebble_angle(minutes: int) -> int:
    return (TRIG_MAX_ANGLE * minutes) // 60


def hour_to_pebble_angle(hours: int, minutes: int) -> int:
    total_minutes = (hours % 12) * 60 + minutes
    return (TRIG_MAX_ANGLE * total_minutes) // (12 * 60)


def separation_degrees(hours: int, minutes: int) -> float:
    """Unsigned angle between the hands, in degrees, 0..180."""
    hour_angle = hour_to_pebble_angle(hours, minutes)
    minute_angle = minute_to_pebble_angle(minutes)
    delta = ((minute_angle - hour_angle) % TRIG_MAX_ANGLE) * 360.0 / TRIG_MAX_ANGLE
    return delta if delta <= 180.0 else 360.0 - delta


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Face:
    """Display geometry.  Defaults to emery (Pebble Time 2), the primary target."""

    name: str = "emery"
    width: int = 200
    height: int = 228

    @property
    def center(self) -> Vec:
        return (self.width * 0.5, self.height * 0.5)

    @property
    def max_radius(self) -> float:
        return min(self.width, self.height) * 0.5


@dataclass(frozen=True)
class Stems:
    """Hand and stem geometry, all as fractions of the face's maximum radius.

    `hour_inner` / `minute_inner` are the radii at which the straight radial
    stems end and the connector begins -- A and B.  The C code derives them as
    length * (1 - stem_ratio); here they are given directly so alternative stem
    geometries can be swept without solving for a ratio.
    """

    name: str
    hour_length: float = 0.60      # HOUR_LENGTH_RATIO
    minute_length: float = 0.90    # MINUTE_LENGTH_RATIO
    hour_inner: float = 0.45       # = 0.60 * (1 - HOUR_STEM_RATIO 0.25)
    minute_inner: float = 0.54     # = 0.90 * (1 - MINUTE_STEM_RATIO 0.40)

    def __post_init__(self) -> None:
        if not 0.0 < self.hour_inner < self.hour_length:
            raise ValueError(f"{self.name}: hour_inner must be in (0, hour_length)")
        if not 0.0 < self.minute_inner < self.minute_length:
            raise ValueError(f"{self.name}: minute_inner must be in (0, minute_length)")

    @property
    def hour_stem_ratio(self) -> float:
        return 1.0 - self.hour_inner / self.hour_length

    @property
    def minute_stem_ratio(self) -> float:
        return 1.0 - self.minute_inner / self.minute_length

    def describe(self) -> str:
        return (
            f"r_h={self.hour_inner:.2f}R r_m={self.minute_inner:.2f}R "
            f"(stem ratios {self.hour_stem_ratio:.3f}/{self.minute_stem_ratio:.3f})"
        )


#: The shipped geometry, plus alternatives the design may move to.  `long` uses
#: r_h = 0.56R rather than 0.60R because the hour stem must stay non-degenerate
#: (r_h < L_h = 0.60R).
STEM_CONFIGS: tuple[Stems, ...] = (
    Stems("current", hour_inner=0.45, minute_inner=0.54),
    Stems("symmetric", hour_inner=0.50, minute_inner=0.50),
    Stems("swapped", hour_inner=0.54, minute_inner=0.45),
    Stems("strong-asym", hour_inner=0.30, minute_inner=0.70),
    Stems("short", hour_inner=0.25, minute_inner=0.30),
    Stems("long", hour_inner=0.56, minute_inner=0.75),
)

STEMS_BY_NAME = {config.name: config for config in STEM_CONFIGS}
DEFAULT_STEMS = STEMS_BY_NAME["current"]


# ---------------------------------------------------------------------------
# Four-by-four linear solver (src/c/main.c:507-652)
# ---------------------------------------------------------------------------

def solve_augmented_system_4x4(
    matrix: list[list[float]], rhs: list[float]
) -> list[float] | None:
    augmented = [row[:] + [rhs[i]] for i, row in enumerate(matrix)]
    for pivot_column in range(4):
        pivot_row = pivot_column
        largest = abs(augmented[pivot_row][pivot_column])
        for row in range(pivot_column + 1, 4):
            candidate = abs(augmented[row][pivot_column])
            if candidate > largest:
                largest, pivot_row = candidate, row
        if largest < SOLVER_EPSILON:
            return None
        if pivot_row != pivot_column:
            augmented[pivot_column], augmented[pivot_row] = (
                augmented[pivot_row],
                augmented[pivot_column],
            )
        pivot_value = augmented[pivot_column][pivot_column]
        for column in range(pivot_column, 5):
            augmented[pivot_column][column] /= pivot_value
        for row in range(4):
            if row == pivot_column:
                continue
            factor = augmented[row][pivot_column]
            if abs(factor) < SOLVER_EPSILON:
                continue
            for column in range(pivot_column, 5):
                augmented[row][column] -= factor * augmented[pivot_column][column]

    solution = [augmented[i][4] for i in range(4)]
    if any(v != v or abs(v) > MAX_SOLVER_RESULT_MAGNITUDE for v in solution):
        return None
    return solution


_ZERO: Vec = (0.0, 0.0)
_UNIT_X: Vec = (1.0, 0.0)
_UNIT_Y: Vec = (0.0, 1.0)


def _add_minimum_bending_segment(
    matrix: list[list[float]],
    rhs: list[float],
    start_point: Vec,
    end_point: Vec,
    safe_length: float,
    start_coefficients: Sequence[Vec],
    end_coefficients: Sequence[Vec],
) -> None:
    """src/c/main.c:658 -- normal equations for the discretized bending integral."""
    inverse_length = 1.0 / safe_length
    inverse_length_squared = inverse_length * inverse_length
    chord = sub(end_point, start_point)

    for row in range(4):
        rhs[row] += (
            12.0
            * inverse_length_squared
            * dot(chord, add(start_coefficients[row], end_coefficients[row]))
        )
        for column in range(4):
            same_endpoint = dot(
                start_coefficients[row], start_coefficients[column]
            ) + dot(end_coefficients[row], end_coefficients[column])
            cross_endpoint = dot(
                start_coefficients[row], end_coefficients[column]
            ) + dot(start_coefficients[column], end_coefficients[row])
            matrix[row][column] += inverse_length * (
                8.0 * same_endpoint + 4.0 * cross_endpoint
            )


def calculate_minimum_bending_derivatives(
    hour_connector_point: Vec,
    guide_point: Vec,
    minute_connector_point: Vec,
    hour_radial_in: Vec,
    minute_radial_out: Vec,
    safe_hour_span: float,
    safe_minute_span: float,
) -> tuple[Vec, Vec, Vec, bool]:
    """src/c/main.c:733.  Returns (hour, guide, minute) derivatives and whether
    the solve succeeded (False means the straight-chord fallback was used)."""
    matrix = [[0.0] * 4 for _ in range(4)]
    rhs = [0.0] * 4

    hour_start = [hour_radial_in, _ZERO, _ZERO, _ZERO]
    hour_end = [_ZERO, _UNIT_X, _UNIT_Y, _ZERO]
    minute_start = [_ZERO, _UNIT_X, _UNIT_Y, _ZERO]
    minute_end = [_ZERO, _ZERO, _ZERO, minute_radial_out]

    _add_minimum_bending_segment(
        matrix, rhs, hour_connector_point, guide_point,
        safe_hour_span, hour_start, hour_end,
    )
    _add_minimum_bending_segment(
        matrix, rhs, guide_point, minute_connector_point,
        safe_minute_span, minute_start, minute_end,
    )
    for i in range(4):
        matrix[i][i] += SOLVER_REGULARIZATION

    solution = solve_augmented_system_4x4(matrix, rhs)
    if solution is None:
        return (
            scale(hour_radial_in, 0.5),
            unit(sub(minute_connector_point, hour_connector_point)),
            scale(minute_radial_out, 0.5),
            False,
        )

    return (
        scale(hour_radial_in, max(solution[0], 0.0)),
        (solution[1], solution[2]),
        scale(minute_radial_out, max(solution[3], 0.0)),
        True,
    )


# ---------------------------------------------------------------------------
# Cubic Hermite sampling (src/c/main.c:893)
# ---------------------------------------------------------------------------

def hermite(
    start_point: Vec, end_point: Vec,
    start_derivative: Vec, end_derivative: Vec,
    parameter_length: float, amount: float,
) -> Vec:
    return hermite_jet(
        start_point, end_point, start_derivative, end_derivative,
        parameter_length, amount,
    )[0]


def hermite_jet(
    start_point: Vec, end_point: Vec,
    start_derivative: Vec, end_derivative: Vec,
    parameter_length: float, amount: float,
) -> tuple[Vec, Vec, Vec]:
    """Position, first and second derivative -- for analytic curvature."""
    t = clamp(amount, 0.0, 1.0)
    t2 = t * t
    t3 = t2 * t
    bases = (
        (2 * t3 - 3 * t2 + 1, t3 - 2 * t2 + t, -2 * t3 + 3 * t2, t3 - t2),
        (6 * t2 - 6 * t, 3 * t2 - 4 * t + 1, -6 * t2 + 6 * t, 3 * t2 - 2 * t),
        (12 * t - 6, 6 * t - 4, -12 * t + 6, 6 * t - 2),
    )
    controls = (
        start_point,
        scale(start_derivative, parameter_length),
        end_point,
        scale(end_derivative, parameter_length),
    )
    out = []
    for basis in bases:
        out.append(
            (
                sum(basis[i] * controls[i][0] for i in range(4)),
                sum(basis[i] * controls[i][1] for i in range(4)),
            )
        )
    return out[0], out[1], out[2]


def curvature(
    start_point: Vec, end_point: Vec,
    start_derivative: Vec, end_derivative: Vec,
    parameter_length: float, amount: float,
) -> float:
    _, first, second = hermite_jet(
        start_point, end_point, start_derivative, end_derivative,
        parameter_length, amount,
    )
    speed = norm(first)
    if speed < 1e-9:
        return 0.0
    return cross(first, second) / speed ** 3


# ---------------------------------------------------------------------------
# Pivot candidates
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PivotContext:
    """Everything a pivot rule may legitimately depend on."""

    center: Vec
    max_radius: float
    hour_radial: Vec          # unit vector, centre -> hour tip
    minute_radial: Vec        # unit vector, centre -> minute tip
    hour_point: Vec           # A: inner end of the hour stem
    minute_point: Vec         # B: inner end of the minute stem
    hour_inner: float         # r_h, px
    minute_inner: float       # r_m, px
    hour_length: float        # L_h, px
    minute_length: float      # L_m, px
    radial_dot: float         # cos(delta)

    @property
    def hour_vector(self) -> Vec:
        return sub(self.hour_point, self.center)

    @property
    def minute_vector(self) -> Vec:
        return sub(self.minute_point, self.center)

    @property
    def half_cos(self) -> float:
        """cos(delta/2)."""
        return math.sqrt(max(0.0, (1.0 + self.radial_dot) * 0.5))

    @property
    def half_sin_squared(self) -> float:
        """sin^2(delta/2) -- the normalized 'openness' of the hands."""
        return max(0.0, (1.0 - self.radial_dot) * 0.5)

    @property
    def sin_separation(self) -> float:
        """|sin(delta)|."""
        return math.sqrt(max(0.0, 1.0 - self.radial_dot * self.radial_dot))

    @property
    def harmonic_inner(self) -> float:
        """H = 2 r_h r_m / (r_h + r_m)."""
        total = self.hour_inner + self.minute_inner
        if total < VECTOR_EPSILON:
            return 0.0
        return 2.0 * self.hour_inner * self.minute_inner / total

    @property
    def chord_ceiling(self) -> float:
        """Where the bisector meets chord AB: H cos(d/2).

        The tangent-triangle bound.  Correct for monotone turning, but far too
        permissive to prevent the curvature from flattening at the pivot -- see
        arc_apex_ceiling, which is the binding one.
        """
        return self.harmonic_inner * self.half_cos

    @property
    def arc_apex_ceiling(self) -> float:
        """The constant-curvature apex: min(r_h, r_m) * tan(pi/4 - d/4).

        The circle tangent to a stem's radial line at its inner end and centred
        on the bisector crosses the bisector at r * tan(pi/4 - d/4).  Tangency
        to both radials at unequal radii is impossible, so the *shorter* stem
        gives the smaller apex and therefore governs.

        Written as cos/(1 + sin) rather than (1 - sin)/cos: algebraically
        identical, but with no 0/0 at opposition, and it needs only square
        roots -- so a C port can use square_root_float() and skip atan.
        """
        return (min(self.hour_inner, self.minute_inner) * self.half_cos
                / (1.0 + self.half_sin))

    @property
    def half_sin(self) -> float:
        """sin(d/2)."""
        return math.sqrt(self.half_sin_squared)


PivotRule = Callable[[PivotContext], Vec]


def along_bisector(depth: Callable[[PivotContext, float], float]) -> PivotRule:
    """Offset from the centre along the hands' angle bisector by `depth`.

    `depth` receives the raw |u_h + u_m| alongside the context, because the
    current C rule uses it directly.
    """

    def rule(ctx: PivotContext) -> Vec:
        direction_sum = add(ctx.hour_radial, ctx.minute_radial)
        length = norm(direction_sum)
        if length < VECTOR_EPSILON:
            return ctx.center
        return add(ctx.center, scale(scale(direction_sum, 1.0 / length),
                                     depth(ctx, length)))

    return rule


def depth_tilt_family(
    mu: Callable[[PivotContext], float],
    beta: Callable[[PivotContext], float],
) -> PivotRule:
    """P = C + mu * ((1 - beta) * A + beta * B), with A, B relative to C.

    A convex combination of C, A and B whenever mu and beta are in [0, 1], so
    the pivot is inside the tangent triangle ABC by construction, and the whole
    family rescales linearly with the stem radii.

    `mu` sets the depth (how far from the centre toward the chord); `beta` sets
    the tilt (which stem end the pull leans toward).
    """

    def rule(ctx: PivotContext) -> Vec:
        m = mu(ctx)
        b = beta(ctx)
        pull = add(
            scale(ctx.hour_vector, (1.0 - b) * m),
            scale(ctx.minute_vector, b * m),
        )
        return add(ctx.center, pull)

    return rule


def mu_for_bisector_depth(
    depth: Callable[[PivotContext], float],
) -> Callable[[PivotContext], float]:
    """Express a target *depth along the bisector* as the family's `mu`.

    Lets a depth rule be combined with any tilt: on the bisector the family
    reaches mu * H * cos(d/2), so mu = depth / (H cos(d/2)).  Both H cos(d/2)
    and every depth rule here vanish together at opposition, and the ratio stays
    finite, so this is well behaved throughout.
    """

    def mu(ctx: PivotContext) -> float:
        ceiling = ctx.chord_ceiling
        if ceiling < VECTOR_EPSILON:
            return 0.0
        return depth(ctx) / ceiling

    return mu


# -- depth (mu) ------------------------------------------------------------

def mu_openness(ctx: PivotContext) -> float:
    """sin^2(delta/2) = (1 - u_h . u_m) / 2."""
    return ctx.half_sin_squared


def mu_openness_power(power: float) -> Callable[[PivotContext], float]:
    return lambda ctx: ctx.half_sin_squared ** power


# -- tilt (beta) -----------------------------------------------------------

def beta_bisector(ctx: PivotContext) -> float:
    """The tilt that lands exactly on the angle bisector.

    Equal weight on u_h and u_m requires (1-b) r_h = b r_m, hence
    b = r_h / (r_h + r_m) -- each stem end weighted by the *opposite* stem's
    radius.  The resulting depth along the bisector is H * cos(delta/2) * mu.
    """
    total = ctx.hour_inner + ctx.minute_inner
    return 0.5 if total < VECTOR_EPSILON else ctx.hour_inner / total


def beta_chord_midpoint(ctx: PivotContext) -> float:
    """Equal barycentric weight, i.e. aimed at the chord midpoint.  Leans
    toward whichever stem is longer."""
    return 0.5


def beta_hand_length(ctx: PivotContext) -> float:
    """Weighted by hand length rather than stem radius.  Leans toward the
    longer hand (0.60 with today's 0.60R / 0.90R hands)."""
    total = ctx.hour_length + ctx.minute_length
    return 0.5 if total < VECTOR_EPSILON else ctx.minute_length / total


def beta_perpendicular_foot(ctx: PivotContext) -> float:
    """Aimed at the closest point of chord AB to the centre.  Leans toward the
    shorter stem."""
    chord = sub(ctx.minute_point, ctx.hour_point)
    length_squared = dot(chord, chord)
    if length_squared < VECTOR_EPSILON:
        return 0.5
    return clamp(dot(sub(ctx.center, ctx.hour_point), chord) / length_squared,
                 0.0, 1.0)


def beta_fixed(value: float) -> Callable[[PivotContext], float]:
    return lambda ctx: value


# -- the shipped rule (src/c/main.c:419) ----------------------------------

def _shape_pivot_pull(raw_pull: float, bias: float = 0.50) -> float:
    x = clamp(raw_pull, 0.0, 1.0)
    return x * (1.0 + bias) / (1.0 + bias * x)


def _current_depth(ctx: PivotContext, direction_sum_length: float) -> float:
    shaped = _shape_pivot_pull(ctx.sin_separation)
    bisector_strength = math.sqrt(clamp(direction_sum_length * 0.5, 0.0, 1.0))
    return ctx.max_radius * 0.15 * shaped * bisector_strength


def scaled(rule: PivotRule, factor: float) -> PivotRule:
    def wrapped(ctx: PivotContext) -> Vec:
        return add(ctx.center, scale(sub(rule(ctx), ctx.center), factor))

    return wrapped


# -- round 2: depths measured against the arc-apex ceiling ----------------

def arc_depth(nu: Callable[[PivotContext], float]) -> Callable[[PivotContext], float]:
    """nu(d) * arc_apex_ceiling -- the round-2 depth family.

    nu must stay below 1: at full strength the ceiling itself flattens the
    curvature at the pivot (measured 91-95% dip), so it sets the right
    d-dependence but is not a safe bound on its own.
    """
    return lambda ctx: nu(ctx) * ctx.arc_apex_ceiling


def nu_half_sin(ctx: PivotContext) -> float:
    return ctx.half_sin


def nu_openness(ctx: PivotContext) -> float:
    return ctx.half_sin_squared


def nu_openness_power(power: float) -> Callable[[PivotContext], float]:
    return lambda ctx: ctx.half_sin_squared ** power


def nu_one(ctx: PivotContext) -> float:
    return 1.0


@dataclass(frozen=True)
class Candidate:
    key: str
    label: str
    formula: str
    rule: PivotRule
    role: str = "contender"   # contender | reference | baseline | illustration


CANDIDATES: tuple[Candidate, ...] = (
    Candidate(
        "c0-current", "C0 current", "0.15R * shape(sin d) * sqrt(cos(d/2))",
        along_bisector(_current_depth), role="reference",
    ),
    Candidate(
        "c1-openness", "C1 openness x ceiling", "mu=sin^2(d/2), beta=r_h/(r_h+r_m)",
        depth_tilt_family(mu_openness, beta_bisector),
    ),
    Candidate(
        "c1-openness-070", "C1 openness (0.70)", "C1 scaled by 0.70",
        scaled(depth_tilt_family(mu_openness, beta_bisector), 0.70),
    ),
    Candidate(
        "c2-clearance", "C2 branch clearance", "0.5 * min(r_h,r_m) * sin d",
        along_bisector(lambda ctx, _l: 0.5 * min(ctx.hour_inner, ctx.minute_inner)
                       * ctx.sin_separation),
    ),
    Candidate(
        "c3-chord-035", "C3 chord fraction", "0.35 * dist(C, line AB)",
        along_bisector(lambda ctx, _l: 0.35 * _chord_distance(ctx)),
    ),
    Candidate(
        "c4-openness-p05", "C4 openness^0.5", "mu=sin(d/2), beta=bisector",
        depth_tilt_family(mu_openness_power(0.5), beta_bisector),
    ),
    Candidate(
        "c4-openness-p20", "C4 openness^2", "mu=sin^4(d/2), beta=bisector",
        depth_tilt_family(mu_openness_power(2.0), beta_bisector),
    ),
    Candidate(
        "c5-centre", "C5 always centre", "s = 0",
        lambda ctx: ctx.center, role="baseline",
    ),
    Candidate(
        "c6-opposition-bow", "C6 opposition bow", "0.5 * H * sin(d/2)",
        along_bisector(lambda ctx, _l: 0.5 * ctx.harmonic_inner
                       * math.sqrt(ctx.half_sin_squared)),
        role="illustration",
    ),
    Candidate(
        "c7-chord-midpoint", "C7 chord midpoint", "mu=sin^2(d/2), beta=1/2",
        depth_tilt_family(mu_openness, beta_chord_midpoint),
    ),
    Candidate(
        "c8-hand-length", "C8 hand-length tilt", "mu=sin^2(d/2), beta=L_m/(L_h+L_m)",
        depth_tilt_family(mu_openness, beta_hand_length),
    ),
    Candidate(
        "c9-perp-foot", "C9 perpendicular foot", "mu=sin^2(d/2), beta=foot",
        depth_tilt_family(mu_openness, beta_perpendicular_foot),
    ),
)

#: Round 2.  Depth is measured against the arc-apex ceiling rather than the
#: chord, which is what keeps the curvature unimodal.
ROUND2: tuple[Candidate, ...] = (
    Candidate(
        "d1-arc-sin", "D1 arc x sin(d/2)",
        "nu=sin(d/2) x min(r) tan(45-d/4)",
        depth_tilt_family(mu_for_bisector_depth(arc_depth(nu_half_sin)),
                          beta_bisector),
    ),
    Candidate(
        "d2-arc-openness", "D2 arc x openness",
        "nu=sin^2(d/2) x min(r) tan(45-d/4)",
        depth_tilt_family(mu_for_bisector_depth(arc_depth(nu_openness)),
                          beta_bisector),
    ),
    Candidate(
        "d3-arc-p075", "D3 arc x openness^0.75",
        "nu=sin^1.5(d/2) x min(r) tan(45-d/4)",
        depth_tilt_family(
            mu_for_bisector_depth(arc_depth(nu_openness_power(0.75))),
            beta_bisector),
    ),
    Candidate(
        "dc-arc-ceiling", "DC the ceiling itself", "nu=1 -- flattens, by design",
        depth_tilt_family(mu_for_bisector_depth(arc_depth(nu_one)),
                          beta_bisector),
        role="illustration",
    ),
    Candidate(
        "c3-chord-035", "C3 chord fraction", "0.35 * dist(C, line AB)",
        along_bisector(lambda ctx, _l: 0.35 * _chord_distance(ctx)),
    ),
    Candidate(
        "c3o-chord-openness", "C3o chord x sin(d/2)",
        "0.30 * dist(C, line AB) * sin(d/2)",
        # 0.30 rather than 0.35: at 0.35 the worst headroom is 0.98, right on
        # the flattening threshold, which leaves nothing for a stem change.
        # 0.30 gives the same 0.84 margin as D1.
        along_bisector(lambda ctx, _l: 0.30 * _chord_distance(ctx) * ctx.half_sin),
    ),
    Candidate(
        "c0-current", "C0 current", "0.15R * shape(sin d) * sqrt(cos(d/2))",
        along_bisector(_current_depth), role="reference",
    ),
    Candidate(
        "c1-openness", "C1 round-1 lead", "mu=sin^2(d/2) vs the chord ceiling",
        depth_tilt_family(mu_openness, beta_bisector), role="illustration",
    ),
)

#: D1 with the tilt swept, to confirm beta does not induce flattening once the
#: depth is inside the limit.
ROUND2_TILT: tuple[Candidate, ...] = tuple(
    Candidate(
        f"d1-beta-{int(value * 100):03d}", f"beta = {value:.2f}",
        f"D1 depth, beta={value:.2f}",
        depth_tilt_family(mu_for_bisector_depth(arc_depth(nu_half_sin)),
                          beta_fixed(value)),
    )
    for value in (0.30, 0.40, 0.50, 0.60, 0.70)
)

CANDIDATES_BY_KEY = {candidate.key: candidate
                     for candidate in CANDIDATES + ROUND2}

#: C10 -- the tilt bracket, same depth, beta swept by hand.
TILT_SWEEP: tuple[Candidate, ...] = tuple(
    Candidate(
        f"c10-beta-{int(value * 100):03d}",
        f"beta = {value:.2f}",
        f"mu=sin^2(d/2), beta={value:.2f}",
        depth_tilt_family(mu_openness, beta_fixed(value)),
    )
    for value in (0.30, 0.40, 0.50, 0.60, 0.70)
)


def _chord_distance(ctx: PivotContext) -> float:
    """Perpendicular distance from the centre to the line through A and B."""
    chord = sub(ctx.minute_point, ctx.hour_point)
    length = norm(chord)
    if length < VECTOR_EPSILON:
        return 0.0
    return abs(cross(chord, sub(ctx.center, ctx.hour_point))) / length


# ---------------------------------------------------------------------------
# Centerline construction (src/c/main.c:1038)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Centerline:
    points: list[Vec]              # the faithful 49-point polyline
    hour_tip: Vec
    minute_tip: Vec
    hour_connector: Vec            # A
    minute_connector: Vec          # B
    pivot: Vec                     # P
    pivot_index: int
    hour_derivative: Vec
    guide_derivative: Vec
    minute_derivative: Vec
    hour_span: float
    minute_span: float
    solver_ok: bool
    context: PivotContext

    def hour_half(self, samples: int) -> list[tuple[Vec, Vec, Vec]]:
        return [
            hermite_jet(self.hour_connector, self.pivot, self.hour_derivative,
                        self.guide_derivative, self.hour_span, i / samples)
            for i in range(samples + 1)
        ]

    def minute_half(self, samples: int) -> list[tuple[Vec, Vec, Vec]]:
        return [
            hermite_jet(self.pivot, self.minute_connector, self.guide_derivative,
                        self.minute_derivative, self.minute_span, i / samples)
            for i in range(samples + 1)
        ]


def build_centerline(
    hours: int, minutes: int,
    rule: PivotRule,
    face: Face = Face(),
    stems: Stems = DEFAULT_STEMS,
) -> Centerline:
    center = face.center
    radius = face.max_radius

    hour_length = radius * stems.hour_length
    minute_length = radius * stems.minute_length

    hour_tip = point_on_clock(center, hour_to_pebble_angle(hours, minutes), hour_length)
    minute_tip = point_on_clock(center, minute_to_pebble_angle(minutes), minute_length)

    hour_radial = unit(sub(hour_tip, center))
    minute_radial = unit(sub(minute_tip, center))
    hour_radial_in = scale(hour_radial, -1.0)

    hour_inner = radius * stems.hour_inner
    minute_inner = radius * stems.minute_inner
    hour_connector = add(center, scale(hour_radial, hour_inner))
    minute_connector = add(center, scale(minute_radial, minute_inner))

    context = PivotContext(
        center=center,
        max_radius=radius,
        hour_radial=hour_radial,
        minute_radial=minute_radial,
        hour_point=hour_connector,
        minute_point=minute_connector,
        hour_inner=hour_inner,
        minute_inner=minute_inner,
        hour_length=hour_length,
        minute_length=minute_length,
        radial_dot=clamp(dot(hour_radial, minute_radial), -1.0, 1.0),
    )
    pivot = rule(context)

    hour_span = norm(sub(pivot, hour_connector))
    minute_span = norm(sub(minute_connector, pivot))
    safe_hour_span = safe_parameter_length(hour_span)
    safe_minute_span = safe_parameter_length(minute_span)

    total_span = hour_span + minute_span
    hour_fraction = hour_span / total_span if total_span > VECTOR_EPSILON else 0.5
    pivot_index = CONNECTOR_FIRST_INDEX + int(CONNECTOR_SEGMENTS * hour_fraction + 0.5)
    pivot_index = min(max(pivot_index, CONNECTOR_FIRST_INDEX + 2),
                      CONNECTOR_LAST_INDEX - 2)

    hour_derivative, guide_derivative, minute_derivative, solver_ok = (
        calculate_minimum_bending_derivatives(
            hour_connector, pivot, minute_connector,
            hour_radial_in, minute_radial,
            safe_hour_span, safe_minute_span,
        )
    )

    points: list[Vec] = [(0.0, 0.0)] * CENTERLINE_POINT_COUNT
    for i in range(CONNECTOR_FIRST_INDEX + 1):
        amount = i / HOUR_STEM_SEGMENTS
        points[i] = add(hour_tip, scale(sub(hour_connector, hour_tip), amount))
    for i in range(CONNECTOR_LAST_INDEX, CENTERLINE_POINT_COUNT):
        amount = (i - CONNECTOR_LAST_INDEX) / MINUTE_STEM_SEGMENTS
        points[i] = add(minute_connector,
                        scale(sub(minute_tip, minute_connector), amount))

    first_count = pivot_index - CONNECTOR_FIRST_INDEX
    for i in range(CONNECTOR_FIRST_INDEX, pivot_index + 1):
        points[i] = hermite(
            hour_connector, pivot, hour_derivative, guide_derivative,
            safe_hour_span, (i - CONNECTOR_FIRST_INDEX) / first_count,
        )
    second_count = CONNECTOR_LAST_INDEX - pivot_index
    for i in range(pivot_index, CONNECTOR_LAST_INDEX + 1):
        points[i] = hermite(
            pivot, minute_connector, guide_derivative, minute_derivative,
            safe_minute_span, (i - pivot_index) / second_count,
        )

    return Centerline(
        points=points,
        hour_tip=hour_tip,
        minute_tip=minute_tip,
        hour_connector=hour_connector,
        minute_connector=minute_connector,
        pivot=pivot,
        pivot_index=pivot_index,
        hour_derivative=hour_derivative,
        guide_derivative=guide_derivative,
        minute_derivative=minute_derivative,
        hour_span=safe_hour_span,
        minute_span=safe_minute_span,
        solver_ok=solver_ok,
        context=context,
    )


ALL_TIMES: tuple[tuple[int, int], ...] = tuple(
    (hour, minute) for hour in range(12) for minute in range(60)
)
