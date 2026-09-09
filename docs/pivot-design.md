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

# Round 4: the verdict

## 24. Two claims from round 3 that visual review overturned

**"F5, the small cosine taper, is the principled choice."** Wrong, twice over.
It carries a taper fraction, which is exactly the kind of tuned constant this
whole exercise exists to remove -- the same objection as C0's four constants.
And it optimises the wrong quantity: a *small* taper maximises the plateau, so
F5 has more constant-radius arc than F2, not less. If what reads as machined
about F4 is its visible constant-radius section, F5 moves toward the defect.

**"F1 is a research instrument, not something to ship."** Also wrong. F1's
solve is a function of `delta` alone once the stems are fixed, so the whole
nested bisection can be precomputed. Tabulating the connector in a
normalised frame and interpolating: 17 slices (11 degrees apart) hold it to
**0.43 px**, 12 slices to 0.63 px. That is about 2 KB of constant data and 31
lerps plus one similarity transform per redraw -- cheaper than the two 4x4
Gauss-Jordan solves in `main.c` today. The honest objection to F1 is not cost
but that the watch would no longer *know* the construction, only replay a table
keyed to one stem configuration.

## 25. Both curvature discontinuities are invisible; the reverse bend is not

Measured as departure from the tangent line over one pixel of arc, at
`delta = 90`:

| | k at the join | radius | departure |
|---|---:|---:|---:|
| D1's step at the stem junction, `current` | 0.0065 | 155 px | 0.003 px |
| D1's step, `strong-asym` | 0.0161 | 62 px | 0.008 px |
| F4's jump at the tangency, `current` | 0.0310 | 32 px | 0.016 px |
| F4's jump, `strong-asym` | 0.0465 | 21 px | 0.023 px |

All sub-pixel by two orders of magnitude, on a face with unantialiased fills.
So `k`-continuity, taken by itself, is a mathematical property here rather than
a visible one -- and what reads as "forced" about F4 cannot be the jump. The
one defect in this whole exercise that *is* visible is the reverse bend, worth
1.9 to 6.8 degrees of reverse turn and up to 3.4 px of separation between D1
and a monotone-curvature construction, and it belongs exclusively to the
prescribed-pivot cubics.

## 26. What actually makes D1 look swoopier

Not a gentler bend: at matched depth D1's peak curvature is 0.048 against F5's
0.031 -- **55% tighter**. What differs is how much of the connector is curved at
all. Compact support buys exact zero curvature at the stem junctions by putting
genuinely straight radial runs there, and those runs are a large share of the
connector:

| shape at matched depth | free constant? | d=38 | d=66 | d=90 | d=115 |
|---|---|---:|---:|---:|---:|
| D1 cubic | four | 100% | 100% | 100% | 100% |
| F3 raised cosine | none | 26% | 65% | 90% | 90% |
| triangle (double clothoid) | none | 23% | 58% | 88% | 90% |
| F2 trapezoid, plateau 1/3 | the plateau | 21% | 54% | 82% | 90% |
| F5 taper 1/6 | the taper | 19% | 46% | 70% | 89% |
| F4 constant | none | 16% | 39% | 59% | 75% |

D1 is 100% curved because its `k` is *nonzero* at the junctions -- that is the
same fact, seen from the other side. And the two cannot both be had: reaching
the centre at overlap means travelling the whole of `r_h` inward and `r_m`
outward, and with `k = 0` at the junctions and `k` single-signed, the only way
to do that is with near-straight radial runs. **Near overlap the straight runs
are forced by the overlap requirement itself, not chosen.**

The obvious escape -- just make it deeper, `d = min(r) sin(delta/2)^p` with
`p < 1` -- does not work. Lowering the exponent pops the curve off the centre
one minute after overlap:

| p | 12:00 | 12:01 | 12:02 |
|---|---:|---:|---:|
| 1.00 | 0.00 | 1.96 | 3.57 |
| 0.75 | 0.00 | 4.19 | 6.42 |
| 0.50 | 0.00 | 8.95 | 11.54 |
| D1 | 0.00 | 2.06 | 3.92 |

`sin(delta/2)` is doing real work, and the 2 px overlap spec essentially pins
`p = 1`. Swoopiness has to come from the *shape*, not from the depth.

## 27. The trade, and the rule that removes it

Shape choice is a single monotone trade -- swoopier shapes reach less depth,
and run out of stem sooner when driven to the fillet depth:

| shape | k' continuous | runs short past | worst shortfall |
|---|---|---:|---:|
| F3 raised cosine | yes | delta 83 | 3.0 px |
| triangle | no (corners in `k'`) | delta 92 | 2.3 px |
| F2 trapezoid 1/3 | no | delta 99 | 1.7 px |
| F5 taper 1/6 | yes | delta 119 | 0.8 px |
| F4 constant | no (`k` jumps) | never | 0 |

Which is resolved by not choosing at all. The cosine-tapered plateau is a
one-parameter family with F3 (`rho = 0.5`, no plateau) and F4 (`rho = 0`, all
plateau) as its two endpoints, and `k`, `k'` both continuous for any
`rho > 0`. So state the rule as a *criterion*:

> **F6: take the smoothest taper that still reaches the depth.**

The condition is `bracket(rho, delta) = bracket(0, delta) sin(delta/2)`, and
`min(r_h, r_m)` cancels from both sides -- so `rho(delta)` is a **universal
function of the separation alone, independent of the stems**. Measured:

- `rho = 0.5` -- a pure raised cosine, zero plateau -- for every separation
  **out to delta 82**, which is where the bend is actually visible
- a plateau reaches a third of the hump only past **delta 96**, and the arc is
  never tighter than **35 px radius** there; plateau length and tightness are
  anti-correlated by construction
- `rho -> 0` only as opposition is approached, where peak `k` has fallen to
  0.0008 (a 1280 px radius on a 200 px face)

Swept over all 720 positions in all six stem configurations: depth matches D1's
rule to **0 px**, reverse turn **0.00 deg**, curvature at both stem junctions
**exactly zero**, depth at overlap **exactly zero**, and it never runs out of
stem. It carries no free constant, no blending, and no per-stem tuning.

Cost: `rho(delta)` is a universal table (about 32 entries, computed once for
all time rather than per design), then one pass over the hump for `g`, one
division for `d`, and the placement. No linear solve, no root find at runtime,
no failure mode -- cheaper than `main.c` today, which does two 4x4 solves plus
a validity check and a Tikhonov retry.

## 28. D1's own design space, for completeness

D1's connector reads the stems only through `r_h` and `r_m`; the hand tips do
not enter it. Sweeping both from 0.10 to 0.90 of the face radius confirms the
defect is **exactly scale-invariant** -- identical to two decimals along any ray
`r_m/r_h = const` -- and symmetric under swapping the two, so it depends only on
`|log(r_m/r_h)|`:

| `r_m/r_h` | reversed `k` lobe (% of peak) | worst reverse turn |
|---:|---:|---:|
| 1.00 | 0.55% | 1.68 deg |
| 1.10 (or 0.91) | 1.32% | 1.80 |
| 1.20 (**current**) | 2.63% | 1.91 |
| 1.31 (or 0.76) | 4.60% | 2.06 |
| 1.50 (or 0.67) | 8.69% | 2.77 |
| 2.00 (or 0.50) | 19.6% | 4.91 |
| 2.50 (or 0.40) | 27.9% | 6.50 |

So: **the region with no reversed curvature is empty.** The reverse turn never
falls below 1.68 degrees anywhere in the space, including at perfect symmetry.
The usable bands, if D1 is kept:

- reversed lobe under 1% of peak: `r_m/r_h` within about **[0.93, 1.07]**
- under 5%: within about **[0.75, 1.33]**

The current 0.45 / 0.54 sits at ratio 1.20, giving a 2.6% lobe -- comfortably
inside the 5% band with roughly 10% of headroom before it leaves. The W
flattening, by contrast, is absent everywhere in the space: D1 fixed that
outright, and the reversed lobe is its only remaining defect.

# Round 5: the asymmetric option, and D1's worst case drawn

## 29. A1: uneven tangent lengths, and what asymmetry is actually worth

A symmetric hump is mirror-symmetric about its own midpoint, so it must meet
both radials at the *same* distance from the centre. The shorter stem therefore
caps the reach and the longer stem's surplus is wasted. Skewing the hump lifts
that cap. From the triangle at the centre, the chord `S -> E` is
`d_h u_in + d_m u_out`, so

    tan(psi) = d_m sin(Omega) / (d_h + d_m cos(Omega))
    d_m / d_h = sin(psi) / sin(Omega - psi)

and `psi = Omega/2` gives `d_h = d_m` -- which is exactly why a symmetric hump
is stuck. So the *shape's* chord angle fixes the tangent-length ratio, and a
wanted ratio fixes the shape.

**The tidy version does not work.** Proportional tangent lengths
(`d_h = rho r_h`, `d_m = rho r_m`) would be the elegant rule: both straight runs
vanish together at `rho = 1`, the required `psi` is closed form, and the whole
configuration scales linearly about the centre so the depth is one division.
But it is out of reach. A skewed raised cosine's area is proportional to its two
ramp widths -- integrating, `Phi(a) = a` for a peak at `a` -- so it cannot
front-load the turn, and its chord angle spans only a narrow band around
`Omega/2`. The tangent-length ratio it can deliver:

| delta | reachable `d_m/d_h` |
|---:|---|
| 10 | 0.86 .. 1.17 |
| 60 | 0.55 .. 1.81 |
| 90 | 0.49 .. 2.06 |
| 170 | 0.42 .. 2.36 |

The current stems already want 1.20, which is outside the reach below about
`delta = 12`; `strong-asym` wants 2.33, outside it below about 150. Driving the
proportional rule anyway fails the inversion at 605 of 720 positions under
`strong-asym`, and falls back to the fold.

**What works is to skew only as far as the depth demands:**

    d_h = min(r_h, d),   d_m = min(r_m, d)

Below the symmetric ceiling nothing is skewed and this *is* F3; above it the
shorter tangent sticks at `r_h` while the longer one grows, and the skew comes
in continuously from zero. Measured over `delta` 0..180 in each stem
configuration:

| stems | exact depth out to | worst shortfall | F3's shortfall | gain |
|---|---:|---:|---:|---:|
| symmetric | delta 83 | 3.34 px | 3.34 px | **0.00** |
| short | delta 91 | 1.27 | 1.67 | 0.40 |
| current | delta 91 | 2.28 | 3.01 | 0.73 |
| swapped | delta 91 | 2.28 | 3.01 | 0.73 |
| long | delta 99 | 2.20 | 3.74 | 1.54 |
| strong-asym | **delta 179** | **0.00** | 2.00 | 2.00 |

That is the honest answer to what asymmetric curvature buys: **it converts the
longer stem's surplus into depth reach, and it is worth exactly nothing when the
stems are equal.** Under `strong-asym` it reaches the full fillet depth at every
separation, which no symmetric smooth shape does. Under the current stems it
extends the exact range from `delta` 83 to 91 and shaves the worst shortfall
from 3.0 to 2.3 px.

Curvature requirements all survive: single-signed everywhere, exactly zero at
both stem junctions, exact fold through the centre at overlap. Reverse turn is
0.08 degrees, which is sampling of the skewed hump rather than shape -- 25 times
smaller than D1's. Below the symmetric ceiling A1 reproduces F3 to 2e-14 px, as
it should: the skew is exactly zero there.

Finding A1's handover exposed a latent bug in the shared hump cache, worth
recording because it was silent. `_hump_unit` keys on the shape's `key` string,
and both `tukey_shape` and `skewed_cosine` formatted their parameter into that
key with `%.3f` / `%.4f`. Every solve that bisects on a shape parameter was
therefore bisecting against a *step function* quantised at 1e-3 or 1e-4, and
converged to the middle of a quantisation cell rather than to the root. It
never showed up in F6's results -- the outer depth solve absorbed it into `d` --
but F6's taper was only ever resolved to about 5e-4. Both keys now carry full
precision, and F6's depth error is 3e-14 px.

**Where it loses to F6.** F6 reaches the depth target at *every* separation in
*every* stem configuration, with no shortfall anywhere; A1 only closes the gap
when the stems happen to be lopsided. F6's taper schedule is a universal
function of `delta` with the stems cancelling out; A1's skew schedule depends on
`r_h` and `r_m`, so it is a per-design constant. And A1 needs a nested 1-D
solve in the band above the symmetric ceiling, against F6's single division.
A1's one advantage is that it keeps a plateau-free cosine at every separation,
where F6 grows a plateau past `delta = 83` -- but that plateau only becomes a
third of the hump past `delta = 96`, where the arc is never tighter than 35 px
radius, so the advantage is not visible.

## 30. D1's worst case, drawn -- and a correction to section 28

Sheet: `d1-worst.svg`. For each stem ratio it finds the hand position maximising
each defect, draws the connector with the reversed-curvature run picked out, and
zooms 7x with F6 overlaid at the same depth.

**The correction.** Section 28 ranked stem ratios by the reversed `k` lobe as a
share of peak `|k|`. That is scale-free, which makes it comparable across
ratios, but it is *not weighted by visibility* -- and its maximum sits out near
opposition, where peak curvature has fallen to a 400 px radius. At ratio 2.50
the worst lobe is 27.9% of peak and sits at `delta = 149`, where it amounts to
**0.12 px** of actual deviation. Quoting it as the headline number overstated
the defect at wide separations and understated where it really lives.

The metric that matters is the distance in pixels between D1 and a
monotone-curvature construction at the same depth. All three, over all 720
positions:

| `r_m/r_h` | worst gap vs F6 | at | worst reverse turn | at | worst lobe | at |
|---:|---:|---:|---:|---:|---:|---:|
| 1.00 | 0.90 px | delta 52 | 1.68 deg | delta 21 | 0.6% | delta 47 |
| 1.20 (**current**) | 1.14 | 51 | 1.91 | 24 | 2.6% | 71 |
| 1.50 | 1.33 | 50 | 2.77 | 47 | 8.7% | 99 |
| 2.00 | 2.64 | 52 | 4.91 | 61 | 19.6% | 133 |
| 2.50 | 4.16 | 58 | 6.50 | 68 | 27.9% | 149 |

The three peak at different separations, and the visible one is consistently
around `delta` 50 to 60 -- the half-open hand position, not opposition. Two
further notes:

- The reverse turn and the lobe are **exactly scale-invariant**: 1.91 deg and
  2.6% at `r_h` of 0.20, 0.30, 0.45 and 0.60, all at ratio 1.20. The pixel gap
  is not, because it is a length: 0.51, 0.76, 1.14, 1.52 px for those same
  radii. **Longer stems make the same defect more visible.**
- Section 28's sweep set the hand tips just past the stem starts, which makes
  the drawn hands almost nonexistent. It does not change the connector -- D1's
  rule reads only `r_h`, `r_m` and `cos(delta)` -- but the numbers above use
  realistic hand lengths, and the ratio bands from section 28 stand unchanged.

At the current ratio the worst visible deviation is **1.14 px**, and at
`r_h = 0.45R` the reverse bend is a 1.91 degree turn concentrated near the stem
junction at `delta = 24`. That is small, and it is not nothing: it is the only
defect in this whole exercise that a person can see, and it is the one thing
prescribed curvature removes outright.

# Round 6: depth headroom, and a stem-ratio budget

## 31. Allowing more depth does not help -- depth and smoothness are one axis

Both F6 and A1 are driven to D1's depth. The obvious question is whether
relaxing that upward away from the two degenerate ends would buy anything. It
does not, and the reason is structural rather than incidental: a deeper corner
needs a *flatter* `k`, because a flat-topped curvature profile turns the same
total angle at a lower peak and so cuts less deeply toward the centre. Depth and
curvature-flatness are the same axis, read in opposite directions. Scaling
D1's depth rule by a multiplier and asking F6 for the smoothest taper that still
reaches it:

| depth x | pure raised cosine (no plateau) out to | reachable at all out to |
|---:|---:|---:|
| 0.70 | delta 123 | everywhere |
| 0.85 | delta 97 | everywhere |
| **1.00** | **delta 82** | **everywhere** |
| 1.15 | delta 72 | delta 120 |
| 1.30 | delta 64 | delta 100 |

More depth costs the plateau-free shape immediately, and past about 1.15x it
becomes unreachable outright -- *no* single-signed unimodal curvature profile
gets there. That last bound is exact and worth stating on its own: D1's rule is
`arc_apex_ceiling * sin(delta/2)`, and `arc_apex_ceiling` is the deepest a
constant-curvature corner can sit, so the available multiplier is at most
`1 / sin(delta/2)` -- which is **1.0 at opposition**. D1's depth rule is already
against the geometric ceiling there; the headroom only exists in the mid-range,
and spending it costs the shape.

Going the other way is a real option: at 0.85x the depth, F6 keeps a pure
raised cosine out to `delta = 97` instead of 82. That is a legitimate trade -- a
slightly shallower, more uniformly-curved connector -- but it is shallower than
D1 everywhere, which is the opposite of the "swoopier" preference.

## 32. A stem-ratio budget from the reverse turn

Sheet: `d1-worst.svg`, rebuilt to centre its zooms on the hardest reversing
vertex rather than on the widest gap -- the gap peaks around `delta` 50 while the
reverse bend sits near the stem junction, so the earlier framing was showing the
wrong place.

The reverse turn in degrees is exactly scale-invariant. The deviation it
produces in pixels is not, because it is a length, so a budget has to be checked
at the largest stems that fit -- with the current hands (`0.60R` and `0.90R`)
and a stem starting no further than 95% up its own hand, that is
`r_h <= 0.57`, `r_m <= 0.855`:

| `r_m/r_h` | worst turn | deviation, moderate stems | deviation, largest stems | at |
|---:|---:|---:|---:|---:|
| 1.00 | 1.68 deg | 0.10 px | 0.12 px | delta 21 |
| 1.20 (**current**) | 1.91 | 0.24 | 0.30 | 24 |
| 1.40 | 2.32 | 0.42 | 0.53 | 45 |
| 1.55 | **3.00** | 0.67 | **0.93** | 49 |
| 1.77 | **3.99** | 0.85 | **1.12** | 58 |
| 2.00 | 4.91 | 1.34 | 1.66 | 61 |
| 2.50 | 6.50 | 1.82 | 2.01 | 68 |

