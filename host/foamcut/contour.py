"""Free 2D outlines from an SVG (letters, silhouettes, sketches), cut
prismatically: both towers follow the same contour, so the block thickness
does not matter (parallel cut, X=U / Y=V).

What the wire needs beyond the drawing, all done here:
- kerf: outer outlines run kerf/2 outside, holes kerf/2 inside;
- no plunging: a hole is reached through a slit from its rearmost point
  straight back to the enclosing outline (or a sibling hole in the way);
- several outlines in one drawing are cut one after another, the wire
  travelling through the waste around the convex hulls of the others - it
  never crosses a piece that is already cut free;
- entry from the block's back face to the rearmost outline, exit the same way.

Coordinates: SVG x -> machine X (forward), SVG y up -> machine Y (up); so
the drawing is seen from the side of tower 1 as drawn. `mirror` flips it.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

from . import geom
from .machine import Machine
from .svg import SvgError, load_svg
from .wing import (Model, WingError, WingPath, _template, emit_gcode, field_catalogue, from_text, loft, to_text)

Point = tuple[float, float]
CLEARANCE = 1.0         # mm, least distance between the travel path and a piece's cut path


def clearance(kerf: float) -> float:
    """Distance the travel path keeps from a piece's cut path: one kerf, so
    two pieces packed two kerfs apart still let the wire pass between them
    (Valentin, 2026-09-23: "Draht darf an geschnittenen Teilen schon nah
    fahren - 2x Schnittbreite")."""
    return max(kerf, CLEARANCE)

FIELDS = [
    ("zeichnung", "Zeichnung", [
        ("svg", "SVG-Datei", "", "",
         "Zeichnung mit geschlossenen Konturen (Inkscape: Text vorher in Pfade umwandeln). "
         "Aeussere Konturen werden Teile, Konturen darin Loecher.", "file:svg"),
        ("width", "Breite", "mm", "",
         "Gesamtbreite der Zeichnung in X nach dem Skalieren. Leer = Masse aus der Datei mal Faktor.", "num"),
        ("scale", "Faktor", "", "1",
         "Skalierung der Zeichnung, wenn keine Breite angegeben ist.", "num"),
        ("mirror", "Spiegeln", "ja/nein", "nein",
         "Zeichnung in X spiegeln (fuer das Gegenstueck oder weil die Vorlage seitenverkehrt ist).", "bool"),
        ("panel", "Dicke", "mm", "30",
         "Blockdicke in Spannrichtung, von Seite A (am Turm mit festem Draht) nach B. "
         "Beide Seiten sind gleich; die Dicke bestimmt nur Block und Schnittzeit.", "num"),
        ("step", "Aufloesung", "mm", "0.5",
         "Laengster Abschnitt, in den Kurven zerlegt werden. Kleiner = runder, mehr Zeilen.", "num"),
    ]),
    ("lage", "Lage im Schneider", [
        ("root_gap", "Seite A ab Turm", "mm", "150",
         "Abstand der Seite A des Blocks vom Turm mit dem festen Draht, entlang des Drahts.", "num"),
        ("block_x", "Block Rueckseite X", "mm", "20",
         "Abstand der Blockrueckseite vom Referenzpunkt nach vorn. Dort taucht der Draht ein.", "num"),
        ("table_y", "Tischoberkante Y", "mm", "20",
         "Hoehe der Tischoberkante (= Blockunterkante) ueber dem Draht-Null. Die Zeichnung liegt 'Rand' darueber.", "num"),
        ("lead", "Einlauf", "mm", "12",
         "Strecke im Schaum von der Blockrueckseite bis zum hintersten Punkt der Zeichnung.", "num"),
    ]),
    ("schnitt", "Schnitt", [
        ("margin", "Rand", "mm", "10",
         "Mindestabstand der Zeichnung zu Vorderseite, Ober-, Unterseite und Seite B des Blocks.", "num"),
        ("tab", "Haltesteg", "mm", "0",
         "So viel jeder Kontur bleibt ungeschnitten (am hintersten Punkt), damit Teil und Lochkern nicht "
         "auf den Draht fallen; danach von Hand brechen. 0 = durchschneiden.", "num"),
    ]),
    ("block", "Block", [
        ("block_s", "Block Anfang ab Seite A", "mm", "", "0 oder leer = der Block beginnt an Seite A.", "num"),
        ("block_w", "Block Breite", "mm", "", "Ausdehnung in Spannrichtung. Leer = Dicke plus Rand.", "num"),
        ("block_len", "Block Laenge", "mm", "", "Leer = Mindestblock.", "num"),
        ("block_h", "Block Hoehe", "mm", "", "Ab Tischoberkante. Leer = Mindestblock.", "num"),
    ]),
]

TEMPLATE = _template(FIELDS, ("; Freie Kontur aus einer SVG-Zeichnung, beide Seiten gleich (Parallelschnitt).",
                              "; Alle Masse in mm. Zeilen mit ; sind Kommentare."))
_NUMERIC = {"width", "scale", "panel", "step", "root_gap", "block_x", "table_y", "lead", "margin", "tab",
            "block_s", "block_w", "block_len", "block_h"}
_MACHINE_KEYS = {"kerf", "feed", "wire", "warmup"}
_REQUIRED = {"svg", "panel", "root_gap", "block_x", "table_y"}
_BOOL = {"ja": True, "nein": False, "yes": True, "no": False, "true": True, "false": False, "1": True, "0": False}


@dataclass
class ContourSpec:
    svg: str = ""
    width: float | None = None
    scale: float = 1.0
    mirror: bool = False
    panel: float = 30.0
    step: float = 0.5
    root_gap: float = 150.0
    block_x: float = 20.0
    table_y: float = 20.0
    chord_y: float | None = None
    lead: float = 12.0
    margin: float = 10.0
    tab: float = 0.0
    block_s: float | None = None
    block_w: float | None = None
    block_len: float | None = None
    block_y: float | None = None
    block_h: float | None = None

    @classmethod
    def parse(cls, text: str) -> "ContourSpec":
        spec = cls()
        seen = set()
        for n, raw in enumerate(text.splitlines(), start=1):
            line = raw.split(";", 1)[0].strip()
            if not line or line.startswith("["):
                continue
            if "=" not in line:
                raise WingError(f"Zeile {n}: erwartet 'name = wert': {raw.strip()!r}")
            key, _, value = line.partition("=")
            key, value = key.strip().lower(), value.strip()
            if key in _MACHINE_KEYS:
                continue
            if not hasattr(spec, key):
                raise WingError(f"Zeile {n}: unbekannter Parameter {key!r}")
            if value == "":
                continue
            if key == "mirror":
                if value.lower() not in _BOOL:
                    raise WingError(f"Zeile {n}: mirror muss ja oder nein sein")
                spec.mirror = _BOOL[value.lower()]
            elif key in _NUMERIC:
                try:
                    setattr(spec, key, float(value.replace(",", ".")))
                except ValueError:
                    raise WingError(f"Zeile {n}: {key} braucht eine Zahl, nicht {value!r}") from None
            else:
                setattr(spec, key, value)
            seen.add(key)
        missing = _REQUIRED - seen
        if missing:
            raise WingError("fehlt: " + ", ".join(sorted(missing)))
        if spec.panel <= 0 or spec.scale <= 0 or spec.step <= 0:
            raise WingError("panel, scale und step muessen > 0 sein")
        if spec.width is not None and spec.width <= 0:
            raise WingError("width muss > 0 sein (oder leer)")
        if spec.lead < 0 or spec.margin < 0 or spec.tab < 0:
            raise WingError("lead, margin und tab duerfen nicht negativ sein")
        return spec


# ------------------------------------------------------------- planning ---
@dataclass
class Outline:
    loop: list[Point]               # CCW, kerf applied
    holes: list["Outline"]
    rear: int = 0                   # index of the rearmost vertex


def _offset(loop: list[Point], d: float) -> list[Point]:
    """Kerf offset with proper corners (miter), unlike the airfoil offset that
    is tuned for dense smooth loops."""
    return geom.grow(loop, d) if abs(d) > 1e-12 else list(loop)


def classify(loops: list[list[Point]], kerf: float) -> list[Outline]:
    """Outer outlines with their holes (nesting by containment), kerf applied."""
    loops = [geom.ccw(geom.dedupe(l)) for l in loops]
    loops = [l for l in loops if len(l) > 2 and abs(geom.signed_area(l)) > 1e-6]
    if not loops:
        raise WingError("keine brauchbare Kontur in der Zeichnung")
    areas = [abs(geom.signed_area(l)) for l in loops]
    parents: list[int | None] = []
    depth: list[int] = []
    for i, l in enumerate(loops):
        containers = [j for j, other in enumerate(loops) if j != i and areas[j] > areas[i] and geom.inside(l[0], other)]
        depth.append(len(containers))
        parents.append(min(containers, key=lambda j: areas[j]) if containers else None)
    outlines: dict[int, Outline] = {}
    for i, l in enumerate(loops):
        if depth[i] % 2 == 0:
            outlines[i] = Outline(_offset(l, kerf / 2.0), [])
    for i, l in enumerate(loops):
        if depth[i] % 2 == 1:
            outlines[parents[i]].holes.append(Outline(_offset(l, -kerf / 2.0), []))
        elif depth[i] >= 2:
            pass                                    # island inside a hole: its own part, fine
    for o in outlines.values():
        o.rear = min(range(len(o.loop)), key=lambda k: o.loop[k][0])
        for h in o.holes:
            h.rear = min(range(len(h.loop)), key=lambda k: h.loop[k][0])
    return sorted(outlines.values(), key=lambda o: o.loop[o.rear][0])


def trim_tail(pts: list[Point], tab: float) -> list[Point]:
    """Drop the last `tab` mm of a closed walk (pts[-1] == pts[0]) so a bridge
    of foam stays and the piece does not drop onto the wire."""
    if tab <= 0 or len(pts) < 3:
        return pts
    left = tab
    out = list(pts)
    while len(out) > 2:
        d = math.dist(out[-2], out[-1])
        if d > left:
            f = (d - left) / d
            a, b = out[-2], out[-1]
            out[-1] = (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)
            return out
        left -= d
        out.pop()
    return out


def _cut_outline(o: Outline, tab: float = 0.0) -> list[Point]:
    """One outline with its holes as a single wire path from its rearmost
    vertex around and back: holes hang off slits that run straight back.
    `tab` > 0 leaves that much of every loop uncut (Haltesteg)."""
    # attach every hole to the first loop its backward ray hits (the outline
    # or a hole nearer the back), so slits never cross a hole
    hosts: list[Outline] = [o]
    junctions: dict[int, list[tuple[int, Outline, Point]]] = {}      # id(host) -> [(edge, hole, point)]
    for h in sorted(o.holes, key=lambda h: h.loop[h.rear][0]):
        origin = h.loop[h.rear]
        best = None
        for host in hosts:
            hit = geom.ray_hit(origin, (-1.0, 0.0), host.loop)
            if hit and (best is None or hit[0] < best[0][0]):
                best = (hit, host)
        if best is None:
            raise WingError("Loch ohne Weg nach hinten - Zeichnung pruefen")
        (dist, edge), host = best
        junctions.setdefault(id(host), []).append((edge, h, (origin[0] - dist, origin[1])))
        hosts.append(h)

    def walk(loop_o: Outline, start: int) -> list[Point]:
        loop = loop_o.loop
        n = len(loop)
        js = junctions.get(id(loop_o), [])
        out: list[Point] = []
        for k in range(n + 1):
            i = (start + k) % n
            out.append(loop[i])
            if k == n:
                break
            # junctions on edge i -> i+1, nearest to vertex i first
            for edge, hole, jp in sorted((j for j in js if j[0] == i), key=lambda j: math.dist(loop[i], j[2])):
                out.append(jp)
                out.extend(walk(hole, hole.rear))
                out.append(jp)
        return trim_tail(out, tab)
    return walk(o, o.rear)


@dataclass
class Part:
    """One piece to cut: its wire path on side A and B (same length, closed
    walks starting and ending at the piece's rearmost point), the convex
    hull of its cut paths (no clearance - packing and routing add their own)
    and which walk indices sit on the outer loop (entry candidates)."""
    a: list[Point]
    b: list[Point]
    hull: list[Point]
    label: str = ""
    outer: list[int] = field(default_factory=list)

    @property
    def closed(self) -> bool:
        return len(self.a) > 2 and math.dist(self.a[0], self.a[-1]) < 1e-9

    def walks_from(self, idx: int) -> tuple[list[Point], list[Point]]:
        """The closed walks started at walk index idx (an outer-loop vertex)."""
        if idx == 0 or not self.closed:
            return list(self.a), list(self.b)
        return self.a[idx:] + self.a[1:idx + 1], self.b[idx:] + self.b[1:idx + 1]


def part_from_outline(o: Outline, tab: float = 0.0, label: str = "", kerf: float = 0.0) -> Part:
    path = _cut_outline(o, tab)
    verts = {(round(x, 9), round(y, 9)) for x, y in o.loop}
    outer = [i for i, q in enumerate(path[:-1]) if (round(q[0], 9), round(q[1], 9)) in verts]
    return Part(path, list(path), geom.convex_hull(o.loop), label, outer)


def _port(own: list[Point], rear: Point, others: list[list[Point]]) -> Point:
    """A point on the piece's clearance hull, rearmost first, that no other
    hull covers: where the wire can wait before entering from behind."""
    for q in sorted(own, key=lambda q: (q[0], abs(q[1] - rear[1]))):
        if not any(geom.inside(q, o) for o in others):
            return q
    raise WingError("Teil ist von anderen so eng umgeben, dass der Draht es nicht erreicht - "
                    "Zusatzabstand erhoehen")


def cut_order(parts: list[Part], start: Point) -> list[int]:
    """Top pieces first - a piece cut free may drop, and a piece cut below
    one that has dropped is off - and within a band of equal height the
    nearest next, which walks the rows back and forth."""
    tops = [max(q[1] for q in p.hull) for p in parts]
    heights = [max(q[1] for q in p.hull) - min(q[1] for q in p.hull) for p in parts]
    order: list[int] = []
    pos = start
    todo = list(range(len(parts)))
    while todo:
        top = max(tops[k] for k in todo)
        band = [k for k in todo if tops[k] >= top - 0.4 * heights[k]]
        k = min(band, key=lambda k: min(math.dist(pos, parts[k].a[i]) for i in (parts[k].outer or [0])))
        order.append(k); todo.remove(k)
        pos = parts[k].a[0]
    return order


def route_parts(parts: list[Part], entry: Point | float, kerf: float = 0.0,
                order: list[int] | None = None) -> tuple[list[Point], list[Point], list[int], Point]:
    """Cut all parts in a chain: from the entry point to the first piece,
    into it at the outer vertex nearest to where the wire is, round, and on
    from there to the next piece - never back to a port, never through a
    piece (cut or not: `clearance(kerf)` around every other hull). Ends
    behind the block face at the height of the last exit; the caller's
    program returns from there to the entry along the face, in air.
    `entry` may be just the x of the block face: the entry height is then the
    rearmost outer vertex of the first piece, so the lead-in is short.
    Returns side A path, side B path (same length), the cut order and the entry."""
    c = clearance(kerf)
    hulls = [geom.grow(p.hull, c) for p in parts]
    if not isinstance(entry, tuple):
        top = max(q[1] for p in parts for q in p.hull)
        order = order if order is not None else cut_order(parts, (entry, top))
        first = parts[order[0]]
        rear = min((first.a[i] for i in (first.outer or [0])), key=lambda q: q[0])
        entry = (entry, rear[1])
    order = order if order is not None else cut_order(parts, entry)
    pa: list[Point] = []; pb: list[Point] = []
    pos = entry
    prev: int | None = None
    for k in order:
        part = parts[k]
        others = [h for j, h in enumerate(hulls) if j != k]
        # leaving the previous piece: first step from its outline out to the
        # nearest vertex of its clearance hull that no other hull covers
        head: list[Point] = [pos]
        if prev is not None:
            free = [q for q in hulls[prev] if not any(geom.inside(q, h) for h in others if h is not hulls[prev])]
            for q in sorted(free, key=lambda q: math.dist(pos, q)):
                if not geom._strict_cross(pos, q, parts[prev].a[:-1]):
                    head.append(q); break
            else:
                raise WingError(f"{parts[prev].label or 'Teil'}: kein freier Weg vom Teil weg - Zusatzabstand erhoehen")
        cands = sorted(part.outer or [0], key=lambda i: math.dist(head[-1], part.a[i])) if part.closed else [0]
        leg = None
        for idx in cands[:12]:
            target = part.a[idx]
            try:
                trial = geom.route(head[-1], target, others)
            except ValueError:
                continue
            # the approach may not cut into the piece we enter
            if not any(geom._strict_cross(u, v, part.a[:-1]) for u, v in zip(trial, trial[1:])):
                leg = (head + trial[1:], idx); break
        if leg is None:                                   # fall back: come in from behind
            port = _port(hulls[k], part.a[0], others)
            trial = geom.route(head[-1], port, others)
            leg = (head + trial[1:] + [part.a[0]], 0)
        trial, idx = leg
        wa, wb = part.walks_from(idx)
        pa.extend(trial[1:] if pa else trial); pb.extend(trial[1:] if pb else trial)
        skip = 1 if trial[-1] == wa[0] else 0          # same on both sides: the paths stay paired
        pa.extend(wa[skip:]); pb.extend(wb[skip:])
        pos = pa[-1]
        prev = k
    # out: off the last piece, then back behind the block face at that height
    exit_pt = (entry[0] - 2.0, pos[1])
    free = [q for q in hulls[prev] if not any(geom.inside(q, h) for j, h in enumerate(hulls) if j != prev)]
    for q in sorted(free, key=lambda q: math.dist(pos, q) + abs(q[1] - pos[1])):
        if not geom._strict_cross(pos, q, parts[prev].a[:-1]):
            break
    else:
        raise WingError("kein freier Weg vom letzten Teil weg - Zusatzabstand erhoehen")
    exit_pt = (entry[0] - 2.0, q[1])
    leg = [pos] + geom.route(q, exit_pt, hulls)
    pa.extend(leg[1:]); pb.extend(leg[1:])
    return pa, pb, order, entry


class ChainError(WingError):
    """The chain scheme does not work for this arrangement; route piece by piece."""


def _centre(pts: list[Point]) -> Point:
    xs = [q[0] for q in pts]; ys = [q[1] for q in pts]
    return ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)


