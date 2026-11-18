#!/usr/bin/env python3
"""Width profiles as data, so the envelope can be explored without editing main.c.

    python3 tools/preview/profiles.py     # verifies `shipped` against the C

The watchface assembles its stroke width from four separate mechanisms -- an
hour-side contraction, a minute-side taper, a waist override near overlap, and a
pressure multiplier over the top. They are all the same thing: one function
w(s) from the hour body to the minute point. This module expresses that function
directly, as a width per centerline sample, so alternatives are values rather
than patches.

`shipped` reproduces `calculate_stroke_width` exactly and is the control: nothing
else here is trustworthy unless it renders pixel-identically to the compiled C.
`check()` asserts that over all 720 minutes.

Two facts from docs/pivot-design.md that bound everything in here:

  * every polygon vertex is rounded to an integer, and across 49 samples only
    ~10 distinct widths survive, so two profiles agreeing to within ~0.3 px at
    the sample points are the *same drawing*;
  * on the minute side the filled polygon is already below 1 px over the outer
    ~46 px of arc, where `gpath` drops the span entirely, so profile detail down
    there reaches the outline and the core but not the fill.
"""
from __future__ import annotations

import math
import os
import sys
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import raster
import sheet_envelope

#: `shipped` below transcribes main.c as it was before the quadratic replaced
#: its width code, and every study here compares against that code, so they all
#: build it. The current main.c is checked separately, against `quadratic`.
LEGACY_SOURCE = sheet_envelope.main_c_at(sheet_envelope.LEGACY)

# --- the constants the profile runs between, read from main.c ---------------

MAIN_C = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "..", "..", "src", "c", "main.c")


#: Constants both versions of main.c have; they must still agree, or the
#: studies of the legacy code no longer describe the current one.
SHARED = ("HOUR_TIP_WIDTH", "HOUR_BODY_WIDTH", "MINUTE_TIP_WIDTH",
          "HOUR_SWELL_POSITION", "OUTLINE_WIDTH_COMPENSATION", "VECTOR_EPSILON")


def read_defines(source, wanted):
    import re
    out = {}
    for name in wanted:
        match = re.search(r"^#define[ \t]+" + name + r"[ \t]+([0-9.]+)f?\s*$",
                          source, re.MULTILINE)
        if not match:
            raise SystemExit(f"could not read #define {name} from main.c")
        out[name] = float(match.group(1))
    return out


def constants():
    """The width-related #defines, so this file cannot drift from the C.

    Read from the legacy main.c, which is the only one that still has
    MIDDLE_WIDTH, MINIMUM_STROKE_WIDTH and PRESSURE_VARIATION.
    """
    out = read_defines(LEGACY_SOURCE, SHARED + (
        "MIDDLE_WIDTH", "MINIMUM_STROKE_WIDTH", "PRESSURE_VARIATION"))
    current = read_defines(open(MAIN_C).read(), SHARED)
    for name in SHARED:
        if current[name] != out[name]:
            raise SystemExit(f"{name} differs between main.c and {sheet_envelope.LEGACY}")
    return out


K = constants()


# --- the widths a profile runs between --------------------------------------

@dataclass(frozen=True)
class Widths:
    """The width constants of one configuration, as main.c names them.

    Defaults to what main.c ships. A different record stands for main.c compiled
    with those constants overridden, and `overrides()` is exactly that set of
    overrides, so a profile and the C it is checked against cannot disagree
    about which configuration they are.
    """
    hour_tip: float = K["HOUR_TIP_WIDTH"]
    peak: float = K["HOUR_BODY_WIDTH"]
    mid: float = K["MIDDLE_WIDTH"]
    tip: float = K["MINUTE_TIP_WIDTH"]
    swell: float = K["HOUR_SWELL_POSITION"]

    @classmethod
    def for_body(cls, body):
        """The hour end scaled with the body: same shape at every thickness.

        Tip and control value stay at half the body, and the widening keeps its
        length in proportion to the width it has to reach.
        """
        scale = body / K["HOUR_BODY_WIDTH"]
        return cls(hour_tip=K["HOUR_TIP_WIDTH"] * scale, peak=body,
                   mid=K["MIDDLE_WIDTH"] * scale,
                   swell=K["HOUR_SWELL_POSITION"] * scale)

    def overrides(self):
        return {"HOUR_TIP_WIDTH": f"{self.hour_tip!r}f",
                "HOUR_BODY_WIDTH": f"{self.peak!r}f",
                "MIDDLE_WIDTH": f"{self.mid!r}f",
                "MINUTE_TIP_WIDTH": f"{self.tip!r}f",
                "HOUR_SWELL_POSITION": f"{self.swell!r}f"}


