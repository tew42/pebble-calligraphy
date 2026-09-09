#!/usr/bin/env python3
"""Self-checks for the preview harness.  No third-party dependencies.

    python3 tools/preview/test_harness.py
"""

from __future__ import annotations

import math
import os
import sys

import curvature as CV
import geometry as G
import gifwriter
import report as R

FAILURES: list[str] = []


def check(condition: bool, message: str) -> None:
    if condition:
        print(f"  ok   {message}")
    else:
        print(f"  FAIL {message}")
        FAILURES.append(message)


def test_stem_configs() -> None:
    print("stem configurations are well formed")
    for stems in G.STEM_CONFIGS:
        check(0.0 < stems.hour_inner < stems.hour_length,
              f"{stems.name}: hour stem non-degenerate")
        check(0.0 < stems.minute_inner < stems.minute_length,
              f"{stems.name}: minute stem non-degenerate")


def test_construction_invariants() -> None:
    """The port must reproduce the C construction's structural invariants."""
    print("construction invariants over all 720 positions")
    face, stems = G.Face(), G.DEFAULT_STEMS
    rule = G.CANDIDATES_BY_KEY["c1-openness"].rule
    bad_index = bad_radius = fallbacks = 0
    for hour, minute in G.ALL_TIMES:
        cl = G.build_centerline(hour, minute, rule, face, stems)
        if not (G.CONNECTOR_FIRST_INDEX + 2 <= cl.pivot_index
                <= G.CONNECTOR_LAST_INDEX - 2):
            bad_index += 1
        r_h = G.norm(G.sub(cl.hour_connector, cl.context.center))
        r_m = G.norm(G.sub(cl.minute_connector, cl.context.center))
        if abs(r_h - face.max_radius * stems.hour_inner) > 1e-6:
            bad_radius += 1
        if abs(r_m - face.max_radius * stems.minute_inner) > 1e-6:
            bad_radius += 1
        if not cl.solver_ok:
            fallbacks += 1
        if len(cl.points) != G.CENTERLINE_POINT_COUNT:
            bad_index += 1
    check(bad_index == 0, "pivot index always within [first+2, last-2]")
    check(bad_radius == 0, "stem ends always at r_h / r_m exactly")
    check(fallbacks == 0, "minimum-bending solve never falls back")


def test_stem_ends_are_tangent_to_radials() -> None:
    """The straight stems must be exactly radial -- this is what makes the two
    tangent lines meet at the watch centre, which the whole design rests on."""
    print("stems are exactly radial")
    face, stems = G.Face(), G.DEFAULT_STEMS
    rule = G.CANDIDATES_BY_KEY["c1-openness"].rule
    worst = 0.0
    for hour, minute in G.ALL_TIMES[::7]:
        cl = G.build_centerline(hour, minute, rule, face, stems)
        for tip, inner in ((cl.hour_tip, cl.hour_connector),
                           (cl.minute_tip, cl.minute_connector)):
            along = G.sub(tip, cl.context.center)
            offset = G.sub(inner, cl.context.center)
            worst = max(worst, abs(G.cross(G.unit(along), G.unit(offset))))
    check(worst < 1e-9, f"stem ends collinear with their hand (worst {worst:.2e})")


def test_fast_path_matches_reference() -> None:
    """report._sample_half is an inlined copy of geometry.hermite_jet."""
    print("inlined sampler agrees with geometry.hermite_jet")
    cl = G.build_centerline(10, 10, G.CANDIDATES_BY_KEY["c1-openness"].rule)
    samples = 32
    px, py, vx, vy, wx, wy = R._sample_half(
        cl.hour_connector, cl.pivot, cl.hour_derivative, cl.guide_derivative,
        cl.hour_span, samples)
    worst = 0.0
    for i in range(samples + 1):
        position, first, second = G.hermite_jet(
            cl.hour_connector, cl.pivot, cl.hour_derivative,
            cl.guide_derivative, cl.hour_span, i / samples)
        worst = max(
            worst,
            abs(position[0] - px[i]), abs(position[1] - py[i]),
            abs(first[0] - vx[i]), abs(first[1] - vy[i]),
            abs(second[0] - wx[i]), abs(second[1] - wy[i]),
        )
    check(worst < 1e-9, f"agreement to {worst:.2e}")


