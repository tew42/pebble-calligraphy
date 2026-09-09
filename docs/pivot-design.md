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

## 16. Curvature-prescribed connector: works, with one broken band

Round 5 inverted the approach. Every construction so far interpolated geometry
and hoped the curvature came out right; since the requirement is stated on `k`,
`tools/preview/curvature.py` makes `k` the primitive:

```
k(s) = (Omega / L) * t^m (1-t)^n / integral(t^m (1-t)^n),   t = s/L
```

Non-negative so single-signed; zero at both stem junctions for `m, n >= 1`;
exactly one maximum at `t = m/(m+n)`; continuous; and it turns by exactly
`Omega = pi - delta`. All structural, none of it tuned.

Because `k` scales as `1/L` the curve is *similar* under `L`, so the solve
decouples: `q = m/(m+n)` from the chord **direction** (1-D bisection, monotone),
`L` from the chord **length** (one division), and `nu = m + n` from the required
**depth**. Concentration is the dial that trades centre-passage against
curvature continuity, so pinning the depth at both ends of the delta range
determines it rather than leaving it free. Evaluate the shape in log space
relative to its peak -- direct evaluation underflows (`t**4000 == 0.0`) and
silently yields zero curvature.

**What it fixes.** Worst reverse turn in the working range, per stem config:

| stems | D1 cubic | C3 cubic | curvature-prescribed |
|---|---:|---:|---:|
| current | 1.91 deg | 0.44 | **0.00** |
| symmetric | 1.68 | 0.00 | **0.00** |
| swapped | 1.91 | 0.44 | **0.00** |
| strong-asym | **6.03** | **5.68** | **0.00** |
| short | 1.91 | 0.44 | **0.00** |
| long | 2.12 | 1.15 | **0.00** |

`k` is zero at both junctions to machine precision, depth tracks D1 to about
1 px, and the rendered shapes are close enough to D1 that adopting it would be
visually low-risk. It removes the `strong-asym` artifact outright, which nothing
else did.

**The one defect, and it is real.** The construction has three regimes in
`delta`, and the middle one is broken:

- `delta >~ 15`: excellent -- reverse turn 0.00, depth within ~1 px of D1.
- `delta <~ 8`: falls back to the degenerate fold, pinned on the centre, which
  is the shape wanted there anyway.
- `delta` 8 to 15: **broken**. The depth jumps 0.00 -> 4.23 px between adjacent
  minutes at the handover, which would read as a pop once per lap. The solve
  also needs `nu` of 2e4 to 5e4 through this band, where the curvature spike is
  about `1/sqrt(nu)` of the span and sits at the edge of what the integration
  resolves (one probe returned a nonsensical 4e7 px radius).

Not yet attempted: making the handover continuous, either by relaxing the depth
target across the transition band so the fold and the smooth solve meet, or by
blending the two curves over it. Both are bounded work, but which depth to
accept through `delta` 8-15 is a design choice, not a numerical one.

# Round 3: four ways to shape the curvature

## 17. The delta 8-15 band was an integration failure, not a design gap

Section 16 blamed a broken middle band on the handover between the smooth solve
and the degenerate fold. That was wrong, and the cause was mundane. The Frenet
integration stepped uniformly in `t`, but a Beta shape with concentration `nu`
has its curvature spike about `1/sqrt(nu)` wide. Past `nu` of roughly 6e4 the
uniform grid simply steps over the spike, so the integrated turn came out short,
the solve failed, and the code fell back to the fold -- taking the depth with
it. The nonsensical 4e7 px radius was the same thing.

Overlaying a fine sub-grid across +/- 8 sigma of the peak (`sigma =
sqrt(q(1-q)/nu)`) resolves the spike at any concentration. With that in place:

- the solve runs down to `delta = 1.5`; the fold is used only for `delta <= 1`
- the 4.23 px pop is gone
- depth now tracks D1 to within **0.001 px** at every minute of the hour, in all
  six stem configurations