def _junction(part: Part, target: Point) -> tuple[int, float]:
    """Where the line from the piece's centre towards `target` leaves its
    outer loop: (walk edge index, position along that edge). The cut is
    split there, so the wire can leave for the neighbour and come back."""
    c = _centre(part.hull)
    n = len(part.a) - 1                       # closed walk: a[0] == a[-1]
    outer = set(part.outer)
    best = None
    for j in range(n):
        if j not in outer or (j + 1) % n not in outer:
            continue                          # edge interrupted by a slit to a hole
        t = geom.seg_intersect(c, target, part.a[j], part.a[j + 1])
        if t is not None and (best is None or t > best[0]):
            best = (t, j)
    if best is None:
        raise ChainError("kein Uebergangspunkt auf der Kontur gefunden")
    t, j = best
    pt = (c[0] + (target[0] - c[0]) * t, c[1] + (target[1] - c[1]) * t)
    a, b = part.a[j], part.a[j + 1]
    d = math.dist(a, b)
    return j, (math.dist(a, pt) / d if d else 0.0)


def _split(part: Part, cuts: list[tuple[int, float]]) -> tuple[Part, list[int]]:
    """Insert points into the walk (both sides, same index - the loft pairing
    must survive) and return the part plus the new indices."""
    order = sorted(range(len(cuts)), key=lambda i: (cuts[i][0], cuts[i][1]))
    a, b = list(part.a), list(part.b)
    outer = list(part.outer)
    idx = [0] * len(cuts)
    for shift, i in enumerate(order):
        j, f = cuts[i]
        at = j + 1 + shift
        mix = lambda pts: (pts[at - 1][0] + (pts[at][0] - pts[at - 1][0]) * f,
                           pts[at - 1][1] + (pts[at][1] - pts[at - 1][1]) * f)
        a.insert(at, mix(a)); b.insert(at, mix(b))
        outer = [k + 1 if k >= at else k for k in outer] + [at]
        idx[i] = at
    return Part(a, b, part.hull, part.label, sorted(outer)), idx