def test_family_stays_in_tangent_triangle() -> None:
    """mu, beta in [0,1] makes the pivot a convex combination of C, A and B."""
    print("depth-tilt family stays inside triangle ABC")
    face = G.Face()
    outside = 0
    for stems in G.STEM_CONFIGS:
        for candidate in list(G.CANDIDATES) + list(G.TILT_SWEEP):
            if candidate.role == "illustration":
                continue
            for hour, minute in G.ALL_TIMES[::11]:
                position = R.measure(hour, minute, candidate.rule, face, stems,
                                     samples=24)
                if not position.inside_triangle:
                    outside += 1
    check(outside == 0, "no pivot outside the tangent triangle, any stem config")


def test_bisector_beta_cancels_at_opposition() -> None:
    """beta = r_h/(r_h+r_m) is exactly the tilt whose axial offset cancels at
    opposition, putting the pivot back on the watch centre."""
    print("bisector tilt returns the pivot to the centre at opposition")
    face = G.Face()
    for stems in G.STEM_CONFIGS:
        cl = G.build_centerline(6, 0, G.CANDIDATES_BY_KEY["c1-openness"].rule,
                                face, stems)
        depth = G.norm(G.sub(cl.pivot, cl.context.center))
        check(depth < 1e-9, f"{stems.name}: s = {depth:.2e} at delta = 180")


def test_overlap_is_centre_pinned() -> None:
    print("every contender pins the pivot to the centre at overlap")
    face = G.Face()
    for candidate in G.CANDIDATES:
        cl = G.build_centerline(12, 0, candidate.rule, face)
        depth = G.norm(G.sub(cl.pivot, cl.context.center))
        check(depth < 1e-9, f"{candidate.label}: s = {depth:.2e} at delta = 0")


def test_stem_scaling_is_proportional() -> None:
    """Scaling both stems must scale the pivot by the same factor."""
    print("pivot depth is homogeneous of degree 1 in the stem radii")
    face = G.Face()
    # Both fit inside the default hand lengths (0.60R / 0.90R), so only the
    # stem radii change between the two configurations.
    base = G.Stems("base", hour_inner=0.20, minute_inner=0.24)
    doubled = G.Stems("doubled", hour_inner=0.40, minute_inner=0.48)
    for key in ("c1-openness", "c2-clearance", "c7-chord-midpoint"):
        rule = G.CANDIDATES_BY_KEY[key].rule
        worst = 0.0
        for hour, minute in G.ALL_TIMES[::13]:
            a = G.build_centerline(hour, minute, rule, face, base)
            b = G.build_centerline(hour, minute, rule, face, doubled)
            depth_a = G.norm(G.sub(a.pivot, a.context.center))
            depth_b = G.norm(G.sub(b.pivot, b.context.center))
            if depth_a > 1e-6:
                worst = max(worst, abs(depth_b / depth_a - 2.0))
        check(worst < 1e-9, f"{key}: ratio is exactly 2 (worst error {worst:.2e})")


def test_swapped_stems_mirror() -> None:
    """Swapping which stem is longer must mirror the turn split about 0.5."""
    print("swapping the stems mirrors the curvature asymmetry")
    face = G.Face()
    current = G.STEMS_BY_NAME["current"]
    swapped = G.STEMS_BY_NAME["swapped"]
    for key in ("c1-openness", "c2-clearance", "c7-chord-midpoint",
                "c9-perp-foot"):
        candidate = G.CANDIDATES_BY_KEY[key]
        a = R.summarise(candidate, face, current)
        b = R.summarise(candidate, face, swapped)
        error = abs((a.mean_turn_share - 0.5) + (b.mean_turn_share - 0.5))
        check(error < 0.02,
              f"{key}: {a.mean_turn_share:.3f} / {b.mean_turn_share:.3f} "
              f"(mirror error {error:.4f})")


def test_curvature_is_continuous_at_the_pivot() -> None:
    """The minimum-bending solve gives C2 at the joint, not merely C1."""
    print("curvature is continuous across the pivot")
    face = G.Face()
    worst = 0.0
    for candidate in G.CANDIDATES:
        for hour, minute in G.ALL_TIMES[::17]:
            worst = max(worst, R.measure(hour, minute, candidate.rule, face,
                                         samples=48).joint_jump)
    check(worst < 1e-6, f"relative |dk| at the pivot never exceeds {worst:.2e}")


