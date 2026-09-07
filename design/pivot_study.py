#!/usr/bin/env python3
"""
Pivot-geometry study for the Calligraphy watchface.

Renders the *centerline* only (no width envelope) for a set of candidate
constructions of the central connector, across representative hand angles.

Everything is expressed in watch units: R = maximum_radius = min(w,h)/2.
For emery / gabbro (200 x 228) that is R = 100 px.

Screen coordinates: x right, y down, angle 0 = 12 o'clock, increasing clockwise.
"""

import math

# --------------------------------------------------------------------------
# Constants mirroring src/c/main.c
# --------------------------------------------------------------------------

R = 100.0

HOUR_LENGTH_RATIO = 0.60
MINUTE_LENGTH_RATIO = 0.90
HOUR_STEM_RATIO = 0.25
MINUTE_STEM_RATIO = 0.40

MAX_PIVOT_OFFSET_RATIO = 0.15
PIVOT_PULL_BIAS = 0.50

HOUR_STEM_SEGMENTS = 8
CONNECTOR_SEGMENTS = 30
MINUTE_STEM_SEGMENTS = 10
CENTERLINE_POINT_COUNT = HOUR_STEM_SEGMENTS + CONNECTOR_SEGMENTS + MINUTE_STEM_SEGMENTS + 1

SOLVER_REGULARIZATION = 1e-4
SOLVER_EPSILON = 1e-5
MAX_SOLVER_RESULT_MAGNITUDE = 100.0

HOUR_LENGTH = R * HOUR_LENGTH_RATIO            # 60
MINUTE_LENGTH = R * MINUTE_LENGTH_RATIO        # 90
R_A = HOUR_LENGTH * (1.0 - HOUR_STEM_RATIO)    # 45  inner end of hour stem
R_B = MINUTE_LENGTH * (1.0 - MINUTE_STEM_RATIO)  # 54  inner end of minute stem

# --------------------------------------------------------------------------
# Small vector helpers (tuples)
# --------------------------------------------------------------------------

def add(a, b):  return (a[0] + b[0], a[1] + b[1])
def sub(a, b):  return (a[0] - b[0], a[1] - b[1])
def mul(a, k):  return (a[0] * k, a[1] * k)
def dot(a, b):  return a[0] * b[0] + a[1] * b[1]
def norm(a):    return math.hypot(a[0], a[1])

def unit(a):
    n = norm(a)
    return (0.0, -1.0) if n < 1e-9 else (a[0] / n, a[1] / n)

def dir_between(a, b):
    return unit(sub(b, a))

def ray(angle):
    """Unit vector at a clock angle (0 = up, clockwise positive)."""
    return (math.sin(angle), -math.cos(angle))

def on_clock(angle, length):
    u = ray(angle)
    return (u[0] * length, u[1] * length)

def wrap_pi(a):
    return (a + math.pi) % (2.0 * math.pi) - math.pi

def smoothstep(x):
    x = 0.0 if x < 0.0 else (1.0 if x > 1.0 else x)
    return x * x * (3.0 - 2.0 * x)

# --------------------------------------------------------------------------
# Clock angles
# --------------------------------------------------------------------------

def angles_for(hour, minute):
    th = 2.0 * math.pi * ((hour % 12) * 60 + minute) / (12.0 * 60.0)
    tm = 2.0 * math.pi * minute / 60.0
    return th, tm

def separation(th, tm):
    """Unsigned angle between the hands, [0, pi]."""
    return abs(wrap_pi(tm - th)) if abs(wrap_pi(tm - th)) <= math.pi else math.pi

def turn_angle(th, tm):
    """
    Signed tangent turn the connector must make: the incoming tangent is
    th + pi (heading inward along the hour ray), the outgoing tangent is tm.
    Result in [-pi, pi).
    """
    return wrap_pi(tm - th - math.pi)

# --------------------------------------------------------------------------
# Polyline utilities
# --------------------------------------------------------------------------