So there was never a broken band and never a design choice to make there. There
was also never a `+1.27 px` depth offset: that reading came from measuring depth
on the *drawn* 30-segment polyline. Near overlap the entire turn happens inside
a window narrower than one drawn segment, so the polyline chords straight across
the fold and misses the centre by over a pixel while the true curve passes
through it. The solved curve was always on target. Depth is now reported from
the solve, and the drawn samples are allocated by turning as well as by arc
length so the rendered line follows the fold.

## 18. Compact support: the shape the geometry was asking for

F1 spreads `k` over the whole connector, so `k` can only reach zero *at* the
junctions, asymptotically. A deep pivot then demands enormous concentration --
`nu` of 2.4e5 at `delta = 5.5`. That is what made it numerically awkward, and it
is an artifact of insisting on full support.

Both stem tangent lines are radial, so they meet at the watch centre (section
2), and the connector is a corner-rounding of the triangle (A, C, B). The
natural curvature shape for a corner-rounding is therefore *compact*: exactly
zero along a straight radial run, one hump, exactly zero along the other
straight run. That has a consequence worth stating plainly -- **`k` reaches the
stem junctions at exactly zero, so there is no curvature step where the
connector meets the straight stem.** The cubics all have one; it shows in the
curvature sheets as a profile that starts and ends visibly off the axis.

Compact support also makes the construction closed form. A symmetric hump is
mirror-symmetric about its own midpoint, so it leaves and rejoins the two radial
lines at the *same* distance `d` from the centre. With `H` the hump's arc length
and `g`, `sigma` the chord and sagitta of the *unit-length* hump (pure shape
constants at a given turn `Omega = pi - delta`):

    straight runs    alpha = r_h - d,   beta = r_m - d
    hump chord       2 d sin(delta/2) = H g(Omega)
    depth            s = d cos(delta/2) - H sigma(Omega)

Eliminating `H` leaves the depth **exactly proportional to `d`**:

    s = d [ cos(delta/2) - 2 sin(delta/2) sigma(Omega) / g(Omega) ]

One dial, and it is a division rather than a root find. No concentration to
diverge, no spike to resolve, and overlap needs no special case: the target goes
to zero, so `d` and `H` go to zero and the curve becomes the fold A -> C -> B by
itself.

| | shape of `k` | `k` continuous | `k'` continuous | closed form |
|---|---|---|---|---|
| F1 | `t^m (1-t)^n`, full support | yes | yes | no: nested bisection |
| F2 | trapezoid (ramp / plateau / ramp) | yes | no, 4 corners | yes |
| F3 | raised cosine, compact support | yes | yes | yes |
| F4 | constant (straight / arc / straight) | **no, 2 jumps** | no | yes |

## 19. F4 is the arc-apex ceiling, and D1's depth rule is F4's geometry

F4's bracket collapses to `cos(delta/2) / (1 + sin(delta/2))`, so its reachable
depth range is exactly `[0, arc_apex_ceiling]` -- the bound section 9 derived
from the constant-curvature apex. That is not a coincidence: F4 *is* that
construction. D1's rule is `arc_apex_ceiling * sin(delta/2)`, so driving F4 to
D1's depth gives, in closed form,

    d = min(r_h, r_m) * sin(delta/2)

and the two agree to the last digit at every hand position and every stem
configuration. D1 was, without anyone intending it, a cubic approximation to a
line-arc-line fillet.

That also supplies the compact families' own dial. Driving them by a depth
target imported from a pivot rule works, but each converts tangent length into
depth at its own rate, so a target tuned for one is out of reach for another --
F3 runs out of stem near `delta = 90` and F2 past `delta = 90`. Stating the rule
on `d` instead removes that entirely:

    d = min(r_h, r_m) * sin(delta/2)

It is one line, identical for every member; it can never ask for more stem than
exists, so nothing ever clamps in any of the six stem configurations; and the
depth becomes a *consequence* of the shape rather than something imposed on it.
The limits come out right with no special casing -- `d -> 0` at overlap so the
connector folds exactly through the centre, `d -> min(r)` at opposition so both
straight runs vanish and the connector is one clean hump -- and it scales with
the stems, so it survives a change of stem length or symmetry.

## 20. How visible is F4's curvature jump?