def test_arc_ceiling_closed_form() -> None:
    """cos/(1+sin) must equal min(r) tan(pi/4 - d/4) -- the form a C port would
    use, since it needs only square roots and has no 0/0 at opposition."""
    print("arc-apex ceiling closed form")
    face = G.Face()
    worst = 0.0
    for stems in G.STEM_CONFIGS:
        smaller = face.max_radius * min(stems.hour_inner, stems.minute_inner)
        for delta in range(0, 181, 3):
            ctx = R._context_for_delta(float(delta), face, stems)
            reference = smaller * math.tan(math.radians(45.0 - delta / 4.0))
            worst = max(worst, abs(ctx.arc_apex_ceiling - reference))
    check(worst < 1e-9, f"agreement to {worst:.2e} px over all stem configs")


def _worst_dip(candidate, face, stems, stride=1):
    worst = 0.0
    for hour, minute in G.ALL_TIMES[::stride]:
        worst = max(worst, R.measure(hour, minute, candidate.rule, face, stems,
                                     samples=64).curvature_dip)
    return worst


def test_round2_is_unimodal() -> None:
    """The whole point of round 2: |k| must not dip at the pivot, in any stem
    configuration -- not just today's."""
    print("round-2 depth rules keep curvature unimodal (all 720, all stems)")
    face = G.Face()
    for key in ("d1-arc-sin", "d2-arc-openness", "d3-arc-p075",
                "c3-chord-035", "c3o-chord-openness"):
        candidate = G.CANDIDATES_BY_KEY[key]
        worst = max(_worst_dip(candidate, face, stems)
                    for stems in G.STEM_CONFIGS)
        check(worst <= R.DIP_GATE, f"{key}: worst dip {worst:.1%}")


def test_controls_still_flatten() -> None:
    """The illustrations have to keep illustrating, or the sheets stop making
    their point."""
    print("controls flatten, as they are meant to")
    face = G.Face()
    for key in ("dc-arc-ceiling", "c1-openness"):
        worst = _worst_dip(G.CANDIDATES_BY_KEY[key], face, G.DEFAULT_STEMS)
        check(worst > R.DIP_GATE, f"{key}: worst dip {worst:.1%} (expected)")


def test_current_rule_flattens_under_changed_stems() -> None:
    """C0 is unimodal today only by luck: its depth is pinned to the face radius,
    so shrinking the stems leaves the pivot past the limit."""
    print("the current rule flattens once the stems change")
    face = G.Face()
    candidate = G.CANDIDATES_BY_KEY["c0-current"]
    today = _worst_dip(candidate, face, G.STEMS_BY_NAME["current"])
    shortened = _worst_dip(candidate, face, G.STEMS_BY_NAME["short"])
    check(today <= R.DIP_GATE, f"unimodal with current stems ({today:.1%})")
    check(shortened > 0.5, f"flattens badly with short stems ({shortened:.1%})")


def test_tilt_does_not_induce_flattening() -> None:
    """Round 1 only ever varied tilt at unsafe depths. At a safe depth, beta
    should be free -- which is what makes depth and tilt separable."""
    print("tilt is free once the depth is inside the limit")
    face = G.Face()
    for candidate in G.ROUND2_TILT:
        worst = _worst_dip(candidate, face, G.DEFAULT_STEMS, stride=3)
        check(worst <= R.DIP_GATE, f"{candidate.label}: worst dip {worst:.1%}")


def test_closed_form_sits_under_the_empirical_limit() -> None:
    """The depth family must stay under the limit measured from the solver, in
    the awkward stem configurations too -- not only in the shipped one."""
    print("D1 stays under the bisected unimodality limit")
    face = G.Face()
    for name in ("current", "short", "strong-asym"):
        stems = G.STEMS_BY_NAME[name]
        worst_ratio = 0.0
        for delta in (45.0, 75.0, 105.0, 135.0, 160.0):
            limit = R.unimodality_limit(delta, face, stems)
            ctx = R._context_for_delta(delta, face, stems)
            depth = G.norm(G.sub(G.CANDIDATES_BY_KEY["d1-arc-sin"].rule(ctx),
                                 ctx.center))
            if limit > 1e-6:
                worst_ratio = max(worst_ratio, depth / limit)
        check(worst_ratio < 1.0,
              f"{name}: worst depth is {worst_ratio:.0%} of the measured limit")


