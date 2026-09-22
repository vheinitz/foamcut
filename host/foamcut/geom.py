"""Small 2D helpers for closed polylines (loops): orientation, containment,
intersections, convex hull, shortest path around obstacles."""
from __future__ import annotations

import heapq
import math

Point = tuple[float, float]
EPS = 1e-3          # mm, width of the slit that joins a hole to its outline


def signed_area(loop: list[Point]) -> float:
    n = len(loop)
    return 0.5 * sum(loop[i][0] * loop[(i + 1) % n][1] - loop[(i + 1) % n][0] * loop[i][1] for i in range(n))


def ccw(loop: list[Point]) -> list[Point]:
    return list(loop) if signed_area(loop) >= 0 else list(reversed(loop))


def dedupe(loop: list[Point], eps: float = 1e-6) -> list[Point]:
    out: list[Point] = []
    for p in loop:
        if not out or math.dist(out[-1], p) > eps:
            out.append(p)
    if len(out) > 1 and math.dist(out[0], out[-1]) <= eps:
        out.pop()
    return out


def inside(p: Point, loop: list[Point]) -> bool:
    """Even-odd point in polygon."""
    x, y = p
    n = len(loop)
    hit = False
    for i in range(n):
        (x1, y1), (x2, y2) = loop[i], loop[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xi = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if xi > x:
                hit = not hit
    return hit


def seg_dist(p: Point, a: Point, b: Point) -> float:
    """Distance from p to the segment a-b."""
    ax, ay = b[0] - a[0], b[1] - a[1]
    l2 = ax * ax + ay * ay
    t = 0.0 if l2 == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * ax + (p[1] - a[1]) * ay) / l2))
    return math.dist(p, (a[0] + ax * t, a[1] + ay * t))


def seg_intersect(a: Point, b: Point, c: Point, d: Point) -> float | None:
    """Parameter t along a->b where it crosses c->d, None if it does not."""
    r = (b[0] - a[0], b[1] - a[1]); s = (d[0] - c[0], d[1] - c[1])
    den = r[0] * s[1] - r[1] * s[0]
    if abs(den) < 1e-12:
        return None
    qp = (c[0] - a[0], c[1] - a[1])
    t = (qp[0] * s[1] - qp[1] * s[0]) / den
    u = (qp[0] * r[1] - qp[1] * r[0]) / den
    if 0.0 <= t <= 1.0 and 0.0 <= u <= 1.0:
        return t
    return None


def ray_hit(origin: Point, direction: Point, loop: list[Point]) -> tuple[float, int] | None:
    """Nearest crossing of the ray with the loop: (distance, edge index)."""
    n = len(loop)
    best = None
    far = (origin[0] + direction[0] * 1e6, origin[1] + direction[1] * 1e6)
    for i in range(n):
        t = seg_intersect(origin, far, loop[i], loop[(i + 1) % n])
        if t is not None and t > 1e-9 and (best is None or t < best[0]):
            best = (t * 1e6, i)
    return best


def crosses(a: Point, b: Point, loop: list[Point]) -> bool:
    n = len(loop)
    for i in range(n):
        if seg_intersect(a, b, loop[i], loop[(i + 1) % n]) is not None:
            return True
    return False


def convex_hull(pts: list[Point]) -> list[Point]:
    pts = sorted(set(pts))
    if len(pts) < 3:
        return pts

    def half(points):
        h: list[Point] = []
        for p in points:
            while len(h) >= 2 and (h[-1][0] - h[-2][0]) * (p[1] - h[-2][1]) - (h[-1][1] - h[-2][1]) * (p[0] - h[-2][0]) <= 0:
                h.pop()
            h.append(p)
        return h
    lower = half(pts); upper = half(reversed(pts))
    return lower[:-1] + upper[:-1]


def grow(loop: list[Point], d: float) -> list[Point]:
    """Convex CCW loop pushed outward by d (vertex bisectors)."""
    n = len(loop)
    out = []
    for i in range(n):
        p0, p1, p2 = loop[i - 1], loop[i], loop[(i + 1) % n]
        def normal(a, b):
            tx, ty = b[0] - a[0], b[1] - a[1]
            l = math.hypot(tx, ty) or 1.0
            return (ty / l, -tx / l)
        n1, n2 = normal(p0, p1), normal(p1, p2)
        bx, by = n1[0] + n2[0], n1[1] + n2[1]
        bl = math.hypot(bx, by)
        if bl < 1e-9:
            out.append((p1[0] + n1[0] * d, p1[1] + n1[1] * d)); continue
        cos_half = (n1[0] * bx + n1[1] * by) / bl
        k = d / max(cos_half, 0.3)
        out.append((p1[0] + bx / bl * k, p1[1] + by / bl * k))
    return out


