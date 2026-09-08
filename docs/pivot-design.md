# Reparametrizing the connector pivot

How the middle of the Calligraphy stroke should bend, and where the pivot that
controls it should sit. **Centerline only** -- nothing here concerns the stroke,
the width profile, or rasterization.

Explored with `tools/preview/`; every number below comes from a sweep of all 720
clock positions, most of them across six stem geometries.

> Written in two rounds, and kept that way because the second round overturns
> part of the first. **The current recommendation is D1, in section 11.**
> Sections 1-3 still stand; the round-1 recommendation in section 6 does not.

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

## 6. Recommendation (superseded — see section 11)

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

---

# Round 2: unimodal curvature

Round 1 recommended C1 and bounded it with the tangent-triangle ceiling. Visual
review found a failure mode neither of us had in the design space, and it
invalidates that bound.

## 8. The constraint

At near-opposition the curvature along the connector can follow a **W**: the
curve *flattens around the pivot*, with the tighter bends pushed out to either
side. The requirement is that **|k| be unimodal** — rising to a single peak at
the pivot and falling, never dipping in the middle.

Measuring the dip as a fraction of the flanking peaks, at 10:10 (d = 115):

| flattens | | unimodal | |
|---|---:|---|---:|
| C4 openness^0.5 | 100.0% | C0 current | 0.0% |
| C2 branch clearance | 99.9% | C1 openness (0.70) | 0.0% |
| C7 chord midpoint | 93.5% | C3 chord fraction | 0.0% |
| C1 openness x ceiling | 92.8% | C4 openness^2 | 0.0% |
| C8 hand-length tilt | 92.8% | C5 always centre | 0.0% |
| C9 perpendicular foot | 92.3% | | |

Every flattener sits at s >= 18.7 px there; every unimodal one at s <= 13.3 px.
It is a **depth** constraint, and `tools/preview/test_harness.py` confirms tilt
is free once the depth is inside the limit — 0% dip for every `beta` from 0.30
to 0.70 — so depth and tilt remain cleanly separable.

## 9. The ceiling round 1 used was the wrong one

The tangent-triangle bound `H cos(d/2)` is correct for monotone turning but
roughly **1.8x** the unimodality limit where it matters, so it never bound
anything. Bisecting the real limit out of the solver:

| d | measured limit | round-1 chord ceiling | `min(r) tan(45-d/4)` |
|---:|---:|---:|---:|
| 45 | 30.43 | 45.35 | 30.07 |
| 75 | 22.71 | 38.95 | 22.19 |
| 105 | 15.75 | 29.88 | 15.28 |
| 135 | 10.24 | 18.79 | 8.95 |
| 165 | 3.37 | 6.41 | 2.95 |

The binding scale is the **constant-curvature apex**. A circle tangent to a
stem's radial line at its inner end and centred on the bisector crosses the
bisector at `r tan(pi/4 - d/4)`; tangency to both radials at unequal radii is
impossible, so the **shorter** stem gives the smaller apex and governs:

```
s_arc = min(r_h, r_m) * tan(pi/4 - d/4)
      = min(r_h, r_m) * cos(d/2) / (1 + sin(d/2))
```

The second form is algebraically identical, has no 0/0 at opposition, and needs
only square roots — so a C port uses the existing `square_root_float` and never
touches `atan`. It tracks the measured limit to within 1-3% across the range
(slightly above below d ~ 30, slightly below above it), and like `H` it is
symmetric in the stem radii and homogeneous of degree 1 in them, so every
stem-stability property from round 1 survives.

**The headroom ratio `s / s_arc` is what predicts the dip.** In the metrics
table every candidate that passes the unimodality gate has worst headroom
<= 1.00 and every one that fails has >= 1.51. That the threshold lands on 1.0
is the evidence that this is the right length scale, rather than merely a
convenient fit.

The ceiling is not, however, a safe *bound* on its own: used at full strength
(`nu = 1`, candidate DC) it flattens 95%. It sets the right d-dependence; the
margin has to come from a factor below 1, and unimodality has to be verified
numerically. `report.py --ceiling` re-bisects the limit so the closed form can
be re-checked rather than trusted, including under changed stems.

## 10. Two findings that settle the reparametrization

**The current rule avoids flattening only by luck.** Worst dip over 720
positions:

| rule | current | symmetric | swapped | strong-asym | short | long |
|---|---:|---:|---:|---:|---:|---:|
| C0 current | 0% | 0% | 0% | 22% | **99%** | 0% |
| D1 proposed | 0% | 0% | 0% | 0% | 0% | 0% |
| C3 chord fraction | 0% | 0% | 0% | 0% | 0% | 0% |

C0's depth is pinned at 13.1 px whatever the stems do, so shrinking them
(`short`, where the apex ceiling falls to ~10 px) leaves the pivot far past the
limit. **The face-radius anchoring causes both failures** — stem-instability and
flattening — from one root cause.