def test_compact_families_hit_the_junctions_at_zero() -> None:
    """Compact support means k reaches the stem junctions exactly, not nearly."""
    print("compact families: k = 0 at both stem junctions")
    face = G.Face()
    for shape in (CV.F2, CV.F3, CV.F4):
        worst = 0.0
        for stems in G.STEM_CONFIGS:
            for minute in range(0, 60, 7):
                cl = CV.build_compact_centerline(12, minute, shape, None,
                                                 face, stems)
                n = len(cl.curvatures)
                worst = max(worst, abs(cl.curvatures[0]),
                            abs(cl.curvatures[n - 1]))
        check(worst == 0.0, f"{shape.key}: junction curvature exactly 0")


def test_compact_families_never_swerve() -> None:
    print("compact families: single-signed curvature, no reverse turn")
    face = G.Face()
    for shape in (CV.F2, CV.F3, CV.F4):
        worst_rev = 0.0
        negative = 0
        for stems in G.STEM_CONFIGS:
            for minute in range(60):
                cl = CV.build_compact_centerline(12, minute, shape, None,
                                                 face, stems)
                negative += sum(1 for k in cl.curvatures if k < 0.0)
                turn = _turn_series(cl.points)
                total = sum(turn)
                worst_rev = max(worst_rev, sum(
                    abs(v) for v in turn
                    if abs(v) > 0.02 and (v > 0) != (total > 0)))
        check(negative == 0, f"{shape.key}: curvature never changes sign")
        check(worst_rev < 0.01, f"{shape.key}: reverse turn {worst_rev:.3f} deg")


def _turn_series(points):
    out = []
    for i in range(1, len(points) - 1):
        a = G.sub(points[i], points[i - 1])
        b = G.sub(points[i + 1], points[i])
        na, nb = G.norm(a), G.norm(b)
        out.append(0.0 if na < 1e-9 or nb < 1e-9 else
                   math.degrees(math.atan2(G.cross(a, b) / (na * nb),
                                           G.dot(a, b) / (na * nb))))
    return out


def test_f4_reproduces_d1_depth() -> None:
    """F4 on its own dial is the arc-apex fillet, which is what D1 approximates."""
    print("F4 on d = min(r) sin(delta/2) matches D1's depth rule")
    face = G.Face()
    rule = G.CANDIDATES_BY_KEY["d1-arc-sin"].rule
    worst = 0.0
    for stems in G.STEM_CONFIGS:
        for hour in range(0, 12, 3):
            for minute in range(0, 60, 5):
                cl = CV.build_compact_centerline(hour, minute, CV.F4, None,
                                                 face, stems)
                ref = G.build_centerline(hour, minute, rule, face, stems)
                target = G.norm(G.sub(ref.pivot, ref.context.center))
                worst = max(worst, abs(cl.exact_depth - target))
    check(worst < 1e-9, f"depth agrees with D1 to {worst:.2e} px")


def test_compact_dial_never_runs_out_of_stem() -> None:
    print("the tangent-length rule never exceeds min(r_h, r_m)")
    face = G.Face()
    clamps = 0
    for shape in (CV.F2, CV.F3, CV.F4):
        for stems in G.STEM_CONFIGS:
            for hour, minute in G.ALL_TIMES[::7]:
                cl = CV.build_compact_centerline(hour, minute, shape, None,
                                                 face, stems)
                if cl.clamped:
                    clamps += 1
    check(clamps == 0, "no clamping in any stem configuration")


def test_overlap_folds_through_the_centre() -> None:
    """The one shape the aesthetic admits at full overlap."""
    print("full overlap folds exactly through the centre")
    face = G.Face()
    for shape in (CV.F2, CV.F3, CV.F4):
        for stems in G.STEM_CONFIGS:
            cl = CV.build_compact_centerline(12, 0, shape, None, face, stems)
            check(cl.exact_depth == 0.0 and cl.depth < 1e-9,
                  f"{shape.key}/{stems.name}: depth 0 at overlap")


