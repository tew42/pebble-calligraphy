# Reparametrizing the connector pivot

How the middle of the Calligraphy stroke should bend, and where the pivot that
controls it should sit. **Centerline only** -- nothing here concerns the stroke,
the width profile, or rasterization.

Explored with `tools/preview/`; every number below comes from a sweep of all 720
clock positions, most of them across six stem geometries.

## 1. What is wrong with the current rule

`calculate_pivot_point` (`src/c/main.c:419`) offsets the pivot from the watch
centre along the hands' angle bisector by

```
s = R * MAX_PIVOT_OFFSET_RATIO(0.15) * shape(|sin d|) * sqrt(cos(d/2))
shape(x) = x(1 + PIVOT_PULL_BIAS)/(1 + PIVOT_PULL_BIAS * x),  bias = 0.50
```

Four independent arbitrary choices: the `0.15`, the `0.50`, the choice of
`|sin d|`, and the extra `sqrt(cos(d/2))` factor -- which is partly redundant,
since `|sin d|` already vanishes at opposition, so the two multiply into a peak
that lands at `d = 75` deg for no stated reason. The rendered peak depth is
13.1 px, not the nominal `0.15 R = 15 px`, because the two shaping factors never
peak together.

The deeper problem is the anchor. `0.15 * R` is a fraction of the **face
radius** -- a length with no relationship to where the stems actually end. The
consequence is measurable: sweeping the stem geometry over six configurations,
the current rule produces **s_max = 13.1 px in every single one**. Move the
stems and the pivot does not follow; the `0.15` has to be re-dialled by hand.
That makes it fragile against any future change to stem length or symmetry.

## 2. The structural fact everything rests on

Both stems are straight and **radial**, and the connector is required to join
them tangentially. So both tangent lines pass through the watch centre, and they
always intersect at exactly one point: **the centre itself**.

The connector is therefore always a rounding of the corner `(A, C, B)`, where
`A` and `B` are the inner stem ends and `C` is the watch centre. Monotone
turning -- no swerve -- requires the pivot to lie inside triangle `ABC`. That
bounds the problem, and it means the natural way to write the pivot is as a
*dimensionless* position within that triangle rather than as an absolute length.

## 3. The family: depth x tilt

```
P = C + mu(d) * [ (1 - beta) * A + beta * B ]      A, B relative to C
```

- **`mu`** -- **depth**: how far from the centre toward the chord.
- **`beta`** -- **tilt**: which stem end the pull leans toward.

With `mu, beta` in `[0,1]` this is a convex combination of `C`, `A` and `B`, so
the pivot is inside the tangent triangle **by construction**, and since `A` and
`B` are homogeneous of degree 1 in the stem radii, the whole family **rescales
with the stems** automatically. Both properties are asserted in
`tools/preview/test_harness.py`, across all six stem configurations.

The canonical depth is the normalized **openness** of the hands:

```
mu = sin^2(d/2) = (1 - u_h . u_m) / 2
```

`radial_dot = u_h . u_m` is already computed in `build_centerline`
(`src/c/main.c:1232`), and `cos(d/2) = sqrt((1+dot)/2)` needs only the existing
`square_root_float`. `mu(0) = 0` pins the centre at overlap. The reading is
plain: *the pivot travels from the watch centre toward the chord in proportion
to how open the hands are.* No constants.

`beta` has derivations rather than settings:

| `beta` | lands on | leans toward |
|---|---|---|
| `r_h/(r_h + r_m)` = 0.455 | the **angle bisector**; depth reduces to `H cos(d/2) mu`, `H` = harmonic mean of the stem radii | neither |
| `1/2` | the **chord midpoint** | the longer stem |
| `L_m/(L_h + L_m)` = 0.60 | hand-length weighting | the longer *hand* |
| `((C-A).(B-A))/|B-A|^2` | the **perpendicular foot**, closest point of the chord to the centre | the shorter stem |

Worth stating plainly: the pure bisector is **not** a neutral default. Equal
weight on `u_h` and `u_m` requires `(1-beta) r_h = beta r_m`, i.e. each stem end
weighted by the *opposite* stem's radius. It is a specific choice that happens
to be symmetric in direction.

## 4. Five findings from the sweep