**Scaling C1 down does not fix it.** C1 x 0.70 is unimodal at 10:10 only because
its headroom there is *exactly* 1.00. It crosses at d = 117.5 and reaches a 91%
dip by d = 151. The *shape* of the depth function has to change, not just its
amplitude — which is precisely what swapping the chord ceiling for the arc apex
does.

## 11. Revised recommendation

**`s = min(r_h, r_m) * cos(d/2) / (1 + sin(d/2)) * sin(d/2)`**, tilt on the
bisector (`beta = r_h/(r_h + r_m)`). This is **D1**.

It supersedes the round-1 recommendation of C1, which fails the unimodality
gate. What carries over unchanged: zero arbitrary constants, homogeneity of
degree 1 in the stem radii, symmetry in them, `s(0) = 0` pinning the centre at
overlap, and containment in the tangent triangle. What is new is that the depth
is measured against the ceiling that actually binds.

A further point in its favour, found while checking it: the hand-tuned C0 profile
*is* D1, to within 1-4% out to d = 105.

| d | 15 | 30 | 45 | 60 | 75 | 90 | 105 | 120 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| C0 | 5.1 | 8.8 | 11.3 | 12.7 | 13.1 | 12.6 | 11.4 | 9.6 |
| D1 | 5.2 | 8.9 | 11.5 | 13.0 | 13.5 | 13.2 | 12.1 | 10.4 |

So D1 is not a new look — it is the current look, restated without the four
constants and made to follow the stems. That also means adopting it is visually
low-risk.

Open choices, all passing the gate:

- **D2** (`nu = sin^2(d/2)`, peak 9.6 px @ 103) and **D3** (`nu = sin^1.5(d/2)`,
  peak 11.1 px @ 92) are shallower and hug the centre longer. D3 is the middle
  option if D1 reads slightly full.
- **C3** (`0.35 dist(C, AB)`, peak 15.7 px @ 33) is fully reinstated. My round-1
  dismissal was wrong on the criterion that now matters: it is unimodal in every
  stem configuration, and its depth *is* stem-covariant, because `dist(C, AB)`
  is also homogeneous of degree 1 in the stem radii. It has the deepest peak of
  any passing candidate and the most front-loaded profile — it reaches 14 px by
  d = 15 and then decays. Whether that early ramp reads as eager or as decisive
  is a judgement the sheets exist to support, not something the metrics settle.
- **C3o** (`0.30 dist(C, AB) sin(d/2)`, peak 7.3 px @ 90) is the same idea with
  the ramp softened. Note the coefficient: at 0.35 its worst headroom is 0.98,
  on the threshold with nothing left for a stem change, so it is set to 0.30 to
  give it D1's margin.

## 12. What the round-2 sheets show

- `curvature-profiles.svg` — |k| against arc length, pivot marked, dip and
  headroom annotated per cell. A W is immediately visible. Positions where the
  connector departs from its chord by under half a pixel are drawn flat and
  labelled `straight`: autoscaling those turns floating-point noise into a
  dramatic and entirely fictional shape.
- `ceiling.svg` — the bisected unimodal region as a band, the closed form on its
  edge, the round-1 chord ceiling far above it, and every candidate's `s(d)`.
  C1 visibly leaves the band between d = 95 and 135.


## 13. Amendment: the criterion is relaxed at both degenerate ends

Unimodality is required through the working range, **not** at overlap or
opposition, where the geometry is degenerate by design. The metric encodes this
with two guards, and a dip is only counted when both are cleared:

- peak |k| corresponds to a radius under 1000 px — ten times the face; and
- the connector departs from its own chord by at least half a pixel.

Without them, floating-point noise in a sub-pixel curve yields 100% dip readings
from nothing. In practice the relaxation covers roughly `d < 5` and `d > 175`.

It does **not** rescue C1 x 0.70. Its failures run from `d = 117.5` (headroom
1.04) to `d = 151` (91% dip), nowhere near either end, so it stays disqualified —
which is what makes the point that the depth function's *shape* has to change
rather than its amplitude.

## 14. Watching the finalists move

Static positions cannot settle whether D1's similarity to the current
construction is a virtue or a reason not to bother, so `tools/preview/` also
renders the finalists over a full hour of clock time:

- `anim-current.gif` — D1 / D3 / C3 side by side, current stems, C0 underlaid.
- `anim-stems.gif` — D1 and C3 across `current`, `symmetric`, `strong-asym` and
  `short` stems.
- `anim-filmstrip.svg` — the same hour as a static contact sheet.

The 12:00 hour is used because it starts on exact overlap; over the hour the
separation runs 0 -> 178.5 -> 35.5 deg, so one loop covers overlap,
near-opposition, and the mid-range twice — opening once and closing once.

Rendering is two steps (`report.py --anim`, then `render_anim.sh`) because
rasterizing SVG needs a browser. The GIF encoder is `gifwriter.py`, written
against the standard library: the bundled Chromium writes only PNG and the
bundled ffmpeg is a stripped Playwright build with no GIF encoder, so neither
tool could close the loop on its own. Its LZW output is round-trip decoded in
`test_harness.py`, so a silently corrupt GIF cannot ship.