def resample(points, count):
    """Uniform arc-length resampling of a polyline."""
    if len(points) < 2:
        return [points[0]] * count
    cum = [0.0]
    for i in range(1, len(points)):
        cum.append(cum[-1] + norm(sub(points[i], points[i - 1])))
    total = cum[-1]
    if total < 1e-9:
        return [points[0]] * count
    out = []
    j = 0
    for k in range(count):
        target = total * k / (count - 1)
        while j < len(cum) - 2 and cum[j + 1] < target:
            j += 1
        span = cum[j + 1] - cum[j]
        t = 0.0 if span < 1e-12 else (target - cum[j]) / span
        out.append(add(points[j], mul(sub(points[j + 1], points[j]), t)))
    return out

def min_distance_to_origin(points):
    """Closest approach of the polyline to (0,0)."""
    best = float("inf")
    for i in range(len(points) - 1):
        a, b = points[i], points[i + 1]
        ab = sub(b, a)
        L2 = dot(ab, ab)
        if L2 < 1e-12:
            d = norm(a)
        else:
            t = max(0.0, min(1.0, -dot(a, ab) / L2))
            d = norm(add(a, mul(ab, t)))
        best = min(best, d)
    return best

def closest_point_to_origin(points):
    best, bp = float("inf"), points[0]
    for i in range(len(points) - 1):
        a, b = points[i], points[i + 1]
        ab = sub(b, a)
        L2 = dot(ab, ab)
        t = 0.0 if L2 < 1e-12 else max(0.0, min(1.0, -dot(a, ab) / L2))
        p = add(a, mul(ab, t))
        d = norm(p)
        if d < best:
            best, bp = d, p
    return bp

def max_turn_per_length(points):
    """Crude discrete curvature peak: max |dtheta|/ds over the polyline."""
    worst = 0.0
    for i in range(1, len(points) - 1):
        d0 = sub(points[i], points[i - 1])
        d1 = sub(points[i + 1], points[i])
        n0, n1 = norm(d0), norm(d1)
        if n0 < 1e-9 or n1 < 1e-9:
            continue
        c = max(-1.0, min(1.0, dot(d0, d1) / (n0 * n1)))
        worst = max(worst, math.acos(c) / (0.5 * (n0 + n1)))
    return worst

# ==========================================================================
# A. Faithful port of the shipping construction (src/c/main.c)
# ==========================================================================

def shape_pivot_pull(raw):
    x = max(0.0, min(1.0, raw))
    return x * (1.0 + PIVOT_PULL_BIAS) / (1.0 + PIVOT_PULL_BIAS * x)

def current_guide_point(hour_point, minute_point):
    """calculate_pivot_point() from main.c."""
    hr = unit(hour_point)
    mr = unit(minute_point)
    rd = max(-1.0, min(1.0, dot(hr, mr)))
    sine_sq = max(0.0, min(1.0, 1.0 - rd * rd))
    raw_pull = math.sqrt(sine_sq)
    shaped = shape_pivot_pull(raw_pull)
    dsum = add(hr, mr)
    dlen = norm(dsum)
    if dlen < 1e-4:
        return (0.0, 0.0)
    pull_dir = mul(dsum, 1.0 / dlen)
    bisector_strength = math.sqrt(max(0.0, min(1.0, dlen * 0.5)))
    offset = R * MAX_PIVOT_OFFSET_RATIO * shaped * bisector_strength
    return mul(pull_dir, offset)

def _solve4(aug):
    n = 4
    for pc in range(n):
        pr, best = pc, abs(aug[pc][pc])
        for r in range(pc + 1, n):
            if abs(aug[r][pc]) > best:
                best, pr = abs(aug[r][pc]), r
        if best < SOLVER_EPSILON:
            return False
        if pr != pc:
            aug[pc], aug[pr] = aug[pr], aug[pc]
        pv = aug[pc][pc]
        for c in range(pc, n + 1):
            aug[pc][c] /= pv
        for r in range(n):
            if r == pc:
                continue
            f = aug[r][pc]
            if abs(f) < SOLVER_EPSILON:
                continue
            for c in range(pc, n + 1):
                aug[r][c] -= f * aug[pc][c]
    return True

def _add_bending_segment(aug, p0, p1, L, sc, ec):
    inv = 1.0 / L
    inv2 = inv * inv
    chord = sub(p1, p0)
    for row in range(4):
        aug[row][4] += 12.0 * inv2 * dot(chord, add(sc[row], ec[row]))
        for col in range(4):
            same = dot(sc[row], sc[col]) + dot(ec[row], ec[col])
            cross = dot(sc[row], ec[col]) + dot(sc[col], ec[row])
            aug[row][col] += inv * (8.0 * same + 4.0 * cross)