**1. The two Hermite halves already join with continuous curvature.** Relative
`|dk|` at the pivot never exceeds `3.8e-14` over any candidate at any position.
Minimizing the bending integral with a free 2-D guide derivative reproduces the
natural-spline condition, so the solver delivers C2 at the joint, not merely C1.
This is a property of the existing solver and it is worth not breaking.

**2. "No swerving" is already satisfied, and not by the pivot rule.** Worst
excursion to the wrong side of the chord is <= 0.003 px for every candidate
except the deliberate counterexample. Curvature *sign flips* are common
(256/720 positions for the current rule) but carry a fraction of a percent of
the turning and under 0.01 px of geometry, so the sign-flip count is a
misleading statistic; the pixel excursion is the honest one.

**3. Both endpoints are accepted degeneracies.** At `d = 180` the connector is
a straight line, `k = 0`. At `d = 0` it is the fully self-overlapping path: in
along the radial to the centre, 180 deg reversal, back out, with all the turning
in the kink. That degenerate overlap is the *only* construction meeting the
design criteria, so the harness treats both as passes -- the tightness metric
excludes near-overlap positions rather than flagging them.

**4. An off-centre pivot at opposition costs a swerve only if the offset is
perpendicular.** This one was a surprise. At `d = 180` the offset decomposes
into a component along the hands' axis and one across it, and only the
perpendicular component forces an inflection:

| candidate | s @ 180 | perpendicular @ 180 | s @ 179.5 | perp @ 179.5 | swerve |
|---|---:|---:|---:|---:|---:|
| C1 openness (bisector) | 0.00 | 0.000 | 0.21 | 0.214 | 0.002 px |
| C7 chord midpoint | **4.50** | **0.000** | 4.51 | 0.235 | 0.000 px |
| C8 hand-length tilt | **14.40** | **0.000** | 14.40 | 0.282 | 0.000 px |
| C6 opposition bow | 0.00 | 0.000 | 24.55 | **24.545** | **1.901 px** |

So the two readings of "the pivot should not remain constrained to the centre"
are **not** in conflict. C7 and C8 hold the pivot 4.5 px and 14.4 px off the
centre at exact opposition while leaving curvature identically zero, because
their offset is purely axial. Only a perpendicular bow (C6) costs an inflection
-- and it costs a real one: 1.9 px of visible S, with 212 positions placing the
pivot outside the tangent triangle.

Relatedly, `beta = r_h/(r_h+r_m)` is exactly the tilt at which the axial offset
cancels at opposition. The bisector member is the unique one that returns the
pivot to the true centre there, in every stem configuration.

**5. The stem-stability test separates the candidates cleanly.**

| rule | `short` (r 0.25/0.30) | `current` (0.45/0.54) | `long` (0.56/0.75) |
|---|---:|---:|---:|
| C0 current | 13.1 px | 13.1 px | 13.1 px |
| C1 openness | 10.5 px | 18.9 px | 24.7 px |
| C2 clearance | 12.5 px | 22.5 px | 28.0 px |

C1 tracks `H` exactly (27.3 / 49.1 / 64.1 px, same ratios to four figures). C0
is flat -- it cannot see the stems. Under `swapped` stems, every derived rule
mirrors its curvature asymmetry about 0.5 to within 1e-4; the one exception is
C8, whose tilt is tied to hand length and so does not follow a stem swap.

## 5. Candidates, measured

`current` stems, all 720 positions. `swerve` in px, `minR90` = tightest radius
of curvature for `d >= 90`, `turn share` = fraction of the turn taken by the
hour half (0.5 is symmetric), `k_h/k_m` = mean peak-curvature ratio between the
halves.

| candidate | swerve | minR90 | s max | @ d | turn share | k_h/k_m | gate |
|---|---:|---:|---:|---:|---:|---:|:--:|
| C0 current | 0.0000 | 19.4 | 13.1 | 75 | 0.468 | 0.97 | pass |
| C1 openness x ceiling | 0.0019 | 26.0 | 18.9 | 110 | 0.501 | 1.21 | pass |
| C1 openness (0.70) | 0.0000 | 18.6 | 13.2 | 110 | 0.478 | 1.16 | pass |
| C2 branch clearance | 0.0000 | 20.7 | 22.5 | 90 | 0.514 | 1.30 | pass |
| C3 chord fraction | 0.0000 | 18.5 | 15.7 | **33** | 0.473 | 0.98 | pass |
| C4 openness^0.5 | 0.0027 | 15.8 | 24.5 | 90 | 0.522 | 1.33 | pass |
| C4 openness^2 | 0.0013 | 14.0 | 14.1 | 127 | 0.481 | 1.13 | pass |
| C5 always centre | 0.0000 | **7.7** | 0.0 | - | 0.423 | 0.96 | pass |
| C6 opposition bow | **1.9010** | 12.1 | 24.5 | 180 | 0.546 | 1.20 | **FAIL** |
| C7 chord midpoint | 0.0002 | 26.9 | 19.2 | 110 | 0.506 | 1.15 | pass |
| C8 hand-length tilt | 0.0004 | **29.4** | 21.1 | 117 | 0.519 | 1.03 | pass |
| C9 perpendicular foot | 0.0019 | 25.7 | 18.9 | 110 | 0.483 | 1.21 | pass |