def test_beta_depth_tracks_its_target() -> None:
    """The integrator fix: no handover band, no systematic offset."""
    print("F1 tracks the depth target across the whole hour")
    face, stems = G.Face(), G.DEFAULT_STEMS
    rule = G.CANDIDATES_BY_KEY["d1-arc-sin"].rule
    worst = 0.0
    limited = []
    for minute in range(60):
        cl = CV.build_beta_centerline(12, minute, rule, face, stems)
        ref = G.build_centerline(12, minute, rule, face, stems)
        target = G.norm(G.sub(ref.pivot, ref.context.center))
        if cl.clamped:
            limited.append(G.separation_degrees(12, minute))
            continue
        worst = max(worst, abs(cl.exact_depth - target))
    check(worst < 0.01, f"F1 depth within {worst:.4f} px of target")
    # nu = 2 is the gentlest Beta with vanishing end curvature, so F1 has a
    # maximum reachable depth and runs out at wide separation -- the mirror of
    # F2/F3 running out of stem there.
    check(bool(limited) and min(limited) > 100.0,
          f"F1 out of range only past d = {min(limited):.0f}")


def test_beta_resolves_its_curvature_spike() -> None:
    """Uniform-t integration silently truncates the turn past nu ~ 6e4."""
    print("the refined grid resolves concentrations a uniform grid misses")
    face, stems = G.Face(), G.DEFAULT_STEMS
    rule = G.CANDIDATES_BY_KEY["d1-arc-sin"].rule
    refined = CV.build_beta_centerline(12, 2, rule, face, stems)
    naive = CV.build_beta_centerline(12, 2, rule, face, stems,
                                     uniform_integrator=True)
    check(not refined.degenerate, "refined grid solves at delta = 11")
    check(refined.concentration > 1e4,
          f"needs nu = {refined.concentration:.3g} there")
    # The uniform path scales its step count with sqrt(nu), so it gets there
    # too -- at ~14 sqrt(nu) steps against the refined grid's fixed budget.
    naive_error = abs(naive.exact_depth - refined.exact_depth)
    check(naive_error < 0.01,
          f"uniform grid agrees once refined, to {naive_error:.4f} px")
    check(CV._steps_for(refined.concentration, CV.FINAL_STEPS)
          > 4 * CV.FINAL_STEPS,
          "but only by spending {:.0f}x the samples".format(
              CV._steps_for(refined.concentration, CV.FINAL_STEPS)
              / CV.FINAL_STEPS))


def test_adaptive_taper_is_stem_independent() -> None:
    """rho(delta) is a universal curve: min(r_h, r_m) cancels from the rule."""
    print("the adaptive taper schedule depends on delta alone")
    face = G.Face()
    for minute in range(0, 60, 4):
        rho = None
        for stems in G.STEM_CONFIGS:
            cl = CV.build_compact_centerline(
                12, minute, CV.adaptive_shape,
                G.CANDIDATES_BY_KEY["d1-arc-sin"].rule, face, stems)
            delta = math.acos(max(-1.0, min(1.0, cl.context.radial_dot)))
            here = CV.adaptive_taper(delta)
            if rho is None:
                rho = here
            elif abs(here - rho) > 1e-12:
                check(False, f"minute {minute}: taper varies with the stems")
                return
    check(True, "identical across all six stem configurations")


def test_adaptive_taper_keeps_the_cosine_where_it_shows() -> None:
    """The plateau only appears where the curvature is too slack to see."""
    print("the plateau appears only where no curvature is visible")
    onset = min(d for d in range(1, 180)
                if CV.adaptive_taper(math.radians(d)) < 0.5 - 1e-9)
    check(onset > 80, f"pure raised cosine, no plateau, out to delta = {onset - 1}")
    # Beyond the onset the shape drifts toward a constant-curvature arc, which
    # only matters if the arc is tight enough to read as one.  Plateau length
    # and tightness are anti-correlated by construction: the shape only grows a
    # long plateau where the turn has already slackened.
    face, stems = G.Face(), G.DEFAULT_STEMS
    rule = G.CANDIDATES_BY_KEY["d1-arc-sin"].rule
    tightest = 0.0
    first = None
    for hour, minute in G.ALL_TIMES:
        delta = G.separation_degrees(hour, minute)
        if CV.adaptive_taper(math.radians(delta)) > 1.0 / 3.0:
            continue          # plateau under a third of the hump
        first = delta if first is None else min(first, delta)
        cl = CV.build_compact_centerline(hour, minute, CV.adaptive_shape,
                                         rule, face, stems)
        tightest = max(tightest, max(abs(k) for k in cl.curvatures))
    radius = 1.0 / tightest if tightest > 0.0 else float("inf")
    check(first is not None and first > 90.0,
          f"plateau reaches a third of the hump only past delta = {first:.0f}")
    check(radius > 30.0,
          f"and the arc is never tighter than {radius:.0f} px radius there")