SHIPPED_WIDTHS = Widths()


# --- the context a profile is evaluated against -----------------------------

@dataclass
class Context:
    """Everything a profile may depend on, for one rendered frame."""
    arc: list          # cumulative arc length at each of the 49 samples
    total: float       # arc[-1]
    pivot: int         # index of the pivot sample
    waist_opening: float   # 0..1, the shipped near-overlap waist term
    separation: float      # degrees between the hands
    points: list           # centerline points, for curvature-aware profiles
    widths: Widths = SHIPPED_WIDTHS

    @property
    def pivot_position(self):
        return self.arc[self.pivot] / self.total if self.total else 0.0

    def position(self, index):
        return self.arc[index] / self.total if self.total else 0.0

    @property
    def middle_width(self):
        """What the shipped code calls effective_middle_width."""
        return lerp(K["MINIMUM_STROKE_WIDTH"], self.widths.mid,
                    smooth_unit(self.waist_opening))


def context_from(frame, separation, widths=SHIPPED_WIDTHS):
    # arc length comes from the C's own s_cumulative_length rather than being
    # recomputed from the printed points: the profile is a function of it, so
    # re-deriving it would compare against a slightly different parameter.
    points = [(row[0], row[1]) for row in frame["centerline"]]
    arc = [row[4] for row in frame["centerline"]]
    return Context(arc=arc, total=arc[-1], pivot=frame["pivot"],
                   waist_opening=frame["scale"], separation=separation,
                   points=points, widths=widths)


# --- helpers, matching main.c's own -----------------------------------------

def clamp(value, low, high):
    return low if value < low else high if value > high else value


def lerp(a, b, t):
    return a + (b - a) * t


def smooth_unit(value):
    p = clamp(value, 0.0, 1.0)
    return p * p * (3.0 - 2.0 * p)


# --- the control ------------------------------------------------------------

def shipped(ctx, pressure=None):
    """`calculate_stroke_width` and the pressure bias, transcribed.

    Returns stroke width per sample, before OUTLINE_WIDTH_COMPENSATION.
    `pressure` overrides PRESSURE_VARIATION; 0.0 gives the bare two-segment
    profile with the multiplier taken off.
    """
    variation = K["PRESSURE_VARIATION"] if pressure is None else pressure
    k = ctx.widths
    widths = []
    pivot_position = ctx.pivot_position
    middle = ctx.middle_width
    for index in range(len(ctx.arc)):
        position = ctx.position(index)
        if position <= pivot_position:
            if pivot_position < K["VECTOR_EPSILON"]:
                width = middle
            else:
                hour = clamp(position / pivot_position, 0.0, 1.0)
                if hour <= k.swell:
                    swell = (hour / k.swell if k.swell > K["VECTOR_EPSILON"]
                             else 1.0)
                    width = lerp(k.hour_tip, k.peak, smooth_unit(swell))
                else:
                    contraction = (hour - k.swell) / (1.0 - k.swell)
                    width = lerp(k.peak, middle, smooth_unit(contraction))
        else:
            remaining = 1.0 - pivot_position
            if remaining < K["VECTOR_EPSILON"]:
                width = middle
            else:
                minute = clamp((position - pivot_position) / remaining, 0.0, 1.0)
                width = lerp(middle, k.tip, smooth_unit(minute))

        envelope = 4.0 * position * (1.0 - position)
        width *= 1.0 + variation * envelope * (pivot_position - position)
        widths.append(width)
    return widths


def to_polygon_widths(widths):
    """Apply OUTLINE_WIDTH_COMPENSATION exactly as build_stroke_polygon does."""
    c = K["OUTLINE_WIDTH_COMPENSATION"]
    return [w - c if w - c > 0.0 else 0.0 for w in widths]


# --- verification -----------------------------------------------------------

def separation_degrees(hour, minute):
    d = abs((30.0 * (hour % 12) + 0.5 * minute) - 6.0 * minute) % 360.0
    return min(d, 360.0 - d)