Reading the table:

- **C3 (chord fraction)** is the most literal reading of "a fraction of the way
  from the centre to the chord", and it is wrong: it peaks at `d = 33` deg and
  then plateaus, because near overlap the chord is short and nearly radial so
  `dist(C, AB)` is dominated by `|r_m - r_h|`. The pivot snaps outward the
  moment the hands separate.
- **C5 (always centre)** has by far the tightest corners (`minR90 = 7.7` px
  against 26 for C1) and the most lopsided turn split. It is visibly pinched --
  a useful demonstration of what pinning the pivot costs.
- **C1, C7, C8, C9** differ mainly in *tilt*, not depth: all four peak near
  `d = 110` at 19-21 px. The tilt is a real difference (at 3:00 the pivot sits
  at -45.0 deg for C1 against -39.8 deg for C9, and at 12:07 the gap is 14.5
  deg) but a subtle one; `tilt-grid.svg` is the sheet for judging it.
- **C2 and C4^0.5** are the deep, round options, peaking at 22-25 px and near
  `d = 90`. They read as smoother arcs -- possibly *too* smooth, in that a very
  round middle starts to blur the two hand directions the design wants to keep
  clearly defined. That is a taste call the sheets exist to settle.

## 6. Recommendation

**Depth: `mu = sin^2(d/2)`. Tilt: `beta = r_h/(r_h + r_m)`.** That is C1, whose
closed form on the bisector is

```
s = H * cos(d/2) * sin^2(d/2),     H = 2 r_h r_m / (r_h + r_m)
```

Reasons, in order of weight:

1. **Zero arbitrary constants.** Four magic numbers become none. Every quantity
   is a length or an angle already present in the model.
2. **Stem-stable by construction** -- homogeneous of degree 1 in the stem radii
   and symmetric in them, so it survives a change of stem length or symmetry
   with no dial to move. This is the criterion the current rule fails outright.
3. **Correct limits for free**, not by special-casing: `mu(0) = 0` pins the
   centre at overlap, and `beta = r_h/(r_h+r_m)` is precisely the tilt whose
   axial offset cancels at opposition. The antiparallel degenerate branch at
   `src/c/main.c:469` becomes unnecessary.
4. **Inside the tangent triangle by construction**, so no-swerve is structural
   rather than a tuning outcome.
5. Corners are materially gentler than today's: `minR90` 26.0 px against 19.4.

Two open choices for you, both cheap to change and both visual rather than
analytical:

- **Depth scale.** C1 at full strength peaks at 18.9 px against today's 13.1.
  `C1 x 0.70` reproduces the current depth exactly while keeping the derived
  shape -- but that reintroduces one dial, so I would rather ship `1.0` unless
  the deeper bow looks wrong to you. The peak also moves from `d = 75` to
  `d = 110`, which is the more visible change.
- **Tilt.** C1's bisector is the principled default. If the hour half should
  turn tighter and the minute half open out lazily toward the long minute hand,
  C9 (`beta` = perpendicular foot) leans that way while keeping every structural
  property; C7 leans the other. Note that C7 and C8 additionally satisfy the
  literal "off-centre at opposition" reading at zero cost, per finding 4 -- if
  that property appeals, C7 is the one to look at.

## 7. Not addressed here

Choosing new stem ratios. `HOUR_STEM_RATIO 0.25` and `MINUTE_STEM_RATIO 0.40`
remain arbitrary and asymmetric; this work makes the pivot rule **indifferent**
to them rather than picking them. Also untouched: the minimum-bending tangent
solve (deliberately -- see finding 1), the width profile, and everything
downstream of `build_stroke_polygon`.
