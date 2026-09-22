"""Small 2D helpers for closed polylines (loops): orientation, containment,
intersections, convex hull, shortest path around obstacles."""
from __future__ import annotations

import heapq
import math

Point = tuple[float, float]


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
    def tag(p: Point, default: int) -> tuple[Point, int, int]:
        # a start/goal that is a hull vertex belongs to that hull (edge moves allowed)
        for k, ob in enumerate(obstacles):
            for i, q in enumerate(ob):
                if math.dist(p, q) < 1e-9:
                    return (p, k, i)
        for k, ob in enumerate(obstacles):
            if inside(p, ob):
                raise ValueError("Start- oder Zielpunkt liegt in einem Teil - Abstand zwischen den Teilen zu klein")
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