So, as a budget on the ratio (symmetric under swapping, since the defect depends
only on `|log(r_m/r_h)|`):

- **3 degrees**: `r_m/r_h` within **[0.65, 1.55]**, worst deviation 0.93 px
- **4 degrees**: within **[0.56, 1.77]**, worst deviation 1.12 px

The current 0.45 / 0.54 is at ratio 1.20 -- 1.91 degrees and 0.30 px at the
largest stems, comfortably inside either budget with room to grow the asymmetry
by about 30% before hitting the 3 degree line. Note also that the position of
the worst turn migrates outward with the ratio, from `delta = 21` at symmetry to
`delta = 68` at ratio 2.5, so a ratio change moves *when* in the hour the defect
shows as well as how much.

Two caveats on reading the budget. It is a budget for *keeping D1*: prescribed
curvature removes the reverse turn entirely at every ratio, so the constraint
only exists if the cubic architecture stays. And the pixel column assumes the
current hand lengths; longer hands admit larger stems, and the same ratio then
costs more pixels.

# Round 7: D1 shipped

## 33. What went into main.c

D1 replaces the pivot rule outright. The whole of it:

    s = min(r_h, r_m) * cos(d/2) * sin(d/2) / (1 + sin(d/2))
    P = C + s * unit(u_h + u_m)

Three changes in `src/c/main.c`, nothing else touched:

- `calculate_pivot_point` rewritten. It now takes the two **connector points**
  rather than the hand tips, because the rule depends on where the stems end,
  not on where the hands end, and it no longer takes `maximum_radius` at all.
- The connector points are computed before the pivot in `build_centerline`
  instead of after it, so they are available to pass in.
- `MAX_PIVOT_OFFSET_RATIO`, `PIVOT_PULL_BIAS` and `shape_pivot_pull` are gone.
  Those were the four tuned constants: two literals and the two functional
  forms wrapped around them.

Note what is *not* in the diff. The minimum-bending tangent solve, the Hermite
evaluation, the stroke width profile and the polygon construction are all
untouched -- the pivot was the only thing under discussion, and it is the only
thing that moved.

The derivation is section 9 for the ceiling and section 11 for the
`sin(delta/2)` factor. Two details of the C are worth flagging:

- `cos/(1 + sin)` rather than the algebraically identical `(1 - sin)/cos`: no
  0/0 at opposition, and the whole rule then needs nothing but square roots, so
  `square_root_float()` covers it and no `atan` is required.
- Both degenerate ends fall out rather than being special-cased. At overlap
  `sin(d/2)` is zero, so the offset is zero and the pivot is exactly on the
  centre. At opposition the bisector itself vanishes, which the existing
  `VECTOR_EPSILON` guard already returns the centre for -- and `cos(d/2)` would
  have given zero anyway, so the guard and the formula agree.

Verified by `tools/preview/check_c_pivot.py`, which lifts the function and its
vector helpers verbatim out of `main.c`, compiles them with
`-Wall -Wextra -Werror`, and compares against `geometry.py`'s D1 at every hand
position in all six stem configurations: **4320 cases, worst disagreement
3.2e-4 px** (float32 against float64), and the pivot is *exactly* on the centre
at overlap in every configuration. The minimum-bending solve never falls back
and the pivot index never leaves its valid range, both over all 720 positions.

Depth against the rule it replaces, on the shipped stems:

| delta | D1 | old rule |
|---:|---:|---:|
| 0 | 0.00 | 0.00 |
| 27.5 | 8.39 | 8.32 |
| 66 | 13.31 | 12.92 |
| 88 | 13.27 | 12.72 |
| 121 | 10.31 | 9.47 |
| 154 | 5.00 | 3.84 |

Close through the middle and progressively deeper past quadrature, which is the
band where the old rule's face-anchored scaling was pulling the pivot in.

## 34. Pending: the stem-ratio constraint for a settings page

The decision, to be enforced wherever the stems become user-settable:

    3/5 <= r_m / r_h <= 5/3

Both endpoints give the same worst reverse turn, **3.54 degrees** at
`delta = 55` -- the range is symmetric because the defect depends only on
`|log(r_m/r_h)|` (section 32). That sits between the 3 degree band
(`[0.65, 1.55]`) and the 4 degree band (`[0.56, 1.77]`), so it is a deliberate
choice of about 3.5 degrees rather than a reading off either table.