Z = (0.0, 0.0)
UX = (1.0, 0.0)
UY = (0.0, 1.0)

def min_bending_derivatives(A, G, B, hour_in, minute_out, Lh, Lm):
    """calculate_minimum_bending_derivatives() from main.c."""
    aug = [[0.0] * 5 for _ in range(4)]
    hs = [hour_in, Z, Z, Z]
    he = [Z, UX, UY, Z]
    ms = [Z, UX, UY, Z]
    me = [Z, Z, Z, minute_out]
    _add_bending_segment(aug, A, G, Lh, hs, he)
    _add_bending_segment(aug, G, B, Lm, ms, me)
    for i in range(4):
        aug[i][i] += SOLVER_REGULARIZATION
    ok = _solve4(aug)
    if ok:
        for i in range(4):
            v = aug[i][4]
            if v != v or abs(v) > MAX_SOLVER_RESULT_MAGNITUDE:
                ok = False
    if ok:
        return (mul(hour_in, max(0.0, aug[0][4])),
                (aug[1][4], aug[2][4]),
                mul(minute_out, max(0.0, aug[3][4])))
    return (mul(hour_in, 0.5), dir_between(A, B), mul(minute_out, 0.5))

def hermite(p0, p1, d0, d1, L, t):
    t = max(0.0, min(1.0, t))
    t2, t3 = t * t, t * t * t
    h00 = 2 * t3 - 3 * t2 + 1
    h10 = t3 - 2 * t2 + t
    h01 = -2 * t3 + 3 * t2
    h11 = t3 - t2
    return (h00 * p0[0] + h10 * L * d0[0] + h01 * p1[0] + h11 * L * d1[0],
            h00 * p0[1] + h10 * L * d0[1] + h01 * p1[1] + h11 * L * d1[1])