def check(times=None, verbose=True, overrides=None, widths=SHIPPED_WIDTHS):
    """`shipped` must reproduce the C's own widths, or nothing else here counts.

    With `overrides` and the `widths` they correspond to, the same holds for
    main.c compiled with other constants.
    """
    times = times or [(h, m) for h in range(12) for m in range(60)]
    frames = raster.gather(times=times, want_frames=False, overrides=overrides,
                           source=LEGACY_SOURCE)
    worst = 0.0
    worst_at = None
    for frame in frames:
        ctx = context_from(frame, separation_degrees(frame["hour"], frame["minute"]),
                           widths)
        mine = to_polygon_widths(shipped(ctx))
        theirs = [row[3] for row in frame["centerline"]]
        for a, b in zip(mine, theirs):
            if abs(a - b) > worst:
                worst = abs(a - b)
                worst_at = (frame["hour"], frame["minute"])
    if verbose:
        print(f"shipped profile vs the compiled C, {len(frames)} frames x "
              f"{len(frames[0]['centerline'])} samples")
        print(f"  worst width disagreement: {worst:.3e} px"
              + (f" at {worst_at[0] % 12 or 12:02d}:{worst_at[1]:02d}"
                 if worst_at else ""))
    return worst


# --- curvature, for the kink track ------------------------------------------

#: A dense reference for curvature. CENTERLINE_POINT_COUNT is hard-capped at
#: 255 by main.c's own #error, since pivot_index is a uint8_t, so this has to
#: stay under it: 16 + 180 + 16 + 1 = 213, giving ~0.5 px in the connector.
DENSE = {"HOUR_STEM_SEGMENTS": "16", "CONNECTOR_SEGMENTS": "180",
         "MINUTE_STEM_SEGMENTS": "16"}


def radius_at_samples(ctx, dense_frame):
    """Radius of curvature at each coarse sample, from a dense reference.

    A three-point circumradius on the 49 shipped samples is meaningless near the
    kink, where the points are 3 px apart and the curve turns inside that. The
    dense frame samples the same curve at ~0.45 px, so the same estimator is
    sound there; it is evaluated at the coarse samples' own arc positions.
    """
    dp = [(row[0], row[1]) for row in dense_frame["centerline"]]
    da = [row[4] for row in dense_frame["centerline"]]

    def radius(i):
        """Arc step over turn angle.

        A circumradius through three points cannot see a reversal: at exact hand
        overlap the centerline runs in along a ray and back out along the same
        ray, so the three points are collinear and the circumradius reads large
        precisely where the curve is sharpest. Turn angle per unit arc does not
        have that blind spot -- a reversal is a turn of pi.
        """
        (ax, ay), (bx, by), (cx, cy) = dp[i - 1], dp[i], dp[i + 1]
        ux, uy = bx - ax, by - ay
        vx, vy = cx - bx, cy - by
        lu, lv = math.hypot(ux, uy), math.hypot(vx, vy)
        if lu < 1e-9 or lv < 1e-9:
            return float("inf")
        cross = (ux * vy - uy * vx) / (lu * lv)
        dot = (ux * vx + uy * vy) / (lu * lv)
        turn = abs(math.atan2(cross, dot))
        if turn < 1e-9:
            return float("inf")
        return 0.5 * (lu + lv) / turn

    # Each coarse sample owns the arc interval halfway to its neighbours, and
    # takes the SHARPEST curvature in it. Point-sampling at the sample position
    # is not good enough: at exact overlap the centerline reverses 0.068 px past
    # the pivot, between two samples 3 px apart, so the point value reads
    # R = 94.7 where the true answer is R = 0.003.
    radii = []
    n = len(ctx.arc)
    for i, target in enumerate(ctx.arc):
        lo = target if i == 0 else 0.5 * (ctx.arc[i - 1] + target)
        hi = target if i == n - 1 else 0.5 * (target + ctx.arc[i + 1])
        worst = float("inf")
        for k in range(1, len(dp) - 1):
            if lo - 1e-9 <= da[k] <= hi + 1e-9:
                worst = min(worst, radius(k))
        if worst == float("inf"):
            j = min(range(1, len(dp) - 1), key=lambda k: abs(da[k] - target))
            worst = radius(j)
        radii.append(worst)
    return radii


# --- track 1: what to do at the kink ----------------------------------------

def _base(ctx, waist_opening, pressure=None):
    """The shipped profile with the waist term forced to a given opening."""
    saved = ctx.waist_opening
    ctx.waist_opening = waist_opening
    try:
        return shipped(ctx, pressure)
    finally:
        ctx.waist_opening = saved


def no_thinning(ctx, dense=None):
    """The waist never closes: MIDDLE_WIDTH straight through the fold."""
    return _base(ctx, 1.0)


def thinning_band(scale):
    """The shipped rule with its band widened (scale > 1) or narrowed."""
    def profile(ctx, dense=None):
        return _base(ctx, clamp(ctx.waist_opening / scale, 0.0, 1.0))
    profile.__name__ = f"band_x{scale:g}"
    return profile