Not implemented: `main.c` still has `HOUR_STEM_RATIO` and `MINUTE_STEM_RATIO`
as fixed literals, so there is nothing yet to constrain. When they become
settings, the constraint belongs on the ratio of the resulting inner radii
`r_h = L_h (1 - stem_h)` and `r_m = L_m (1 - stem_m)`, not on the stem ratios
themselves -- the hand lengths are in between.

## 35. What a rebuild costs

Measured with `tools/preview/check_c_build.py`, which compiles the geometry half
of `main.c` on its own and runs the per-minute rebuild for all 720 hand
positions. `square_root_float()` is the dominant arithmetic, so its call count
is the figure that transfers to the watch; the microseconds are a desktop
number and mean nothing on ARM.

**Per rebuild: 205 square roots, 615 divisions inside them.** Where they go:

| | square roots per rebuild |
|---|---:|
| `build_centerline` (including the pivot and both 4x4 solves) | 14 |
| `update_cumulative_lengths` | 48 |
| `calculate_centerline_tangent`, over the 49 polygon points | 143 |

The structure around it is already about as tight as it can be, and none of
this is worth touching:

- All storage is static -- `s_centerline`, `s_cumulative_length`,
  `s_polygon_points` and the solver workspace come to roughly 1.2 KB, and there
  is no allocation at runtime at all.
- `gpath_create` runs once in `init()` and `gpath_destroy` once in `deinit()`.
  No path churn per frame.
- The tick subscription is `MINUTE_UNIT`, so there are no per-second wakeups,
  and `ensure_geometry` caches on a `time_key` of `hour % 12 * 60 + minute`.
  A rebuild happens once a minute and the draw proc hits the cache.
- The solver workspace's fixed sparse entries are set once at init, not per
  rebuild.

**`square_root_float`'s three Newton steps are exactly right.** From the
exponent-halving seed, worst-case relative error over the range the geometry
actually feeds it:

| Newton steps | relative error |
|---:|---:|
| 0 (seed only) | 6.1e-2 |
| 1 | 1.7e-3 |
| 2 | 1.6e-6 |
| **3 (shipped)** | **8.9e-8** |
| 4 | 8.9e-8 |

`FLT_EPSILON` is 1.19e-7, so three steps reach float precision and a fourth
gains nothing, while two would be thirteen times too coarse. On hardware with
an FPU a single `sqrtf()` would be several times faster than this, but that is
a deliberate portability choice and it is documented as one.

### The one real redundancy, and why it is still not worth it

`calculate_centerline_tangent` recomputes the two adjacent segment lengths at
every polygon point -- lengths `update_cumulative_lengths` has just finished
computing. Caching the per-segment unit direction there instead drops the
rebuild from **205 square roots to 109** and from 615 divisions to 327, and it
shortens `calculate_centerline_tangent` from about seventy lines with four
epsilon branches to twenty-five with one. Verified in the harness to produce a
**bit-identical polygon**.

It is still 96 square roots once a minute. Not a reason on its own to touch
working code; worth doing if that function is being edited anyway.

The same applies, smaller, to `calculate_pivot_point`: it recomputes the two
radial directions, `radial_dot` and the two inner radii that `build_centerline`
already has or computes later for `branch_clearance`, which is six of the 205.
Reusing them would agree to 2.7e-7 in the unit vectors -- about 1e-5 px on the
pivot -- so it is free to do, and it is deliberately not done. See section 36:
the original pivot function recomputed exactly the same radials and
`radial_dot`, so this is the file's convention rather than a slip in one
place.

## 36. Why the redundancy is there

Worth answering, because it decides whether removing it is a fix or a
disagreement about style. Four pieces of evidence, and they point the same way.

**There is no history to read.** `git log` on `src/c/main.c` is one commit,
"Initial commit", and then the D1 change. The file arrived whole, so intent has
to be inferred from its structure rather than from how it got that way. The
header also records that it was written with AI assistance, which plausibly
favours locally self-contained functions over state threaded between them.

**The file's own section headers assign ownership.** `s_cumulative_length` is
declared under `/* Arc-length cache */`; `calculate_centerline_tangent` lives
under `/* Stroke polygon */`. The tangent function does not reach into another
section's state, and the redundancy is exactly what that boundary costs.

**The original pivot function did the same thing, deliberately.** Before D1,
`calculate_pivot_point` took the hand tips and recomputed both radial
directions with `direction_between(center, ...)` and then `radial_dot` -- all
three of which `build_centerline` already had in hand at the call site, and
`radial_dot` again later for `branch_clearance`. So self-containment is the
convention across the file, not an oversight in `calculate_centerline_tangent`.
D1 follows it, which is why the new pivot derives its own radials and inner
radii too.