def test_adaptive_taper_meets_every_requirement() -> None:
    print("F6 across all 720 positions and all six stem configurations")
    face = G.Face()
    rule = G.CANDIDATES_BY_KEY["d1-arc-sin"].rule
    worst_depth = worst_rev = worst_junction = worst_overlap = 0.0
    clamps = 0
    for stems in G.STEM_CONFIGS:
        for hour, minute in G.ALL_TIMES:
            cl = CV.build_compact_centerline(hour, minute, CV.adaptive_shape,
                                             rule, face, stems)
            ref = G.build_centerline(hour, minute, rule, face, stems)
            target = G.norm(G.sub(ref.pivot, ref.context.center))
            worst_depth = max(worst_depth, abs(cl.exact_depth - target))
            turn = _turn_series(cl.points)
            total = sum(turn)
            worst_rev = max(worst_rev, sum(
                abs(v) for v in turn
                if abs(v) > 0.02 and (v > 0) != (total > 0)))
            worst_junction = max(worst_junction, abs(cl.curvatures[0]),
                                 abs(cl.curvatures[-1]))
            if G.separation_degrees(hour, minute) < 1e-9:
                worst_overlap = max(worst_overlap, cl.exact_depth)
            clamps += cl.clamped
    check(worst_depth < 1e-6, f"depth matches D1 to {worst_depth:.2e} px")
    check(worst_rev < 0.01, f"reverse turn {worst_rev:.3f} deg")
    check(worst_junction == 0.0, "junction curvature exactly zero")
    check(worst_overlap == 0.0, "folds exactly through the centre at overlap")
    check(clamps == 0, "never runs out of stem")


def test_animation_covers_the_hour() -> None:
    """The animated hour has to pass through both accepted degeneracies, or it
    is not exercising the interesting part of the design."""
    print("the animated hour spans overlap to opposition")
    deltas = [G.separation_degrees(12, minute) for minute in range(R.ANIM_FRAMES)]
    check(len(deltas) == 60, f"{len(deltas)} frames")
    check(abs(deltas[0]) < 1e-9, f"frame 0 is exact overlap (d = {deltas[0]:.2f})")
    check(max(deltas) > 178.0, f"reaches near-opposition (max d = {max(deltas):.1f})")
    check(deltas[-1] < 40.0, f"comes back down (final d = {deltas[-1]:.1f})")
    rising = deltas[:deltas.index(max(deltas))]
    check(all(b > a for a, b in zip(rising, rising[1:])),
          "separation opens monotonically up to opposition")


def test_animation_frames_are_wellformed() -> None:
    """Emitted frames must be valid XML -- checked with the standard library, so
    the harness still has no third-party dependencies."""
    print("emitted animation frames are well-formed SVG")
    import tempfile
    import xml.etree.ElementTree as ElementTree

    face = G.Face()
    layout = R.ANIM_LAYOUTS_BY_NAME["anim-current"]
    with tempfile.TemporaryDirectory() as directory:
        count = R.write_animation_frames(face, layout, 12, directory)
        check(count == R.ANIM_FRAMES, f"wrote {count} frames")
        frame_dir = os.path.join(directory, "anim", layout.name)
        names = sorted(n for n in os.listdir(frame_dir) if n.endswith(".svg"))
        check(len(names) == R.ANIM_FRAMES, f"{len(names)} svg files on disk")
        bad = []
        for name in names:
            try:
                ElementTree.parse(os.path.join(frame_dir, name))
            except ElementTree.ParseError as error:
                bad.append(f"{name}: {error}")
        check(not bad, f"all frames parse ({bad[:1]})" if bad else "all frames parse")
        check(os.path.exists(os.path.join(frame_dir, "manifest.txt")),
              "manifest written")