def thinning_floor(floor):
    """The shipped rule, but the waist bottoms out at `floor` px, not 1 px."""
    def profile(ctx, dense=None):
        t = smooth_unit(ctx.waist_opening)
        middle = lerp(floor, ctx.widths.mid, t)
        saved = ctx.waist_opening
        # solve for the opening that yields this middle through the shipped path
        lo, hi = 0.0, 1.0
        for _ in range(40):
            mid = 0.5 * (lo + hi)
            ctx.waist_opening = mid
            if ctx.middle_width < middle:
                lo = mid
            else:
                hi = mid
        try:
            return shipped(ctx)
        finally:
            ctx.waist_opening = saved
    profile.__name__ = f"floor{floor:g}"
    return profile


def curvature_capped(ctx, dense=None):
    """No band and no special case: hold w <= 2R everywhere.

    2R is exactly the condition for the inner offset not to cusp, so this is the
    principled version of what the separation term approximates -- and unlike the
    separation term it is a property of the curve rather than of the clock.
    """
    widths = no_thinning(ctx)
    if dense is None:
        return widths
    radii = radius_at_samples(ctx, dense)
    # Floored at MINIMUM_STROKE_WIDTH: at a true reversal R -> 0, so an
    # unfloored 2R would collapse the stroke to nothing at exactly the fold the
    # design wants to keep. The shipped waist term has the same floor.
    floor = K["MINIMUM_STROKE_WIDTH"]
    return [max(floor, min(w, 2.0 * r)) for w, r in zip(widths, radii)]


def curvature_spread(spread_px):
    """`w <= 2R`, but with R taken as the sharpest within +/-`spread_px` of arc.

    The unspread rule finds the right place and then thins exactly one sample
    out of 49, which is why it renders like no-thinning at all at overlap: a
    single-sample notch is not a visible narrowing. Spreading the cap over a
    neighbourhood is what turns a correct diagnosis into a visible treatment.
    """
    def profile(ctx, dense=None):
        widths = no_thinning(ctx)
        if dense is None:
            return widths
        radii = radius_at_samples(ctx, dense)
        floor = K["MINIMUM_STROKE_WIDTH"]
        out = []
        for i, w in enumerate(widths):
            nearby = [radii[j] for j in range(len(radii))
                      if abs(ctx.arc[j] - ctx.arc[i]) <= spread_px]
            cap = 2.0 * min(nearby) if nearby else float("inf")
            out.append(max(floor, min(w, cap)))
        return out
    profile.__name__ = f"curvature_spread{spread_px:g}"
    return profile


TRACK1 = (
    ("shipped", lambda ctx, dense=None: shipped(ctx)),
    ("no thinning at all", no_thinning),
    ("band x2 (thins further out)", thinning_band(2.0)),
    ("band x0.5 (thins only very close)", thinning_band(0.5)),
    ("floor 2 px instead of 1", thinning_floor(2.0)),
    ("curvature rule, w <= 2R", curvature_capped),
    ("curvature, spread +/-4 px", curvature_spread(4.0)),
)


# --- tracks 2 and 3: the profile itself, on a no-thinning baseline ----------
#
# Thinning exists to keep the pivot from reading as a broad blob, which makes it
# a statement about w at the pivot -- the thing track 2 varies -- rather than a
# mechanism of its own. So both tracks run with the waist held open, and the
# near-overlap columns are kept on every sheet to show whether the pivot value a
# profile lands on needs help once the hands close.
#
# The domain is from the end of the hour swell to the minute point. The swell is
# the defined hour part and is reproduced exactly as shipped in every variant.

def domain(ctx):
    """(arc where the swell ends, arc span of the domain, pivot's place in it)."""
    start = ctx.widths.swell * ctx.arc[ctx.pivot]
    span = ctx.total - start
    return start, span, (ctx.arc[ctx.pivot] - start) / span


def from_shape(shape, name=None):
    """Lift w(u, u_pivot, span_px, widths) on the domain to a width per sample.

    u runs 0 at the swell's peak to 1 at the minute point; u_pivot is where the
    pivot falls in that parameter, which is NOT one half and moves with the time.
    `widths` is the configuration's Widths, so one shape serves every thickness.
    """
    def profile(ctx, dense=None):
        start, span, u_pivot = domain(ctx)
        k = ctx.widths
        widths = []
        for a in ctx.arc:
            if a <= start:
                t = a / start if start > K["VECTOR_EPSILON"] else 1.0
                widths.append(lerp(k.hour_tip, k.peak, smooth_unit(t)))
            else:
                widths.append(shape((a - start) / span, u_pivot, span, k))
        return widths
    if name:
        profile.__name__ = name
    return profile