It breaks the stated requirement, so it needs a number rather than an opinion.
At a straight-to-arc join of radius `R` the curve pulls away from the incoming
straight by `R (1 - cos(1/R))` over one pixel of travel:

| stems | R at d=90 | dep | R at d=45 | dep | min R | at d | dep |
|---|---:|---:|---:|---:|---:|---:|---:|
| current | 32.2 | 0.016 | 6.8 | 0.073 | 0.10 | 5.5 | 0.207 |
| strong-asym | 21.5 | 0.023 | 4.5 | 0.110 | 0.07 | 5.5 | 0.138 |
| short | 17.9 | 0.028 | 3.8 | 0.131 | 0.06 | 5.5 | 0.115 |
| long | 40.1 | 0.012 | 8.5 | 0.059 | 0.13 | 5.5 | 0.258 |

Sub-pixel everywhere, and largest near overlap -- which is exactly where the
design wants a kink. Fills are not antialiased on this platform, so a 0.02 px
departure at quadrature cannot survive rasterization at all. The jump is real in
`k` and invisible in the drawing.

## 21. Cost, sized for once-per-minute redraw

| | linear solves | root finds | quadrature | transcendentals | can fail |
|---|---|---|---|---|---|
| C0 / C1 / D1 | 2 x 4x4 Gauss-Jordan | none | none | 1 sqrt + 30 Hermite evals | yes: solve validity, Tikhonov retry |
| F1 | none | **nested**: 30 x 44 | ~1600 pts per probe | ~2e6 log/exp/sin/cos | yes: falls back to the fold |
| F2 / F3 | none | none | one 1-D pass over the hump | ~90 `sin_lookup` / `cos_lookup` | no |
| F4 | none | none | **none** | 30 `sin_lookup` + 30 `cos_lookup` | no |

F2 and F3 need no lookup table, and the ordering works out better than it
looks. The chord `g` of the unit hump is just the endpoint of the same
integration pass that produces the drawn samples, so one pass over ~30 steps
gives `g`, hence `H = 2 d sin(delta/2) / g`, hence the scale factor for the
points already computed. `Phi(tau)` is analytic in both cases -- piecewise
quadratic for F2, `tau - sin(2 pi tau)/(2 pi)` for F3 -- so each sample costs a
couple of table lookups. No iteration anywhere.

F1 also has a *maximum* reachable depth: `nu = 2` is the gentlest Beta whose
curvature still vanishes at both ends (`m, n >= 1`), and past `delta` of about
110 even that is too deep to match D1, so F1 falls short by up to 1.1 px there.
That is the mirror image of F2 and F3 running out of stem at wide separation.
F4 is the only member that never runs out of range anywhere.

F1 is a research instrument, not something to ship: it costs roughly four orders
of magnitude more than the alternatives and is the only member that can fail.
F4 is *cheaper than the code in `main.c` today*, because it removes both 4x4
solves and the validity/retry path along with them; `d = min(r) sin(delta/2)`
needs one square root, which `square_root_float()` already provides, and the arc
samples are two table lookups each.

## 22. What the round-3 sheets show

Sheets: `constructions-current.svg`, `constructions-strong-asym.svg`, the
matching `-zoom-` pair at 2.6x on the centre, `constructions-own-d.svg`, and
`curvature-current.svg` / `curvature-strong-asym.svg`.

Swept over all 720 hand positions and all six stem configurations (full tables
in [`families-measured.md`](families-measured.md)). On `current` stems:

| family | worst reverse turn | `k` at junction / peak | swerves at | depth at d=90 |
|---|---:|---:|---:|---:|
| C0 cubic (current) | 1.93 deg | 0.46 | 59% of positions | 12.61 px |
| C1 cubic | 6.55 | **1.00** | 61% | 17.36 |
| D1 cubic | 1.91 | 0.82 | 36% | 13.18 |
| F1 Beta | **0.00** | **0.000** | **0%** | 13.16 |
| F2 trapezoid | **0.00** | **0.000** | **0%** | 10.12 |
| F3 raised cosine | **0.00** | **0.000** | **0%** | 8.59 |
| F4 constant | **0.00** | **0.000** | **0%** | 13.18 |

