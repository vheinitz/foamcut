"""Two lofted sections -> a closed triangle mesh, written as a binary STL.

Both sections must be point-for-point pairs (same count, same order), which is
exactly what the cut paths of a wing or a free shape already are: side A at
z = 0, side B at z = span. Holes pair the same way. The two end faces are
triangulated with a hole-bridged ear clip, so the body is watertight - every
edge belongs to exactly two triangles.
"""
from __future__ import annotations

import struct

from . import geom

Point = tuple[float, float]
Vec3 = tuple[float, float, float]


def loft_body(a_outer: list[Point], b_outer: list[Point], span: float,
              a_holes: list[list[Point]] | None = None,
              b_holes: list[list[Point]] | None = None) -> list[tuple[Vec3, Vec3, Vec3]]:
    """Triangles of the solid between the two sections."""
    a_holes = [list(h) for h in (a_holes or [])]
    b_holes = [list(h) for h in (b_holes or [])]
    if len(a_outer) != len(b_outer):
        raise ValueError("Die beiden Seiten haben verschieden viele Punkte")
    tris: list[tuple[Vec3, Vec3, Vec3]] = []

    def wall(a2: list[Point], b2: list[Point], flip: bool):
        n = len(a2)
        for i in range(n):
            j = (i + 1) % n
            p0 = (a2[i][0], a2[i][1], 0.0); p1 = (a2[j][0], a2[j][1], 0.0)
            q0 = (b2[i][0], b2[i][1], span); q1 = (b2[j][0], b2[j][1], span)
            quad = [(p0, p1, q1), (p0, q1, q0)]
            tris.extend([(c, b, a) for a, b, c in quad] if flip else quad)

    wall(a_outer, b_outer, False)
    for ha, hb in zip(a_holes, b_holes):
        wall(ha, hb, True)                          # a hole faces the other way
    for pts, holes, z, flip in ((a_outer, a_holes, 0.0, True), (b_outer, b_holes, span, False)):
        if holes:
            walk, exact = geom.bridge_holes(list(pts), holes)
        else:
            walk = exact = list(pts)
        for i, j, k in geom.triangulate(walk):
            p0, p1, p2 = exact[i], exact[j], exact[k]
            if abs((p1[0] - p0[0]) * (p2[1] - p0[1]) - (p1[1] - p0[1]) * (p2[0] - p0[0])) < 1e-9:
                continue                            # sliver along a slit: no area once the slit is closed
            face = ((p0[0], p0[1], z), (p1[0], p1[1], z), (p2[0], p2[1], z))
            tris.append(tuple(reversed(face)) if flip else face)
    return tris


def to_stl(tris: list[tuple[Vec3, Vec3, Vec3]], header: str) -> bytes:
    """Binary STL. Normals are left at zero - every reader recomputes them."""
    out = bytearray(header.encode("ascii", "replace")[:79].ljust(80, b" ")) + struct.pack("<I", len(tris))
    for a, b, c in tris:
        out += struct.pack("<3f", 0.0, 0.0, 0.0) + struct.pack("<9f", *a, *b, *c) + b"\0\0"
    return bytes(out)