def two_smoothstep(mid=None, at=None):
    """Peak -> `mid` -> point in two smoothsteps: the shipped shape.

    `mid` defaults to the configuration's MIDDLE_WIDTH. `at` places the control
    value at a fixed fraction of the domain instead of at the pivot. With both
    left alone this is exactly the shipped profile with the waist open and the
    pressure multiplier off.
    """
    def shape(u, u_pivot, span, k):
        m = k.mid if mid is None else mid
        c = u_pivot if at is None else at
        if u <= c:
            return lerp(k.peak, m, smooth_unit(u / c))
        return lerp(m, k.tip, smooth_unit((u - c) / (1.0 - c)))
    return shape


def single_smoothstep(u, u_pivot, span, k):
    """Peak -> point in one smoothstep. No control value: MIDDLE_WIDTH's null."""
    return lerp(k.peak, k.tip, smooth_unit(u))


def hold_then_reduce(hold_px):
    """Full width for `hold_px` of arc, then one smoothstep down to the point."""
    def shape(u, u_pivot, span, k):
        h = min(hold_px / span, 0.95)
        if u <= h:
            return k.peak
        return lerp(k.peak, k.tip, smooth_unit((u - h) / (1.0 - h)))
    return shape


def power(p):
    """w = tip + (peak - tip)(1 - u)^p. p = 1 is a straight taper."""
    def shape(u, u_pivot, span, k):
        return k.tip + (k.peak - k.tip) * (1.0 - u) ** p
    return shape


def circular(u, u_pivot, span, k):
    """Quarter-ellipse: holds width, then closes round at the point."""
    return k.tip + (k.peak - k.tip) * math.sqrt(max(0.0, 1.0 - u * u))


BASELINE_SHAPE = two_smoothstep()
baseline = from_shape(BASELINE_SHAPE, "baseline")

#: w = tip + (peak - tip)(1 - u)^2: no control value, and no knowledge of where
#: the pivot is. What it puts at the pivot is whatever the geometry gives it.
quadratic = from_shape(power(2.0), "quadratic")


def skewed(a, b):
    """w = tip + (peak - tip)(1 - u^a)^b: the quadratic, skewed along the stroke.

    a = 1, b = 2 is the quadratic itself. a > 1 holds the width longer and then
    drops it; a < 1 drops early and trails. Like the quadratic it never looks at
    the pivot.
    """
    def shape(u, u_pivot, span, k):
        return k.tip + (k.peak - k.tip) * (1.0 - u ** a) ** b
    return shape


def split_at_pivot(a, b):
    """A different fall either side of the pivot, meeting at the quadratic's own
    pivot width, so nothing new is pinned there.

    Hour side: w_p + (peak - w_p)(1 - s)^a over s = u / u_pivot.
    Minute side: tip + (w_p - tip)(1 - t)^b over t from the pivot to the point.
    """
    def shape(u, u_pivot, span, k):
        w_p = k.tip + (k.peak - k.tip) * (1.0 - u_pivot) ** 2
        if u <= u_pivot:
            return w_p + (k.peak - w_p) * (1.0 - u / u_pivot) ** a
        t = (u - u_pivot) / (1.0 - u_pivot)
        return k.tip + (w_p - k.tip) * (1.0 - t) ** b
    return shape


def reference(ctx, dense=None):
    """The watchface as drawn today: waist term and pressure both on."""
    return shipped(ctx)


def raised_cosine(distance, half_width):
    if abs(distance) >= half_width:
        return 0.0
    return 0.5 * (1.0 + math.cos(math.pi * distance / half_width))


def with_bumps(*bumps):
    """The baseline plus raised-cosine bumps placed in px of arc from the pivot.

    Each bump is (centre_px, half_width_px, amount_px); centre is signed, so
    negative sits on the hour side. Floored at MINIMUM_STROKE_WIDTH.
    """
    def shape(u, u_pivot, span, k):
        w = BASELINE_SHAPE(u, u_pivot, span, k)
        from_pivot = (u - u_pivot) * span
        for centre, half_width, amount in bumps:
            w += amount * raised_cosine(from_pivot - centre, half_width)
        return max(K["MINIMUM_STROKE_WIDTH"], w)
    return shape