def _arc(walk: list[Point], i: int, j: int) -> list[Point]:
    """The stretch of the closed walk from index i forward to index j."""
    n = len(walk) - 1
    if i == j:
        return [walk[i]]
    return walk[i:j + 1] if i < j else walk[i:n] + walk[0:j + 1]


def chain_cut(parts: list[Part], entry_x: float, kerf: float = 0.0,
              order: list[int] | None = None) -> tuple[list[Point], list[Point], list[int], Point]:
    """Cut the pieces as one chain with a single lead-in.

    Out: the wire enters the first piece, cuts one arc of it, crosses the
    waste strip to the next piece along the line joining their centres, cuts
    one arc there, and so on. At the last piece it closes the loop and turns
    around; on the way back it cuts the other arc of every piece, retracing
    the connecting channels it has already melted. One lead-in, no travel
    through untouched foam, and every piece comes free on the way back - the
    last one first, so the wire always moves away from a piece that drops
    (the chain runs top to bottom).
    """
    if not parts:
        raise ChainError("keine Teile")
    order = order or cut_order(parts, (entry_x, max(q[1] for p in parts for q in p.hull)))
    seq = [parts[k] for k in order]
    centres = [_centre(p.hull) for p in seq]
    entry = (entry_x, centres[0][1])
    # junctions: towards the entry / the previous piece, and towards the next
    cuts = [[_junction(seq[0], entry)] if len(seq) else []]
    for i in range(1, len(seq)):
        cuts[i - 1].append(_junction(seq[i - 1], centres[i]))
        cuts.append([_junction(seq[i], centres[i - 1])])
    split, idx = [], []
    for part, cl in zip(seq, cuts):
        sp, ii = _split(part, cl)
        split.append(sp); idx.append(ii)
    # every hop must stay in the waste: it may touch the two pieces it joins
    for i in range(len(seq)):
        frm = split[i].a[idx[i][0]] if i == 0 else split[i - 1].a[idx[i - 1][1]]
        to = split[i].a[idx[i][0]]
        if i == 0:
            frm = entry
        for j, other in enumerate(split):
            if j in (i, i - 1):
                continue
            if geom._strict_cross(frm, to, other.a[:-1]) or geom.inside(((frm[0] + to[0]) / 2, (frm[1] + to[1]) / 2),
                                                                        other.a[:-1]):
                raise ChainError("Uebergang wuerde ein anderes Teil treffen")
    pa: list[Point] = [entry]; pb: list[Point] = [entry]
    # out: one arc per piece, hopping to the next
    for i, part in enumerate(split):
        j_in = idx[i][0]
        if i < len(split) - 1:
            j_out = idx[i][1]
            pa.extend(_arc(part.a, j_in, j_out)); pb.extend(_arc(part.b, j_in, j_out))
            nxt = split[i + 1]
            pa.append(nxt.a[idx[i + 1][0]]); pb.append(nxt.b[idx[i + 1][0]])
        else:                                   # last piece: close its loop, then turn around
            wa, wb = part.walks_from(j_in)
            pa.extend(wa); pb.extend(wb)
    # back: the other arc of every piece, retracing the channels between them
    for i in range(len(split) - 2, -1, -1):
        part = split[i]
        j_in, j_out = idx[i][0], idx[i][1]
        pa.append(part.a[j_out]); pb.append(part.b[j_out])
        pa.extend(_arc(part.a, j_out, j_in)[1:]); pb.extend(_arc(part.b, j_out, j_in)[1:])
    pa.append(entry); pb.append(entry)
    keep = [0] + [i for i in range(1, len(pa)) if math.dist(pa[i], pa[i - 1]) > 1e-9 or math.dist(pb[i], pb[i - 1]) > 1e-9]
    return [pa[i] for i in keep], [pb[i] for i in keep], order, entry