def guide_hermite_connector(A, B, G, hour_in, minute_out, n=240):
    Lh = max(0.001, norm(sub(G, A)))
    Lm = max(0.001, norm(sub(B, G)))
    dh, dg, dm = min_bending_derivatives(A, G, B, hour_in, minute_out, Lh, Lm)
    pts = [hermite(A, G, dh, dg, Lh, i / (n // 2)) for i in range(n // 2 + 1)]
    pts += [hermite(G, B, dg, dm, Lm, i / (n // 2)) for i in range(1, n // 2 + 1)]
    return pts

# ==========================================================================
# B. Candidate constructions
# ==========================================================================
# Every method returns the complete centerline (hour tip -> minute tip),
# arc-length resampled to a common point count.

SAMPLES = 320

def frame(th, tm, ra=R_A, rb=R_B):
    return dict(
        hour_tip=on_clock(th, HOUR_LENGTH),
        minute_tip=on_clock(tm, MINUTE_LENGTH),
        A=on_clock(th, ra),
        B=on_clock(tm, rb),
        hour_in=mul(ray(th), -1.0),
        minute_out=ray(tm),
        theta=turn_angle(th, tm),
        delta=math.pi - abs(turn_angle(th, tm)),
    )

def assemble(f, connector):
    return resample([f["hour_tip"]] + connector + [f["minute_tip"]], SAMPLES)

# --- A0: shipping construction ------------------------------------------

def m_current(th, tm):
    f = frame(th, tm)
    G = current_guide_point(f["A"], f["B"])
    return assemble(f, guide_hermite_connector(
        f["A"], f["B"], G, f["hour_in"], f["minute_out"]))

# --- A1: same machinery, guide point pinned to the true centre ----------

def m_guide_center(th, tm):
    f = frame(th, tm)
    return assemble(f, guide_hermite_connector(
        f["A"], f["B"], (0.0, 0.0), f["hour_in"], f["minute_out"]))

# --- B1: corner conic, apex = true centre, weight = tan(turn / 2) -------

def conic_points(A, B, w, n=400):
    """Rational quadratic with control polygon A -> origin -> B."""
    pts = []
    for i in range(n + 1):
        t = i / n
        u, v = (1.0 - t), t
        num = (u * u * A[0] + v * v * B[0], u * u * A[1] + v * v * B[1])
        den = u * u + 2.0 * w * u * v + v * v
        pts.append((num[0] / den, num[1] / den))
    return pts

W_CAP = 4.0e3

def conic_weight_tan_half_turn(theta):
    h = abs(theta) * 0.5
    if h >= math.pi * 0.5 - 1e-6:
        return W_CAP
    return min(W_CAP, math.tan(h))

def m_conic(th, tm):
    f = frame(th, tm)
    w = conic_weight_tan_half_turn(f["theta"])
    return assemble(f, conic_points(f["A"], f["B"], w))

def m_conic_linear_cut(th, tm):
    """Same conic, but cut fraction rho = delta / pi  (w = 1/rho - 1)."""
    f = frame(th, tm)
    rho = f["delta"] / math.pi
    w = W_CAP if rho < 1.0 / W_CAP else min(W_CAP, 1.0 / rho - 1.0)
    return assemble(f, conic_points(f["A"], f["B"], w))

R_SYM = 0.50 * R

def m_conic_symmetric(th, tm):
    """Corner conic on a symmetric corner: both stems end at the same radius."""
    f = frame(th, tm, ra=R_SYM, rb=R_SYM)
    w = conic_weight_tan_half_turn(f["theta"])
    return assemble(f, conic_points(f["A"], f["B"], w))

# --- B2: cubic whose handles reach the centre ---------------------------

def bezier3(p0, p1, p2, p3, n=300):
    out = []
    for i in range(n + 1):
        t = i / n
        u = 1.0 - t
        b0, b1, b2, b3 = u**3, 3*u*u*t, 3*u*t*t, t**3
        out.append((b0*p0[0] + b1*p1[0] + b2*p2[0] + b3*p3[0],
                    b0*p0[1] + b1*p1[1] + b2*p2[1] + b3*p3[1]))
    return out

def m_cubic_reach(th, tm, lam=1.0):
    f = frame(th, tm)
    A, B = f["A"], f["B"]
    Q1 = mul(A, 1.0 - lam)
    Q2 = mul(B, 1.0 - lam)
    return assemble(f, bezier3(A, Q1, Q2, B))

def m_cubic_overshoot(th, tm):
    return m_cubic_reach(th, tm, lam=4.0 / 3.0)

# --- B3: equal-tangent circular biarc (negative control) ----------------

def arc_points(P, t, Q, n=80):
    """Circular arc from P (unit tangent t) to Q."""
    d = sub(Q, P)
    nrm = (-t[1], t[0])
    denom = 2.0 * dot(d, nrm)
    if abs(denom) < 1e-9:
        return [add(P, mul(d, i / n)) for i in range(n + 1)]
    r = dot(d, d) / denom
    C = add(P, mul(nrm, r))
    a0 = math.atan2(P[1] - C[1], P[0] - C[0])
    a1 = math.atan2(Q[1] - C[1], Q[0] - C[0])
    # pick the sweep consistent with the tangent direction
    sweep = wrap_pi(a1 - a0)
    cross = t[0] * (Q[1] - P[1]) - t[1] * (Q[0] - P[0])
    if (cross > 0) != (r > 0):
        pass
    if r > 0 and sweep < 0:
        sweep += 2 * math.pi
    if r < 0 and sweep > 0:
        sweep -= 2 * math.pi
    return [(C[0] + abs(r) * math.cos(a0 + sweep * i / n),
             C[1] + abs(r) * math.sin(a0 + sweep * i / n)) for i in range(n + 1)]

def m_biarc(th, tm):
    f = frame(th, tm)
    A, B, t0, t1 = f["A"], f["B"], f["hour_in"], f["minute_out"]
    V = sub(B, A)
    c = dot(t0, t1)
    s = dot(add(t0, t1), V)
    v2 = dot(V, V)
    k = 2.0 * (1.0 - c)
    if k < 1e-6:
        a = v2 / (2.0 * s) if abs(s) > 1e-9 else norm(V) * 0.5
    else:
        a = (-s + math.sqrt(max(0.0, s * s + k * v2))) / k
    a = max(1e-4, a)
    Q0 = add(A, mul(t0, a))
    Q1 = sub(B, mul(t1, a))
    J = mul(add(Q0, Q1), 0.5)
    seg = arc_points(A, t0, J) + arc_points(J, unit(sub(J, Q0)), B)[1:]
    return assemble(f, seg)

# --- C: signed-radius swing ---------------------------------------------

def swing_points(th, theta, h, u0=HOUR_LENGTH, u1=-MINUTE_LENGTH, n=600):
    """
    P(u) = u * ray(psi(u)) with u a *signed* radius running from +hour_length
    down through 0 to -minute_length, and the tangent angle psi turning by the
    full required turn `theta` across the radial window |u| <= h.
    Outside that window the curve is exactly a straight radial segment.
    """
    pts = []
    for i in range(n + 1):
        u = u0 + (u1 - u0) * i / n
        if h <= 1e-9:
            g = 0.0 if u > 0 else 1.0
        else:
            g = smoothstep((h - u) / (2.0 * h))
        psi = th + theta * g
        pts.append(mul(ray(psi), u))
    return pts

def make_swing(h):
    def f(th, tm):
        return resample(swing_points(th, turn_angle(th, tm), h), SAMPLES)
    return f

def m_swing_hard(th, tm):
    """h -> 0: two straight radial segments meeting at the exact centre."""
    return resample([on_clock(th, HOUR_LENGTH), (0.0, 0.0),
                     on_clock(tm, MINUTE_LENGTH)], SAMPLES)

# --- D: looping variant --------------------------------------------------

def m_loop(th, tm):
    theta = turn_angle(th, tm) - 2.0 * math.pi
    return resample(swing_points(th, theta, 0.30 * R, n=1200), SAMPLES)

# ==========================================================================
# E. Euler-spiral (clothoid) corner: kappa rises linearly to a peak and back
#    down to zero, so the join with the straight stems is G2. Two unknowns
#    (total length L, peak position m) are solved from the closure condition.
# ==========================================================================

def clothoid_shoot(A, phi0, theta, L, m, n=400):
    """Integrate a curve of length L whose curvature ramps 0 -> K -> 0."""
    m = min(0.95, max(0.05, m))
    K = 2.0 * theta / L
    x, y, phi = A[0], A[1], phi0
    ds = L / n
    pts = [(x, y)]
    for i in range(n):
        s = (i + 0.5) / n
        k = K * (s / m) if s < m else K * (1.0 - (s - m) / (1.0 - m))
        phi += k * ds
        x += math.cos(phi) * ds
        y += math.sin(phi) * ds
        pts.append((x, y))
    return pts

def m_clothoid(th, tm):
    f = frame(th, tm)
    A, B, t0 = f["A"], f["B"], f["hour_in"]
    phi0 = math.atan2(t0[1], t0[0])
    theta = f["theta"]
    L = max(6.0, norm(sub(B, A)) * 1.6 + abs(theta) * 12.0)
    m = 0.5
    for _ in range(80):
        e0 = sub(clothoid_shoot(A, phi0, theta, L, m, 200)[-1], B)
        if norm(e0) < 0.05:
            break
        hL, hm = max(0.05, L * 1e-3), 1e-3
        jL = mul(sub(sub(clothoid_shoot(A, phi0, theta, L + hL, m, 200)[-1], B), e0), 1.0 / hL)
        jm = mul(sub(sub(clothoid_shoot(A, phi0, theta, L, m + hm, 200)[-1], B), e0), 1.0 / hm)
        det = jL[0] * jm[1] - jL[1] * jm[0]
        if abs(det) < 1e-12:
            break
        dL = (-e0[0] * jm[1] + e0[1] * jm[0]) / det
        dm = (-jL[0] * e0[1] + jL[1] * e0[0]) / det
        step = 1.0
        while step > 0.02:
            nL, nm = L + step * dL, m + step * dm
            if nL > 1.0 and 0.02 < nm < 0.98:
                e1 = sub(clothoid_shoot(A, phi0, theta, nL, nm, 200)[-1], B)
                if norm(e1) < norm(e0):
                    L, m = nL, nm
                    break
            step *= 0.5
        else:
            break
    return assemble(f, clothoid_shoot(A, phi0, theta, L, m, 400))

# ==========================================================================
# F. SVG rendering
# ==========================================================================

def panel_svg(points, size=112, view=104.0, mark_fold=True, chrome=True):
    d = " ".join(f"{p[0]:.2f},{p[1]:.2f}" for p in points)
    fold = closest_point_to_origin(points)
    scale = view / 104.0
    body = []
    if chrome:
        body.append(f'<rect class="scr" x="-100" y="-114" width="200" height="228" rx="26"/>')
        body.append(f'<circle class="face" cx="0" cy="0" r="100"/>')
        for i in range(12):
            a = 2.0 * math.pi * i / 12.0
            u = ray(a)
            w = 3.0 if i % 3 == 0 else 1.6
            inner = 100 - (9 if i % 3 == 0 else 5)
            body.append(f'<line class="tk" x1="{u[0]*100:.1f}" y1="{u[1]*100:.1f}" '
                        f'x2="{u[0]*inner:.1f}" y2="{u[1]*inner:.1f}" stroke-width="{w}"/>')
    else:
        body.append(f'<rect class="scr" x="{-view}" y="{-view}" width="{2*view}" '
                    f'height="{2*view}" rx="{6*scale:.1f}"/>')
        for i in range(12):
            u = ray(2.0 * math.pi * i / 12.0)
            body.append(f'<line class="tk" x1="{u[0]*view*0.97:.1f}" y1="{u[1]*view*0.97:.1f}" '
                        f'x2="{u[0]*view*0.88:.1f}" y2="{u[1]*view*0.88:.1f}" '
                        f'stroke-width="{1.6*scale:.2f}"/>')
    body.append(f'<polyline class="ln" points="{d}" stroke-width="{2.6*scale:.2f}"/>')
    if mark_fold:
        body.append(f'<circle class="fold" cx="{fold[0]:.2f}" cy="{fold[1]:.2f}" '
                    f'r="{6.5*scale:.2f}" stroke-width="{1.6*scale:.2f}"/>')
    body.append(f'<circle class="pin" cx="0" cy="0" r="{3.2*scale:.2f}"/>')
    return (f'<svg viewBox="{-view} {-view} {2*view} {2*view}" width="{size}" height="{size}" '
            f'preserveAspectRatio="xMidYMid meet" aria-hidden="true">' + "".join(body) + '</svg>')


def offset_chart_svg(series, width=780, height=210, ymax=50.0):
    """series: list of (label, [(separation_degrees, offset_px)])."""
    top, bot, left, right = 14, 30, 34, 10
    iw, ih = width - left - right, height - top - bot
    parts = [f'<svg viewBox="0 0 {width} {height}" width="100%" '
             f'preserveAspectRatio="none" class="chart">']
    for v in (0, 10, 20, 30, 40, 50):
        y = top + ih * (1.0 - v / ymax)
        parts.append(f'<line class="grid" x1="{left}" y1="{y:.1f}" x2="{width-right}" y2="{y:.1f}"/>')
        parts.append(f'<text class="axis" x="{left-6}" y="{y+3.5:.1f}" text-anchor="end">{v}</text>')
    for a in range(0, 181, 30):
        x = left + iw * a / 180.0
        parts.append(f'<line class="grid vg" x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{top+ih}"/>')
        parts.append(f'<text class="axis" x="{x:.1f}" y="{height-13}" text-anchor="middle">{a}\u00b0</text>')
    parts.append(f'<text class="axis" x="{left+iw/2:.0f}" y="{height-2}" text-anchor="middle">'
                 f'angle between the hands</text>')
    for idx, (label, data) in enumerate(series):
        pts = " ".join(f"{left + iw*a/180.0:.2f},{top + ih*(1.0 - min(v, ymax)/ymax):.2f}"
                       for a, v in data)
        parts.append(f'<polyline class="s{idx}" points="{pts}"/>')
    parts.append("</svg>")
    return "".join(parts)


# ==========================================================================
# G. Extra variants added after the first render pass
# ==========================================================================

def m_guide_center_symmetric(th, tm):
    f = frame(th, tm, ra=R_SYM, rb=R_SYM)
    return assemble(f, guide_hermite_connector(
        f["A"], f["B"], (0.0, 0.0), f["hour_in"], f["minute_out"]))

def m_conic_pow(th, tm, p=2.0):
    """Corner conic with a hug exponent: w = tan(|Theta|/2) ** p."""
    f = frame(th, tm)
    w = min(W_CAP, conic_weight_tan_half_turn(f["theta"]) ** p)
    return assemble(f, conic_points(f["A"], f["B"], w))

def make_swing_constant_fold(rho0):
    """
    Turn window scaled so the radius of curvature at the fold is constant:
    kappa(0) = 1.5 * |Theta| / h  =>  h = 1.5 * rho0 * |Theta|.
    One constant with a physical reading: the pen's tightest turn.
    """
    def f(th, tm):
        theta = turn_angle(th, tm)
        h = 1.5 * rho0 * abs(theta)
        return resample(swing_points(th, theta, h), SAMPLES)
    return f

def make_shrinking_corner(inner=R_SYM, floor_frac=0.03):
    """
    Keep a smooth (hairpin-prone) connector, but shrink the corner region
    itself: the stems run in to radius r_c proportional to the hand
    separation, so as the hands converge the whole turn collapses onto the pin.
    """
    def f(th, tm):
        delta = math.pi - abs(turn_angle(th, tm))
        rc = inner * max(floor_frac, delta / math.pi)
        g = frame(th, tm, ra=rc, rb=rc)
        A, B, t0, t1 = g["A"], g["B"], g["hour_in"], g["minute_out"]
        V = sub(B, A)
        c = dot(t0, t1); s = dot(add(t0, t1), V); v2 = dot(V, V)
        k = 2.0 * (1.0 - c)
        if k < 1e-6:
            a = v2 / (2.0 * s) if abs(s) > 1e-9 else norm(V) * 0.5
        else:
            a = (-s + math.sqrt(max(0.0, s * s + k * v2))) / k
        a = max(1e-4, a)
        Q0 = add(A, mul(t0, a)); Q1 = sub(B, mul(t1, a))
        J = mul(add(Q0, Q1), 0.5)
        seg = arc_points(A, t0, J) + arc_points(J, unit(sub(J, Q0)), B)[1:]
        return assemble(g, seg)
    return f

def make_loop(h):
    def f(th, tm):
        theta = turn_angle(th, tm) - 2.0 * math.pi
        return resample(swing_points(th, theta, h, n=1400), SAMPLES)
    return f

def make_swing_by_separation(h1):
    """
    Turn window proportional to the hand separation: h = h1 * (Delta / pi).
    Delta = 0   -> h = 0    -> exact cusp on the pin (no loop)
    Delta = pi  -> straight line anyway
    One constant, and the rounding is read straight off the hand angle.
    """
    def f(th, tm):
        theta = turn_angle(th, tm)
        delta = math.pi - abs(theta)
        return resample(swing_points(th, theta, h1 * delta / math.pi), SAMPLES)
    return f

def _rdp(points, tol, keep, lo, hi):
    stack = [(lo, hi)]
    while stack:
        i, j = stack.pop()
        if j <= i + 1:
            continue
        a, b = points[i], points[j]
        ab = sub(b, a)
        L = norm(ab)
        worst, wk = -1.0, -1
        for k in range(i + 1, j):
            p = points[k]
            if L < 1e-9:
                d = norm(sub(p, a))
            else:
                d = abs(ab[0] * (a[1] - p[1]) - ab[1] * (a[0] - p[0])) / L
            if d > worst:
                worst, wk = d, k
        if worst > tol:
            keep[wk] = True
            stack.append((i, wk))
            stack.append((wk, j))


def simplify(points, tol=0.12):
    """
    Ramer-Douglas-Peucker, but cusps are pinned first: a stroke that doubles
    back along its own line is collinear, and plain RDP would erase the fold.
    """
    if len(points) < 3:
        return list(points)
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    breaks = [0]
    for k in range(1, len(points) - 1):
        d0 = sub(points[k], points[k - 1])
        d1 = sub(points[k + 1], points[k])
        n0, n1 = norm(d0), norm(d1)
        if n0 > 1e-9 and n1 > 1e-9 and dot(d0, d1) / (n0 * n1) < -0.5:
            keep[k] = True
            breaks.append(k)
    breaks.append(len(points) - 1)
    for a, b in zip(breaks, breaks[1:]):
        _rdp(points, tol, keep, a, b)
    return [p for p, k in zip(points, keep) if k]