def split_power(p_hour, p_minute, mid=None):
    """A different exponent either side of the pivot, meeting at `mid`."""
    def shape(u, u_pivot, span, k):
        m = k.mid if mid is None else mid
        if u <= u_pivot:
            return m + (k.peak - m) * (1.0 - u / u_pivot) ** p_hour
        t = (u - u_pivot) / (1.0 - u_pivot)
        return k.tip + (m - k.tip) * (1.0 - t) ** p_minute
    return shape


def pressured(variation):
    """The baseline under the shipped pressure multiplier at a given strength.

    pressured(PRESSURE_VARIATION) is the shipped profile with only the waist
    removed; it is the null case for the whole of track 3.
    """
    def profile(ctx, dense=None):
        return _base(ctx, 1.0, variation)
    profile.__name__ = f"pressured{variation:g}"
    return profile


def pressure_as_profile(amount_px):
    """The pressure idea as a shape, in pixels rather than as a percentage.

    The shipped multiplier follows 4p(1-p)(p_pivot - p): heavier before the
    pivot, lighter after. At 0.20 that peaks near 0.15 px, under the ~0.3 px a
    drawn width can resolve, which is why it reads as jitter. Here the same
    curve is added, scaled so its larger lobe is `amount_px`.
    """
    def profile(ctx, dense=None):
        widths = baseline(ctx)
        start, _, _ = domain(ctx)
        pp = ctx.pivot_position

        def lobe(p):
            return 4.0 * p * (1.0 - p) * (pp - p)
        scale = max(abs(lobe(i / 400.0)) for i in range(401)) or 1.0
        out = []
        for index, w in enumerate(widths):
            if ctx.arc[index] > start:
                w += amount_px * lobe(ctx.position(index)) / scale
            out.append(max(K["MINIMUM_STROKE_WIDTH"], w))
        return out
    profile.__name__ = f"pressure_profile{amount_px:g}"
    return profile


TRACK2_CONTROL = (
    ("shipped, as drawn today", reference),
    ("baseline: 6 -> 3 at pivot -> 1", baseline),
    ("pivot value 2 px", from_shape(two_smoothstep(2.0))),
    ("pivot value 2.5 px", from_shape(two_smoothstep(2.5))),
    ("pivot value 4 px", from_shape(two_smoothstep(4.0))),
    ("NO control value: one smoothstep", from_shape(single_smoothstep)),
    ("3 px at the arc midpoint, not the pivot", from_shape(two_smoothstep(3.0, 0.5))),
    ("3 px at one third of the arc", from_shape(two_smoothstep(3.0, 1.0 / 3.0))),
)

TRACK2_SHAPE = (
    ("shipped, as drawn today", reference),
    ("baseline: 6 -> 3 at pivot -> 1", baseline),
    ("one smoothstep (hold 0)", from_shape(single_smoothstep)),
    ("hold 10 px, then smoothstep", from_shape(hold_then_reduce(10.0))),
    ("hold 20 px, then smoothstep", from_shape(hold_then_reduce(20.0))),
    ("hold 30 px, then smoothstep", from_shape(hold_then_reduce(30.0))),
    ("linear taper", from_shape(power(1.0))),
    ("power 0.5 (stays wide, closes late)", from_shape(power(0.5))),
    ("power 2 (falls early, long thin tail)", quadratic),
    ("power 3", from_shape(power(3.0))),
    ("quarter ellipse", from_shape(circular)),
)

TRACK3 = (
    ("shipped, as drawn today", reference),
    ("baseline: 6 -> 3 at pivot -> 1", baseline),
    ("pressure x0.20 (shipped strength)", pressured(K["PRESSURE_VARIATION"])),
    ("pressure as a shape, 1 px lobe", pressure_as_profile(1.0)),
    ("bulge +1 px, 12 px past the pivot", from_shape(with_bumps((12.0, 12.0, 1.0)))),
    ("bulge +2 px, 12 px past the pivot", from_shape(with_bumps((12.0, 12.0, 2.0)))),
    ("pinch -1.5 px, 8 px before the pivot", from_shape(with_bumps((-8.0, 8.0, -1.5)))),
    ("pinch before, bulge after", from_shape(with_bumps((-8.0, 8.0, -1.5),
                                                        (12.0, 12.0, 1.5)))),
    ("hour falls fast, minute holds", from_shape(split_power(2.5, 0.5))),
    ("hour holds, minute falls fast", from_shape(split_power(0.5, 2.5))),
)

#: Every exponent here is a multiple of 0.5: on the watch that is products and at
#: most one square_root_float, where an arbitrary one would need powf.
EXPONENT = (
    ("shipped, as drawn today", reference),
    ("quadratic, p = 2", quadratic),
    ("p = 1.5 (lifts later)", from_shape(power(1.5))),
    ("p = 2.5 (lifts sooner)", from_shape(power(2.5))),
    ("p = 3", from_shape(power(3.0))),
)