def cut_parts(parts: list[Part], entry_x: float, kerf: float = 0.0,
              tab: float = 0.0) -> tuple[list[Point], list[Point], list[int], Point, str]:
    """The wire path over all pieces: the chain (one lead-in, every piece cut
    in two arcs, the channels between them reused on the way back) where it
    works, otherwise piece by piece from behind. Also returns which it was."""
    if tab <= 0:
        try:
            pa, pb, order, entry = chain_cut(parts, entry_x, kerf)
            return pa, pb, order, entry, "Kette"
        except (ChainError, ValueError):
            pass
    pa, pb, order, entry = route_parts(parts, entry_x, kerf)
    return [entry] + pa, [entry] + pb, order, entry, "einzeln"


def plan(loops: list[list[Point]], kerf: float, entry_x: float, tab: float = 0.0) -> tuple[list[Point], list[str]]:
    """All outlines as one path from the entry point and back to it, in the
    drawing's coordinates."""
    outlines = classify(loops, kerf)
    parts = [part_from_outline(o, tab, kerf=kerf) for o in outlines]
    path, _, order, entry, how = cut_parts(parts, entry_x, kerf, tab)
    notes = [f"{len(outlines)} Teil(e), {sum(len(o.holes) for o in outlines)} Loch/Loecher, "
             f"Schnittreihenfolge ({how}): " + ", ".join(str(k + 1) for k in order)
             + (f"; Haltesteg {tab:g} mm an jeder Kontur (von Hand brechen)" if tab > 0 else "")]
    return path, notes