**`calculate_centerline_tangent` is written defensively about its inputs, and
one of those guards is load-bearing.** It has four epsilon branches. Measured
over all 720 hand positions:

| branch | hits per full cycle |
|---|---:|
| both adjacent segments degenerate | 0 |
| incoming segment degenerate | 0 |
| outgoing segment degenerate | 0 |
| the two unit directions cancel | **1** |

The shortest segment anywhere in the cycle is **0.0315 px** against a
`VECTOR_EPSILON` of 1e-4, a margin of 315x, so the three length guards are
dead code. The fourth fires exactly once, at **12:00, centerline index 22** --
which is the pivot index at exact overlap, where the fold reverses direction by
180 degrees and the incoming and outgoing tangents are precisely antiparallel.
That is the degenerate hairpin the whole design is built around, and it is
handled in the one place a caller would never think to check.

So the reading is: these are functions written to be correct on their own terms,
independent of who calls them and in what order, composed out of the
one-line `distance_between` / `direction_between` primitives. The recomputation
is the price of that, and at 205 square roots a minute it is a price the design
can afford without anyone having to notice.

**Which is also the argument against the optimisation.** As written,
`calculate_centerline_tangent` depends only on `s_centerline` and an index, so
it is correct whenever the centerline is filled. Caching per-segment directions
would give it a hidden ordering requirement -- valid only after
`update_cumulative_lengths()` -- in exchange for 96 square roots a minute. That
is a worse trade than the raw numbers suggest, and it is the reason to leave it
alone rather than the arithmetic.

# Round 8: the envelope

## 37. What the envelope is made of

The stroke is the centerline offset by half a width profile, filled as a
98-point polygon. Six constants shape it, plus one that is a rendering
correction rather than an aesthetic choice:

| | | |
|---|---:|---|
| `HOUR_TIP_WIDTH` | 3.0 px | width at the hour tip |
| `HOUR_BODY_WIDTH` | 6.0 px | the swell just inside it |
| `MIDDLE_WIDTH` | 3.0 px | at the pivot |
| `MINUTE_TIP_WIDTH` | 1.0 px | at the minute tip |
| `HOUR_SWELL_POSITION` | 0.05 | where the swell peaks, as a fraction of total arc |
| `PRESSURE_VARIATION` | 0.20 | a brush-pressure asymmetry about the pivot |
| `OUTLINE_WIDTH_COMPENSATION` | 1.0 px | keep: see below |

Three passes draw it, and reading only the first is misleading. The fill is
inset by `OUTLINE_WIDTH_COMPENSATION` so the antialiased outline pass puts that
pixel back, which means **the width profile is the composite ink extent and the
filled polygon is one pixel narrower.** At the minute tip the profile is 1 px,
so the fill has *zero* width there and the minute hand is carried entirely by
the outline plus the hard one-pixel core line. That is why the minute hand is a
hairline: it is the pen's thinnest possible mark, one pixel, by construction.

Sheet: `envelope.svg` and `envelope-zoom.svg`, rendered from `main.c`'s own
polygon rather than a re-port.

## 38. Three things measured, one of which is a no-op

**`PRESSURE_VARIATION` does nothing.** The term is
`w *= 1 + 0.20 * 4p(1-p) * (pivot_position - p)`. Over all 720 positions and
every sample its multiplier stays between 0.945 and 1.026, and **the largest
change it makes to any width is 0.133 px.** On a face with unantialiased fills
that cannot survive rasterization. At the hour stem junction it is constant to
four decimal places across the whole day (1.0216 to 1.0219). It costs a
constant and buys nothing measurable: delete it, or raise it until it is
visible and decide whether the asymmetry is wanted. As written it is neither.

**The anti-blob term is inert, because it measures the wrong distance.**
`branch_clearance = 2 min(r_h, r_m) sin(delta/2)` is the chord between the two
*stem ends* -- about 45 px at `delta = 30` -- and it is compared against
`MIDDLE_WIDTH`, 3 px. So `center_width_scale` saturates at 1 for
`delta > 3.5` and is doing nothing at **705 of 720 positions.** What it was
presumably meant to prevent is happening anyway, further out than it reaches:

| | extent |
|---|---|
| ink collides with a non-adjacent part of the stroke | out to `delta = 18.5` (75 of 720 positions) |
| the fill polygon's inner offset inverts (cusps) | out to `delta = 24.5` (92 of 720) |
| `center_width_scale` still below 1 | only `delta <= 3.5` |