ASYMMETRIC = (
    ("shipped, as drawn today", reference),
    ("quadratic, p = 2", quadratic),
    ("skew a = 0.5: drops early, long trail", from_shape(skewed(0.5, 2.0))),
    ("skew a = 1.5: holds, then drops", from_shape(skewed(1.5, 2.0))),
    ("skew a = 2: holds longer", from_shape(skewed(2.0, 2.0))),
    ("pivot split 2 / 1.5: eases in, minute heavier",
     from_shape(split_at_pivot(2.0, 1.5))),
    ("pivot split 1 / 3: straight in, minute lifts fast",
     from_shape(split_at_pivot(1.0, 3.0))),
)


# --- envelopes asymmetric about the centerline ------------------------------
#
# The quadratic fixes how wide the stroke is; these decide where that width
# sits. A split k in [-1, 1] per sample puts the +normal edge (the C's "left",
# centerline + normal * half) at pw (1 + k) / 2 and the other at pw (1 - k) / 2,
# pw being the polygon width. k = 0 is the centred stroke; k = +-1 puts one edge
# on the centerline. The total width is untouched, so the profile is still the
# quadratic. The minute core stays on the centerline: it marks where the hand
# points.

@dataclass
class Envelope:
    widths: list    # stroke width per sample, as a plain profile returns
    split: list     # k per sample


def _normals(ctx):
    import sheet_workshop as W
    return [(-ty, tx) for tx, ty in W.bisector_tangents(ctx.points)]


def _connector(ctx):
    """Arc positions of the connector's two ends, read from main.c's layout."""
    counts = read_defines(open(MAIN_C).read(),
                          ("HOUR_STEM_SEGMENTS", "CONNECTOR_SEGMENTS"))
    first = int(counts["HOUR_STEM_SEGMENTS"])
    last = first + int(counts["CONNECTOR_SEGMENTS"])
    return ctx.arc[first], ctx.arc[last], first, last


def turning(ctx):
    """Signed total turn of the connector, in radians, in the +normal sense.

    Positive means the tangent rotates towards +normal, so +normal is the inside
    of the bend. A straight stroke (06:00) is 0; a full reversal is +-pi.
    """
    _, _, first, last = _connector(ctx)
    total = 0.0
    p = ctx.points
    for i in range(first + 1, last + 1):
        ux, uy = p[i][0] - p[i - 1][0], p[i][1] - p[i - 1][1]
        vx, vy = p[i + 1][0] - p[i][0], p[i + 1][1] - p[i][1]
        if math.hypot(ux, uy) < 1e-9 or math.hypot(vx, vy) < 1e-9:
            continue
        total += math.atan2(ux * vy - uy * vx, ux * vx + uy * vy)
    return total


def outside_of_bend(k0):
    """Extra width on the outside of the turn, strongest at the pivot.

    k = -k0 * g(s) * turn / pi: zero on a straight stroke, largest at a full
    reversal, and g fades from 1 at the pivot to 0 at both ends of the connector
    so the straight stems stay centred.
    """
    def profile(ctx, dense=None):
        widths = quadratic(ctx)
        s0, s1, _, _ = _connector(ctx)
        sp = ctx.arc[ctx.pivot]
        strength = -k0 * turning(ctx) / math.pi
        split = []
        for a in ctx.arc:
            if s0 < a <= sp:
                g = smooth_unit((a - s0) / (sp - s0)) if sp > s0 else 1.0
            elif sp < a < s1:
                g = smooth_unit((s1 - a) / (s1 - sp)) if s1 > sp else 1.0
            else:
                g = 0.0
            split.append(clamp(strength * g, -1.0, 1.0))
        return Envelope(widths, split)
    profile.__name__ = f"outside_of_bend{k0:g}"
    return profile


def spine(k0):
    """The same share on the same side of travel along the whole stroke."""
    def profile(ctx, dense=None):
        widths = quadratic(ctx)
        return Envelope(widths, [k0] * len(widths))
    profile.__name__ = f"spine{k0:g}"
    return profile


#: Lower right on screen (y grows downwards).
LIGHT = (math.sqrt(0.5), math.sqrt(0.5))