On `strong-asym` the cubics get much worse -- C0 5.41 deg and swerving at 84% of
positions, C1 7.46 deg at 72%, D1 6.03 deg at 82% -- and every F family stays at
0.00 deg and 0%.

- The cubics' `k` changes sign somewhere along the connector at between 12% and
  84% of hand positions, depending on rule and stems. **None of the F families
  changes sign at any position, in any stem configuration.**
- The cubics' `k` starts and ends off zero -- a curvature step at the stem
  junction, and for C1 the curvature *maximum* sits at the junction rather than
  anywhere near the pivot. F1 approaches zero asymptotically; F2, F3 and F4
  reach the junctions at exactly zero.
- C0's depth at quadrature is 12.61 px in *every* stem configuration -- the
  stem-instability from section 1, visible in one number. Every F family scales
  with `min(r_h, r_m)`.
- Silhouettes are close: at the working separations F1 through F4 sit within a
  pixel or two of D1, so this is not a change of look. `constructions-own-d.svg`
  shows the compact families on their own dial, where nothing clamps.
- Depth is continuous: the largest change between adjacent minutes is ~2 px on
  `current`, which is just the hands moving, and it matches D1's to 3 decimals.

None of this is a recommendation yet -- the visual judgement between F2, F3 and
F4 (and whether F4's `k` jump matters at this resolution) is the author's.

## 23. Families not built, and why

The four above are not the whole space. These were considered and set aside,
with the reason in each case.

**Clothoid pair (Euler spiral in, Euler spiral out).** `k` rises linearly from
zero to a peak at the join and falls linearly back -- so it is F2 with the
plateau removed, a triangle rather than a trapezoid. Everything said about F2
applies, `k` is continuous and `k'` has two corners instead of four, and it is
marginally cheaper. It is not a separate family so much as F2 at a plateau
fraction of zero; the plateau fraction is fixed structurally at one third, and
nothing measured suggests the triangle would behave differently. Worth a row on
a sheet if the trapezoid's flat maximum reads badly.

**Biarc.** Two same-sign circular arcs meeting tangentially at an interior
point: the classical way to hit two positions and two tangents in closed
form. It is what F4 becomes if the two tangent lengths are allowed to differ,
and it is the only cheap construction that can be genuinely asymmetric (see
below). But `k` then jumps *three* times
-- at both stem junctions and at the arc-arc join -- so it is strictly worse
than F4 on the stated requirement while costing more. Rejected on that.

**Spiral (curvature-monotone) Hermite interpolation.** The literature
construction for joining two position/tangent pairs with monotone curvature.
It solves the wrong problem here: monotone `k` along the whole connector is
incompatible with `k = 0` at *both* junctions, which is the requirement that
removes the curvature step. It would suit a connector allowed to keep curvature
at one end.

**Genuinely asymmetric curvature, informed by the hand lengths.** This was asked
for explicitly and deserves a straight answer: F2, F3 and F4 are only *mildly*
asymmetric. The hump itself is symmetric -- that is what forces equal tangent
lengths and makes the depth a division rather than a root find -- so the stem
asymmetry shows up only in the two straight runs, `r_h - d` against `r_m - d`.
For `strong-asym` at `delta = 90` that is 8.8 px against 48.8 px, which is a
large asymmetry in the *drawn line* but none at all in `k`.

Making `k` itself asymmetric means unequal tangent lengths -- say `d_h = rho
r_h`, `d_m = rho r_m`, one dial `rho` -- and then the hump has to skew to join
them. Skewing costs the symmetry argument, so the chord direction no longer
comes for free and a second solve returns: exactly F1's two-dimensional
structure, at F1's price. The honest summary is that **asymmetric `k` and
closed form are in direct conflict here**, and the conflict is structural, not
an artifact of these four shapes. Given that all four already reach 0.00 deg
reverse turn in `strong-asym` -- the case asymmetry was meant to fix -- there is
no measured problem left for asymmetric `k` to solve. If it is wanted for its
own sake, the biarc is the cheap version and it costs a third `k` jump.