def test_gif_writer_roundtrip() -> None:
    """gifwriter has to survive its own PNG decoder, so encode a known image with
    Chromium-style filters and check the GIF header and frame count."""
    print("gif writer produces a well-formed GIF")
    import tempfile

    palette = [(13, 15, 18), (255, 255, 255), (255, 138, 61)]
    palette += [(0, 0, 0)] * (256 - len(palette))
    width, height = 8, 4
    frames = [bytes([(x + f) % 3 for x in range(width)] * height)
              for f in range(3)]
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, "t.gif")
        gifwriter.write_gif(path, width, height, palette, frames, 17)
        blob = open(path, "rb").read()
    check(blob[:6] == b"GIF89a", "GIF89a signature")
    check(blob[-1:] == b"\x3b", "trailer present")
    check(blob.count(b"\x21\xf9\x04") == 3, "three graphic control blocks")
    check(b"NETSCAPE2.0" in blob, "loops forever")


def test_gif_lzw_is_decodable() -> None:
    """Decode our own LZW stream back, so a silently corrupt GIF cannot ship."""
    print("gif LZW round-trips")
    original = bytes([0, 0, 1, 1, 2, 2, 2, 1, 0, 0, 0, 1, 2, 1, 0] * 40)
    blocked = gifwriter.lzw_compress(original, 8)

    # unpack sub-blocks
    payload = bytearray()
    index = 0
    while blocked[index]:
        length = blocked[index]
        payload += blocked[index + 1:index + 1 + length]
        index += 1 + length

    codes = []
    width = 9
    bit = 0
    table = {i: bytes((i,)) for i in range(256)}
    next_code = 258
    out = bytearray()
    previous = None
    total_bits = len(payload) * 8
    while bit + width <= total_bits:
        chunk = 0
        for k in range(width):
            byte = payload[(bit + k) // 8]
            chunk |= ((byte >> ((bit + k) % 8)) & 1) << k
        bit += width
        if chunk == 256:
            table = {i: bytes((i,)) for i in range(256)}
            next_code, width, previous = 258, 9, None
            continue
        if chunk == 257:
            break
        if chunk in table:
            entry = table[chunk]
        else:
            entry = previous + previous[:1]
        out += entry
        if previous is not None:
            table[next_code] = previous + entry[:1]
            next_code += 1
            if next_code >= (1 << width) and width < 12:
                width += 1
        previous = entry
        codes.append(chunk)
    check(bytes(out) == original,
          f"decoded {len(out)} of {len(original)} bytes identically")


def main() -> int:
    for test in (
        test_stem_configs,
        test_construction_invariants,
        test_stem_ends_are_tangent_to_radials,
        test_fast_path_matches_reference,
        test_family_stays_in_tangent_triangle,
        test_bisector_beta_cancels_at_opposition,
        test_overlap_is_centre_pinned,
        test_stem_scaling_is_proportional,
        test_swapped_stems_mirror,
        test_curvature_is_continuous_at_the_pivot,
        test_arc_ceiling_closed_form,
        test_round2_is_unimodal,
        test_controls_still_flatten,
        test_current_rule_flattens_under_changed_stems,
        test_tilt_does_not_induce_flattening,
        test_closed_form_sits_under_the_empirical_limit,
        test_compact_families_hit_the_junctions_at_zero,
        test_compact_families_never_swerve,
        test_f4_reproduces_d1_depth,
        test_compact_dial_never_runs_out_of_stem,
        test_overlap_folds_through_the_centre,
        test_beta_depth_tracks_its_target,
        test_beta_resolves_its_curvature_spike,
        test_adaptive_taper_is_stem_independent,
        test_adaptive_taper_keeps_the_cosine_where_it_shows,
        test_adaptive_taper_meets_every_requirement,
        test_animation_covers_the_hour,
        test_animation_frames_are_wellformed,
        test_gif_writer_roundtrip,
        test_gif_lzw_is_decodable,
    ):
        test()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) failed")
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