# ---------------------------------------------------------------- build ---
def _drawing(spec: ContourSpec) -> tuple[list[list[Point]], list[str]]:
    p = Path(spec.svg).expanduser()
    if not p.exists():
        raise WingError(f"SVG-Datei nicht gefunden: {spec.svg}")
    try:
        loops, warnings = load_svg(p, spec.step)
    except SvgError as e:
        raise WingError(str(e)) from None
    xs = [q[0] for l in loops for q in l]
    x0, x1 = min(xs), max(xs)
    f = spec.width / (x1 - x0) if spec.width else spec.scale
    loops = [[(x * f, y * f) for x, y in l] for l in loops]
    if spec.mirror:
        loops = [[(-x, y) for x, y in l] for l in loops]
    return loops, warnings


def build_path(spec: ContourSpec, machine: Machine) -> WingPath:
    loops, warnings = _drawing(spec)
    rear = min(q[0] for l in loops for q in l)
    shift_x = spec.block_x + spec.lead - rear
    loops = [[(x + shift_x, y) for x, y in l] for l in loops]
    path, notes = plan(loops, machine.kerf_mm, spec.block_x, spec.tab)
    y0 = path[0][1]
    rel = [(x, y - y0) for x, y in path]             # entry line = reference line (y = 0)
    wp = loft(spec, rel, list(rel), machine)
    xs = [q[0] for l in loops for q in l]; ys = [q[1] for l in loops for q in l]
    wp.notes.insert(1, f"Kontur: {Path(spec.svg).name}, {max(xs) - min(xs):.1f} x {max(ys) - min(ys):.1f} mm"
                       + (", gespiegelt" if spec.mirror else "") + f", Dicke {spec.panel:g}")
    wp.notes.extend(notes)
    wp.notes.extend(warnings)
    return wp