def _strict_cross(a: Point, b: Point, loop: list[Point]) -> bool:
    """Proper crossing of a-b with an edge of the loop (touching endpoints do not count)."""
    n = len(loop)
    r = (b[0] - a[0], b[1] - a[1])
    for i in range(n):
        c, d = loop[i], loop[(i + 1) % n]
        s_ = (d[0] - c[0], d[1] - c[1])
        den = r[0] * s_[1] - r[1] * s_[0]
        if abs(den) < 1e-12:
            continue
        qp = (c[0] - a[0], c[1] - a[1])
        t = (qp[0] * s_[1] - qp[1] * s_[0]) / den
        u = (qp[0] * r[1] - qp[1] * r[0]) / den
        if 1e-7 < t < 1 - 1e-7 and 1e-7 < u < 1 - 1e-7:
            return True
    return False


def route(start: Point, goal: Point, obstacles: list[list[Point]]) -> list[Point]:
    """Shortest polyline from start to goal that crosses none of the convex
    obstacle loops (visibility graph over their vertices + Dijkstra).
    start and goal must lie outside the obstacles. Returns [start, ..., goal]."""
    # An endpoint inside an obstacle means the wire already stands in that
    # piece's clearance ring (neighbours packed tight). Such an obstacle
    # cannot be routed around, so it is dropped for this query - grazing a
    # neighbour's clearance is allowed, cutting into it is prevented by the
    # caller, which keeps the piece outlines out of the way.
    obstacles = [ob for ob in obstacles if not (inside(start, ob) or inside(goal, ob))]

    def tag(p: Point, default: int) -> tuple[Point, int, int]:
        # a start/goal that is a hull vertex belongs to that hull (edge moves allowed)
        for k, ob in enumerate(obstacles):
            for i, q in enumerate(ob):
                if math.dist(p, q) < 1e-9:
                    return (p, k, i)
        return (p, default, 0)
    nodes: list[tuple[Point, int, int]] = [tag(start, -1), tag(goal, -2)]
    for k, ob in enumerate(obstacles):
        nodes += [(p, k, i) for i, p in enumerate(ob)]

    def free(i: int, j: int) -> bool:
        (a, ka, ia), (b, kb, ib) = nodes[i], nodes[j]
        if ka == kb and ka >= 0:                      # same hull: only along its edges
            m = len(obstacles[ka])
            return (ia - ib) % m in (1, m - 1) or ia == ib
        for k, ob in enumerate(obstacles):
            if _strict_cross(a, b, ob):
                return False
            if k not in (ka, kb) and inside(((a[0] + b[0]) / 2, (a[1] + b[1]) / 2), ob):
                return False
        return True

    if free(0, 1):
        return [start, goal]
    n = len(nodes)
    dist = [math.inf] * n; prev = [-1] * n
    dist[0] = 0.0
    heap = [(0.0, 0)]
    done = [False] * n
    while heap:
        d, i = heapq.heappop(heap)
        if done[i]:
            continue
        done[i] = True
        if i == 1:
            break
        for j in range(n):
            if j == i or done[j] or not free(i, j):
                continue
            w = d + math.dist(nodes[i][0], nodes[j][0])
            if w < dist[j]:
                dist[j] = w; prev[j] = i
                heapq.heappush(heap, (w, j))
    if dist[1] == math.inf:
        raise ValueError("kein Weg zwischen den Konturen gefunden")
    path = []
    i = 1
    while i != -1:
        path.append(nodes[i][0]); i = prev[i]
    return list(reversed(path))


def _stretches(keys: list[int], m: int) -> list[tuple[int, int]]:
    """(a, b) index ranges between consecutive keys, going round the loop
    from keys[0]; b may exceed m - 1 (use modulo)."""
    out = []
    for a, b in zip(keys, keys[1:] + [keys[0]]):
        while b <= a:
            b += m
        out.append((a, b))
    return out


def segment_counts(loop: list[Point], keys: list[int], n: int) -> list[int]:
    """How many points each stretch between consecutive key vertices gets so
    that the whole loop has n (proportional to length, at least 1 each)."""
    m = len(loop)
    lengths = []
    for a, b in _stretches(keys, m):
        lengths.append(sum(math.dist(loop[i % m], loop[(i + 1) % m]) for i in range(a, b)))
    total = sum(lengths) or 1.0
    counts = [max(1, int(round(n * l / total))) for l in lengths]
    while sum(counts) > n and max(counts) > 1:
        counts[counts.index(max(counts))] -= 1
    while sum(counts) < n:
        counts[lengths.index(max(lengths))] += 1
    return counts