The closest approach between the two *branches* is nothing like the chord
between the stem ends, which is why the calibration misses.

**The swell drifts with the time.** `HOUR_SWELL_POSITION` is a fraction of
*total* sweep arc length, and that length swings 15% over the hour (130.8 to
150.0 px). So the swell peak slides between 6.54 and 7.50 px from the hour tip,
across 6% of the hour stem's 15 px. Small, but it is the same class of mistake
as the pivot rule the face radius used to anchor: a feature of one hand
positioned by a length belonging to the whole sweep. Anchoring it to the hour
stem's own length makes it time-invariant and costs nothing.

## 39. Two hypotheses of mine that measurement killed

Recorded because both were plausible and both were wrong.

**"The stems waste samples; reallocating them by arc length would smooth the
outline."** Backwards. The connector's 30 samples are placed uniformly in the
Hermite parameter, not in arc length, so the arc-length spacing within it
varies by up to 39x at `delta = 5.5` -- and the samples bunch exactly where the
Hermite speed is low, which is where the curvature is highest. That is the right
place for them. At the worst well-conditioned position the step is 0.99 px and
the inner-offset sagitta 0.116 px; arc-length-even spacing there would be
2.73 px and 0.884 px, **7.6 times worse.** Uniform-in-`t` is doing useful work.

**"49 samples may be too few for the outline, whose curvature the offset
amplifies."** No: the worst inner-offset sagitta anywhere the offset is
well conditioned is **0.116 px**. `CONNECTOR_SEGMENTS = 30` is not a
bottleneck. (A naive version of this metric reports 13.9 px, but that is the
formula dividing by a near-zero inner radius right at the cusp condition, which
is the cusp being rediscovered, not faceting.)

## 40. What could actually be de-parametrized

**The four widths are already a ratio ladder, and only need saying so.**
In units of the smallest: minute tip 1, middle 3, hour tip 3, hour body 6. So
`MIDDLE_WIDTH == HOUR_TIP_WIDTH` and `HOUR_BODY_WIDTH == 2 * MIDDLE_WIDTH`
exactly. That is **one** parameter -- a one-pixel pen unit -- and three small
integers, not four independent floats. Naming it that way removes most of the
apparent arbitrariness without changing a pixel, and it makes the design
intent legible: the stroke runs from six pen units at the hour body down to one
at the minute tip.

**The derived ceiling, and why it is not a drop-in.** The structural analogue of
`arc_apex_ceiling` exists here. The room available at any sample is its distance
to the nearest non-adjacent part of the centerline,

    clearance(s) = min over |t - s| > eps of |P(s) - P(t)|

and capping `w(s) <= clearance(s)` makes self-overlap impossible: if
`w(s) <= clearance(s)` everywhere then for any pair,
`(w(s) + w(t))/2 <= (clearance(s) + clearance(t))/2 <= |P(s) - P(t)|`. Adding
`w(s) <= 2 R(s)` also rules out the inner-offset cusp. Both are constant-free
and derived from the construction, and together they would replace
`center_width_scale` with something that actually binds where the problem is.

But it cannot be applied as a hard cap, because at overlap `clearance` goes to
zero and the design *requires* the fold to overlap itself -- capping there would
make the stroke vanish exactly where it should be a single confident mark. So
the ceiling is a diagnostic and a bound to spend, not a limiter, and how to
spend it is a design decision rather than a derivation.

**The nib model is the textbook answer and it is wrong here.** A broad-edged
pen gives `w = W |sin(theta - theta_nib)|`, which would replace the whole
profile with two parameters and generate thick-and-thin from the geometry. On a
clock it fails: the hands rotate, so the weight depends on absolute direction
and the minute hand would pass through the nib's null twice an hour, nearly
vanishing each time. A watchface cannot have its minute hand disappear at 07
and 37 past. Worth stating explicitly because it is the first idea anyone has.

## 41. The open question, which is a design decision

Through roughly `delta = 2` to `20` the two arms are *partially* merged: close
enough that the ink joins, far enough apart that a waist shows between two
lobes. The sheet shows it clearly at 12:02 and 12:03. That is arguably the least
attractive state available -- neither a clean fold nor two clean arms -- and it
is currently reached by default rather than by decision, because the term meant
to govern it stopped acting at `delta = 3.5`.

The choice is which way to resolve it:

- **merge harder** -- let the width grow through that band so it reads as one
  confident stroke doubling back, which is what a broad pen actually does in a
  hairpin, or
- **separate cleanly** -- spend the clearance ceiling to thin both arms through
  the band so two strokes read distinctly.

Either is defensible and they look quite different. This is where "natural" gets
decided, and it is not a question measurement can settle.