def generate(spec: ContourSpec, machine: Machine, airfoil_dir: Path | None = None) -> tuple[str, WingPath]:
    path = build_path(spec, machine)
    header = ["; foamcut contour: " + path.notes[1][8:],
              f"; Kerf {machine.kerf_mm:g}, Vorschub {machine.cut_feed:g} mm/min, Parallelschnitt X=U Y=V"]
    return emit_gcode(path, machine.cut_feed, machine.wire_power, machine.warmup_s, header), path


def contour_name(spec: ContourSpec) -> str:
    stem = Path(spec.svg).stem or "kontur"
    size = f"_b{spec.width:g}" if spec.width else (f"_x{spec.scale:g}" if spec.scale != 1 else "")
    return f"{stem}{size}{'_sp' if spec.mirror else ''}_{spec.panel:g}.nc"


def contour_to_text(values: dict[str, str]) -> str:
    return to_text(values, FIELDS, "; foamcut contour")


def contour_from_text(text: str) -> dict[str, str]:
    return from_text(text, FIELDS)


def preview(spec: ContourSpec):
    """Outlines of the drawing in mm plus the indices of the holes."""
    loops, _ = _drawing(spec)
    # a loop is a hole when it lies inside larger loops an odd number of times
    holes = set()
    areas = [abs(geom.signed_area(l)) for l in loops]
    for i, l in enumerate(loops):
        depth = sum(1 for j, o in enumerate(loops) if j != i and areas[j] > areas[i] and geom.inside(l[0], o))
        if depth % 2 == 1:
            holes.add(i)
    return loops, holes


CONTOUR_MODEL = Model("Kontur", "contour", FIELDS, ContourSpec.parse, generate, contour_name, contour_to_text,
                      contour_from_text, TEMPLATE, "contour (*.contour);;alle (*)", preview, "loops")