def resample_keyed(loop: list[Point], keys: list[int], counts: list[int]) -> list[Point]:
    """Like resample, but the key vertices (sorted indices, the first is the
    start) are kept exactly; stretch s gets counts[s] points including its
    key vertex. Two loops with the same key structure and counts pair up
    point for point. Last point == first point."""
    m = len(loop)
    out: list[Point] = []
    for (a, b), c in zip(_stretches(keys, m), counts):
        pts = [loop[i % m] for i in range(a, b + 1)]
        seg = [math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
        total = sum(seg)
        k = 0; acc = 0.0
        for q in range(c):
            target = total * q / c
            while k < len(seg) - 1 and acc + seg[k] < target:
                acc += seg[k]; k += 1
            f = (target - acc) / seg[k] if seg[k] > 0 else 0.0
            p0, p1 = pts[k], pts[k + 1]
            out.append((p0[0] + (p1[0] - p0[0]) * f, p0[1] + (p1[1] - p0[1]) * f))
    out.append(out[0])
    return out


def resample(loop: list[Point], n: int, start: int = 0) -> list[Point]:
    """n + 1 points at equal arc length around the loop, from vertex `start`,
    last point == first point."""
    pts = loop[start:] + loop[:start]
    pts.append(pts[0])
    seg = [math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
    total = sum(seg)
    out = [pts[0]]
    k = 0; acc = 0.0
    for i in range(1, n):
        target = total * i / n
        while k < len(seg) - 1 and acc + seg[k] < target:
            acc += seg[k]; k += 1
        f = (target - acc) / seg[k] if seg[k] > 0 else 0.0
        a, b = pts[k], pts[k + 1]
        out.append((a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f))
    out.append(pts[0])
    return out


# ---------------------------------------------------------------- notches ---
def surface_y(loop: list[Point], x: float, top: bool) -> float:
    """Height of the upper (top=True) or lower surface of a closed loop at x."""
    m = len(loop)
    best = None
    for i in range(m):
        a, b = loop[i], loop[(i + 1) % m]
        if a[0] == b[0] or (a[0] - x) * (b[0] - x) > 0:
            continue
        y = a[1] + (b[1] - a[1]) * (x - a[0]) / (b[0] - a[0])
        if best is None or (y > best if top else y < best):
            best = y
    if best is None:
        raise ValueError(f"X={x:g} liegt ausserhalb der Kontur")
    return best


def surface_at(loop: list[Point], x: float, top: bool) -> tuple[Point, Point, Point]:
    """Point, unit tangent and inward unit normal of the upper (top=True) or
    lower surface of a closed loop at x."""
    m = len(loop)
    best = None
    for i in range(m):
        a, b = loop[i], loop[(i + 1) % m]
        if a[0] == b[0] or (a[0] - x) * (b[0] - x) > 0:
            continue
        y = a[1] + (b[1] - a[1]) * (x - a[0]) / (b[0] - a[0])
        if best is None or (y > best[0][1] if top else y < best[0][1]):
            best = ((x, y), (b[0] - a[0], b[1] - a[1]))
    if best is None:
        raise ValueError(f"X={x:g} liegt ausserhalb der Kontur")
    (px, py), (tx, ty) = best
    ln = math.hypot(tx, ty) or 1.0
    t = (tx / ln, ty / ln)
    n = (t[1], -t[0])
    if not inside((px + n[0] * 1e-4, py + n[1] * 1e-4), loop):     # point into the body
        n = (-n[0], -n[1])
    return (px, py), t, n


def notch_normal(loop: list[Point], x: float, w: float, h: float, top: bool) -> tuple[list[Point], list[int]]:
    """Cut a slot of w x h into the loop at chord position x, square to the
    skin there (a strip glued on the surface sits flat in it), not upright.
    Returns the new loop and the indices of its four slot corners."""
    if w <= 0 or h <= 0:
        raise ValueError("Nut: Breite und Hoehe muessen > 0 sein")
    p, t, n = surface_at(loop, x, top)
    m = len(loop)
    walls = []
    for sgn in (1.0, -1.0):
        base = (p[0] + t[0] * sgn * w / 2, p[1] + t[1] * sgn * w / 2)
        far_a = (base[0] - n[0] * 1e4, base[1] - n[1] * 1e4)
        far_b = (base[0] + n[0] * 1e4, base[1] + n[1] * 1e4)
        best = None
        for i in range(m):
            a, b = loop[i], loop[(i + 1) % m]
            u = seg_intersect(far_a, far_b, a, b)
            if u is None:
                continue
            pt = (far_a[0] + (far_b[0] - far_a[0]) * u, far_a[1] + (far_b[1] - far_a[1]) * u)
            d = math.dist(pt, base)
            if best is None or d < best[0]:
                best = (d, i, pt)
        if best is None:
            raise ValueError(f"Nut bei X={x:g} passt nicht auf die Kontur")
        walls.append(best)
    (_, e1, m1), (_, e2, m2) = walls
    pts = list(loop)
    ins = sorted(((e1, m1), (e2, m2)), key=lambda kv: -kv[0])
    idx = {}
    for e, pt in ins:                     # from the back, so earlier insertions keep their edge
        at = e + 1
        for q in list(idx):
            if idx[q] >= at:
                idx[q] += 1
        pts.insert(at, pt); idx[pt] = at
    i1, i2 = idx[m1], idx[m2]
    n_pts = len(pts)

    def arc(i, j):
        out = [i]
        k = (i + 1) % n_pts
        while k != j:
            out.append(k); k = (k + 1) % n_pts
        return out + [j]
    a12, a21 = arc(i1, i2), arc(i2, i1)
    length = lambda a: sum(math.dist(pts[a[k]], pts[a[k + 1]]) for k in range(len(a) - 1))
    keep_from, keep_to = (i2, i1) if length(a12) < length(a21) else (i1, i2)   # replace the short arc
    s1 = (pts[keep_to][0] - p[0]) * n[0] + (pts[keep_to][1] - p[1]) * n[1]
    s2 = (pts[keep_from][0] - p[0]) * n[0] + (pts[keep_from][1] - p[1]) * n[1]
    floor = max(s1, s2) + h
    f_to = (pts[keep_to][0] + n[0] * (floor - s1), pts[keep_to][1] + n[1] * (floor - s1))
    f_from = (pts[keep_from][0] + n[0] * (floor - s2), pts[keep_from][1] + n[1] * (floor - s2))
    kept = [pts[k] for k in arc(keep_from, keep_to)]          # the long way round, outside the slot
    return kept + [f_to, f_from], [len(kept) - 1, len(kept), len(kept) + 1, 0]


def notch(loop: list[Point], x1: float, x2: float, y_end: float, side: str) -> tuple[list[Point], list[int]]:
    """Cut a slot into a CCW loop: from the top (side 'oben') or the bottom
    edge, between x1 < x2, down/up to y_end. Returns the new loop and the
    indices of its four slot corners (edge, floor, floor, edge)."""
    if x1 >= x2:
        raise ValueError("Nut: Breite muss > 0 sein")
    top = side == "oben"
    m = len(loop)

    def crossing(x):
        best = None
        for i in range(m):
            a, b = loop[i], loop[(i + 1) % m]
            if a[0] == b[0] or (a[0] - x) * (b[0] - x) > 0:
                continue
            y = a[1] + (b[1] - a[1]) * (x - a[0]) / (b[0] - a[0])
            if best is None or (y > best[0] if top else y < best[0]):
                best = (y, i)
        if best is None:
            raise ValueError(f"Nut bei X={x:g} liegt ausserhalb der Kontur")
        return best
    (ya, ea), (yb, eb) = crossing(x1), crossing(x2)
    if (y_end >= min(ya, yb)) if top else (y_end <= max(ya, yb)):
        raise ValueError(f"Nut: Grund Y={y_end:g} liegt nicht innerhalb der Kontur")
    pts: list[Point] = []
    idx = {}
    for i in range(m):
        pts.append(loop[i])
        here = [(key, (x, y)) for key, (y, e), x in (("a", (ya, ea), x1), ("b", (yb, eb), x2)) if e == i]
        here.sort(key=lambda kv: math.dist(loop[i], kv[1]))
        for key, pt in here:
            idx[key] = len(pts); pts.append(pt)
    n = len(pts)
    ia, ib = idx["a"], idx["b"]
    # CCW runs right-to-left along the top and left-to-right along the bottom:
    # the stretch to replace goes from b to a on top, from a to b at the bottom
    start, end = (ib, ia) if top else (ia, ib)
    kept = []
    k = end
    while k != start:
        kept.append(pts[k]); k = (k + 1) % n
    return [pts[start], (pts[start][0], y_end), (pts[end][0], y_end)] + kept, [0, 1, 2, 3]


def rect(x0: float, y0: float, x1: float, y1: float) -> list[Point]:
    """CCW rectangle."""
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


# ------------------------------------------------------------ triangulate ---
def bridge_holes(outer: list[Point], holes: list[list[Point]]) -> tuple[list[Point], list[Point]]:
    """One weakly simple polygon from an outline and its holes: every hole is
    joined to the outline by a slit between two existing vertices, so no new
    point lands on the outline (a point in the middle of an edge would leave a
    T-junction where the cap meets the walls).

    Returns two walks with the same indices: the first has the slit opened by
    EPS (ear clipping chokes on a zero-width bridge), the second has the exact
    points. Triangulate the first, build geometry from the second.
    """
    walk = list(outer); exact = list(outer)
    rest = [list(h) for h in holes]
    for hole in sorted(rest, key=lambda h: min(q[0] for q in h)):
        others = [h for h in rest if h is not hole]
        best = None
        for hi, hp in enumerate(hole):
            for wi, wp in enumerate(walk):
                d = math.dist(hp, wp)
                if best is not None and d >= best[0]:
                    continue
                mid = ((hp[0] + wp[0]) / 2, (hp[1] + wp[1]) / 2)
                if _strict_cross(hp, wp, walk) or any(_strict_cross(hp, wp, h) for h in rest):
                    continue
                if not inside(mid, outer) or any(inside(mid, h) for h in rest):
                    continue
                best = (d, wi, hi)
        if best is None:
            raise ValueError("Loch laesst sich nicht mit der Kontur verbinden")
        _, wi, hi = best
        n = len(hole)
        ring = [hole[(hi - k) % n] for k in range(n)]          # a hole runs the other way round
        wp, hp = walk[wi], hole[hi]
        dx, dy = hp[0] - wp[0], hp[1] - wp[1]
        ln = math.hypot(dx, dy) or 1.0
        off = (-dy / ln * EPS, dx / ln * EPS)                  # open the slit sideways
        seam = ([(wp[0] + off[0], wp[1] + off[1])] + [(q[0] + off[0], q[1] + off[1]) for q in ring]
                + [(q[0] - off[0], q[1] - off[1]) for q in (ring[0], wp)])
        walk = walk[:wi + 1] + seam + walk[wi + 1:]
        exact = exact[:wi + 1] + [wp] + ring + [ring[0], wp] + exact[wi + 1:]
    return walk, exact


def triangulate(poly: list[Point]) -> list[tuple[int, int, int]]:
    """Ear clipping for a simple (or hole-bridged) CCW polygon -> triangles as
    index triples into `poly`."""
    n = len(poly)
    if n < 3:
        return []
    idx = list(range(n))
    if signed_area(poly) < 0:
        idx.reverse()
    out: list[tuple[int, int, int]] = []
    guard = 0
    while len(idx) > 3 and guard < 4 * n * n:
        guard += 1
        best = None
        for k in range(len(idx)):
            i0, i1, i2 = idx[k - 1], idx[k], idx[(k + 1) % len(idx)]
            a, b, c = poly[i0], poly[i1], poly[i2]
            cross = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
            if cross <= 1e-12:                           # reflex or degenerate
                continue
            if best is None or cross > best[0]:
                best = (cross, k, (i0, i1, i2))
            if any(_in_tri(poly[j], a, b, c) for j in idx if j not in (i0, i1, i2)):
                continue
            out.append((i0, i1, i2)); idx.pop(k); break
        else:
            # No clean ear - happens where the outline is a sliver (a trailing
            # edge). Clip the most convex corner anyway: a slightly wrong
            # triangle there beats a hole in the surface.
            if best is None:
                break
            out.append(best[2]); idx.pop(best[1])
    if len(idx) == 3:
        out.append((idx[0], idx[1], idx[2]))
    return out


def _in_tri(p: Point, a: Point, b: Point, c: Point) -> bool:
    d1 = (p[0] - b[0]) * (a[1] - b[1]) - (a[0] - b[0]) * (p[1] - b[1])
    d2 = (p[0] - c[0]) * (b[1] - c[1]) - (b[0] - c[0]) * (p[1] - c[1])
    d3 = (p[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (p[1] - a[1])
    neg = (d1 < -1e-12) or (d2 < -1e-12) or (d3 < -1e-12)
    pos = (d1 > 1e-12) or (d2 > 1e-12) or (d3 > 1e-12)
    return not (neg and pos)