def screen_direction(k0, towards=LIGHT):
    """The heavier edge always faces `towards` on screen: k = k0 (n . L)."""
    def profile(ctx, dense=None):
        widths = quadratic(ctx)
        split = [clamp(k0 * (nx * towards[0] + ny * towards[1]), -1.0, 1.0)
                 for nx, ny in _normals(ctx)]
        return Envelope(widths, split)
    profile.__name__ = f"screen_direction{k0:g}"
    return profile


CENTERLINE = (
    ("quadratic, centred (as shipped now)", quadratic),
    ("outside of the bend, k = 0.5", outside_of_bend(0.5)),
    ("outside of the bend, k = 1", outside_of_bend(1.0)),
    ("spine: one side of travel, k = 0.5", spine(0.5)),
    ("spine: one side of travel, k = 1", spine(1.0)),
    ("faces lower right on screen, k = 0.5", screen_direction(0.5)),
    ("faces lower right on screen, k = 1", screen_direction(1.0)),
)


def check_families(times=None, verbose=True):
    """The new families must reduce to the shipped maths where they claim to."""
    times = times or [(h, m) for h in range(12) for m in range(0, 60, 7)]
    frames = raster.gather(times=times, want_frames=False, source=LEGACY_SOURCE)
    worst_baseline = worst_pressured = worst_skew = worst_split = 0.0
    skew_unit = from_shape(skewed(1.0, 2.0))
    for frame in frames:
        ctx = context_from(frame, separation_degrees(frame["hour"], frame["minute"]))
        bare = _base(ctx, 1.0, 0.0)
        worst_baseline = max(worst_baseline, max(
            abs(a - b) for a, b in zip(baseline(ctx), bare)))
        worst_pressured = max(worst_pressured, max(
            abs(a - b) for a, b in
            zip(pressured(K["PRESSURE_VARIATION"])(ctx), no_thinning(ctx))))
        worst_skew = max(worst_skew, max(
            abs(a - b) for a, b in zip(skew_unit(ctx), quadratic(ctx))))
        _, span, u_pivot = domain(ctx)
        for a, b in ((2.0, 1.5), (1.0, 3.0)):
            shape = split_at_pivot(a, b)
            worst_split = max(worst_split, abs(
                shape(u_pivot, u_pivot, span, ctx.widths)
                - shape(u_pivot + 1e-12, u_pivot, span, ctx.widths)))
    if verbose:
        print(f"families vs the shipped maths, {len(frames)} frames")
        print(f"  baseline vs shipped with waist open, pressure off: "
              f"{worst_baseline:.3e} px")
        print(f"  pressured(0.20) vs shipped with waist open:        "
              f"{worst_pressured:.3e} px")
        print(f"  skewed(1, 2) vs quadratic:                         "
              f"{worst_skew:.3e} px")
        print(f"  split_at_pivot, jump across the pivot:             "
              f"{worst_split:.3e} px")
    return max(worst_baseline, worst_pressured, worst_skew, worst_split)


def check_current(verbose=True):
    """The current main.c must draw exactly `quadratic`: widths and pixels.

    Returns (worst width disagreement, minutes rendered identically).
    """
    import sheet_workshop as W
    times = [(h, m) for h in range(12) for m in range(60)]
    frames = raster.gather(times=times)
    worst, specs = 0.0, []
    for frame in frames:
        ctx = context_from(frame, separation_degrees(frame["hour"], frame["minute"]))
        mine = to_polygon_widths(quadratic(ctx))
        theirs = [row[3] for row in frame["centerline"]]
        worst = max(worst, max(abs(a - b) for a, b in zip(mine, theirs)))
        points = [(x, y) for x, y, *_ in frame["centerline"]]
        specs.append((W.polygon_from(points, mine, W.bisector_tangents(points)),
                      points[frame["pivot"]:]))
    identical = sum(a["buffer"] == b["buffer"] for a, b in
                    zip(raster.render_polygons(specs), frames))
    if verbose:
        print(f"current main.c vs `quadratic`, {len(frames)} frames")
        print(f"  worst width disagreement: {worst:.3e} px")
        print(f"  pixel-identical frames:   {identical}/{len(frames)}")
    return worst, identical


def main() -> int:
    print("legacy main.c (" + sheet_envelope.LEGACY + ") vs `shipped`:")
    worst = check()
    # float32 in the C against float64 here, over widths of order 6 px
    if worst > 1e-4:
        print("FAIL: the reimplementation does not match the C")
        return 1
    worst, identical = check_current()
    if worst > 1e-4 or identical != 720:
        print("FAIL: the current main.c does not draw `quadratic`")
        return 1
    if check_families() > 1e-9:
        print("FAIL: a family does not reduce to the shipped profile")
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
