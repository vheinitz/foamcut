"""A 3D body (STL) cut as slabs of one thickness: fuselages, big wings,
anything, stacked from foam slices on spars.

Slice n covers z0 = zmin + (n-1)*t .. z1 = z0 + t along the slicing axis.
Two ways to cut it:
- loft (default): side A is the section at z0, side B the section at z1 and
  the wire sweeps the ruled surface between them - the stack comes out
  smooth instead of stepped. Needs one outline per section (holes allowed:
  a hollow fuselage is cut with a slit from the rear, like a ring).
- prismatic: the section in the middle of the slab, both sides equal;
  works for any number of outlines (contour.plan does the routing).

Axes: the STL axis chosen as `axis` becomes the span (block thickness),
`up` becomes machine Y, the remaining axis machine X (forward).
"""
from __future__ import annotations

import math
import struct
from dataclasses import dataclass, field
from pathlib import Path

from . import geom
from .contour import CLEARANCE, Part, classify, part_from_outline, route_parts
from .machine import Machine
from .wing import (Model, WingError, WingPath, _template, contour_moves, from_text, inverted, job_line, loft, to_text)

Point = tuple[float, float]
Tri = tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]
AXES3 = ("x", "y", "z")

FIELDS = [
    ("koerper", "Koerper", [
        ("stl", "STL-Datei", "", "", "3D-Koerper (binaer oder ASCII), Masse in mm mal Faktor.", "file:stl"),
        ("scale", "Faktor", "", "1", "Skalierung des Koerpers (z. B. 0.001 fuer Dateien in Metern).", "num"),
        ("axis", "Scheibenachse", "", "z",
         "Achse des Koerpers, entlang der geschnitten wird (Laengsachse des Rumpfs, Spannweite). "
         "Sie wird zur Blockdicke.", "choice:x|y|z"),
        ("up", "Oben", "", "y", "Achse des Koerpers, die auf der Maschine nach oben zeigt.", "choice:x|y|z"),
        ("mirror", "Spiegeln", "ja/nein", "nein", "Querschnitt in X spiegeln.", "bool"),
        ("thickness", "Scheibendicke", "mm", "40",
         "Dicke jeder Scheibe = Blockdicke. Anzahl der Scheiben folgt aus der Laenge des Koerpers.", "num"),
        ("index", "Scheiben", "", "1",
         "Welche Scheiben geschnitten werden, 1 = am Anfang der Achse: eine Nummer, Liste '2,3,4', Bereich '1-5' "
         "oder 'alle'. Mehrere Scheiben werden nebeneinander auf der Platte angeordnet; passen nicht alle, "
         "haelt das Programm an (M0) und verlangt die naechste Platte.", "text"),
        ("gap", "Abstand", "mm", "6", "Schaum, der zwischen zwei Scheiben auf der Platte stehen bleibt.", "num"),
        ("loft", "Verlaufend", "ja/nein", "ja",
         "ja: Seite A = Schnitt am Anfang der Scheibe, Seite B = am Ende, der Draht schneidet die "
         "Flaeche dazwischen (glatt). nein: Querschnitt in der Scheibenmitte, beide Seiten gleich (Stufen).", "bool"),
        ("points", "Stuetzpunkte", "", "120",
         "Punkte je Umriss beim verlaufenden Schnitt (beide Seiten gleich viele).", "int"),
    ]),
    ("holm", "Holmnut", [
        ("spar_side", "Nut von", "", "keine",
         "Nut fuer eine Holmleiste, vom Rand des Querschnitts aus: oben oder unten. In Koerperkoordinaten, "
         "also in jeder Scheibe an derselben Stelle - die Leiste geht gerade durch den Stapel.", "choice:keine|oben|unten"),
        ("spar_x", "Nut Mitte X", "mm", "0",
         "Lage der Nutmitte entlang der Vorwaerts-Achse des Koerpers (Koerperkoordinaten mal Faktor).", "num"),
        ("spar_y", "Nut Grund Y", "mm", "0",
         "Hoehe des Nutgrunds (Koerperkoordinaten): die Nut reicht vom Rand bis hierher.", "num"),
        ("spar_w", "Nut Breite", "mm", "6", "Breite der Leiste; die Kerf ist beruecksichtigt.", "num"),
    ]),
    ("lage", "Lage im Schneider", [
        ("root_gap", "Seite A ab Turm", "mm", "150",
         "Abstand der Seite A des Blocks vom Turm mit dem festen Draht, entlang des Drahts.", "num"),
        ("block_x", "Block Rueckseite X", "mm", "20",
         "Abstand der Blockrueckseite vom Referenzpunkt nach vorn. Dort taucht der Draht ein.", "num"),
        ("table_y", "Tischoberkante Y", "mm", "20",
         "Hoehe der Tischoberkante (= Blockunterkante) ueber dem Draht-Null.", "num"),
        ("lead", "Einlauf", "mm", "12",
         "Strecke im Schaum von der Blockrueckseite bis zum hintersten Punkt des Querschnitts.", "num"),
    ]),
    ("schnitt", "Schnitt", [
        ("margin", "Rand", "mm", "10",
         "Mindestabstand des Querschnitts zu Vorderseite, Ober-, Unterseite und Seite B des Blocks.", "num"),
        ("tab", "Haltesteg", "mm", "0",
         "Nur prismatisch: so viel jeder Kontur bleibt ungeschnitten, damit Teil und Lochkern nicht auf den "
         "Draht fallen. 0 = durchschneiden.", "num"),
    ]),
    ("block", "Block", [
        ("block_s", "Block Anfang ab Seite A", "mm", "", "0 oder leer = der Block beginnt an Seite A.", "num"),
        ("block_w", "Block Breite", "mm", "", "Ausdehnung in Spannrichtung. Leer = Dicke plus Rand.", "num"),
        ("block_len", "Platte Laenge", "mm", "",
         "Laenge der Schaumplatte in X ab der Rueckseite. Leer = so viel, wie der Verfahrweg hergibt.", "num"),
        ("block_h", "Platte Hoehe", "mm", "",
         "Hoehe der Platte ab Tischoberkante. Leer = so viel, wie der Verfahrweg hergibt.", "num"),
    ]),
]

TEMPLATE = _template(FIELDS, ("; Scheiben eines 3D-Koerpers (STL) fuer den Schaumschneider, auf Platten der Scheibendicke.",
                              "; Alle Masse in mm. Zeilen mit ; sind Kommentare."))
_NUMERIC = {"scale", "thickness", "gap", "points", "spar_x", "spar_y", "spar_w", "tab", "root_gap", "block_x", "table_y", "lead", "margin",
            "block_s", "block_w", "block_len", "block_h"}
_MACHINE_KEYS = {"kerf", "feed", "wire", "warmup"}
_REQUIRED = {"stl", "thickness", "root_gap", "block_x", "table_y"}
_BOOL = {"ja": True, "nein": False, "yes": True, "no": False, "true": True, "false": False, "1": True, "0": False}


@dataclass
class SliceSpec:
    stl: str = ""
    scale: float = 1.0
    axis: str = "z"
    up: str = "y"
    mirror: bool = False
    thickness: float = 40.0
    index: str = "1"
    gap: float = 6.0
    loft: bool = True
    points: int = 120
    spar_side: str = "keine"
    spar_x: float = 0.0
    spar_y: float = 0.0
    spar_w: float = 6.0
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

    @property
    def panel(self) -> float:           # loft() and nesting read the span length here
        return self.thickness

    @panel.setter
    def panel(self, v: float):
        self.thickness = v

    @classmethod
    def parse(cls, text: str) -> "SliceSpec":
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
            if not hasattr(spec, key) or key == "panel":
                raise WingError(f"Zeile {n}: unbekannter Parameter {key!r}")
            if value == "":
                continue
            if key in ("mirror", "loft"):
                if value.lower() not in _BOOL:
                    raise WingError(f"Zeile {n}: {key} muss ja oder nein sein")
                setattr(spec, key, _BOOL[value.lower()])
            elif key in ("axis", "up"):
                if value.lower() not in AXES3:
                    raise WingError(f"Zeile {n}: {key} muss x, y oder z sein")
                setattr(spec, key, value.lower())
            elif key == "spar_side":
                if value.lower() not in ("keine", "oben", "unten"):
                    raise WingError(f"Zeile {n}: spar_side muss keine, oben oder unten sein")
                spec.spar_side = value.lower()
            elif key in _NUMERIC:
                try:
                    num = float(value.replace(",", "."))
                except ValueError:
                    raise WingError(f"Zeile {n}: {key} braucht eine Zahl, nicht {value!r}") from None
                setattr(spec, key, int(num) if key == "points" else num)
            else:
                setattr(spec, key, value)
            seen.add(key)
        missing = _REQUIRED - seen
        if missing:
            raise WingError("fehlt: " + ", ".join(sorted(missing)))
        if spec.thickness <= 0 or spec.scale <= 0:
            raise WingError("thickness und scale muessen > 0 sein")
        if spec.gap < 0:
            raise WingError("gap darf nicht negativ sein")
        if spec.axis == spec.up:
            raise WingError("axis und up muessen verschiedene Achsen sein")
        if spec.points < 12:
            raise WingError("points: mindestens 12")
        if spec.spar_side != "keine" and spec.spar_w <= 0:
            raise WingError("spar_w muss > 0 sein")
        if spec.lead < 0 or spec.margin < 0:
            raise WingError("lead und margin duerfen nicht negativ sein")
        return spec


# ------------------------------------------------------------------ stl ----
def load_stl(path: Path) -> list[Tri]:
    data = path.read_bytes()
    if len(data) < 84:
        raise WingError(f"{path.name}: keine STL-Datei (zu kurz)")
    is_ascii = data[:5] == b"solid" and b"facet" in data[:4000]
    tris: list[Tri] = []
    if is_ascii:
        verts: list[tuple[float, float, float]] = []
        for line in data.decode("ascii", "replace").splitlines():
            t = line.split()
            if len(t) == 4 and t[0] == "vertex":
                verts.append((float(t[1]), float(t[2]), float(t[3])))
                if len(verts) == 3:
                    tris.append((verts[0], verts[1], verts[2])); verts = []
    else:
        n = struct.unpack_from("<I", data, 80)[0]
        if 84 + n * 50 != len(data):
            raise WingError(f"{path.name}: binaere STL mit falscher Laenge ({n} Dreiecke angekuendigt)")
        for i in range(n):
            v = struct.unpack_from("<12f", data, 84 + i * 50)
            tris.append(((v[3], v[4], v[5]), (v[6], v[7], v[8]), (v[9], v[10], v[11])))
    if not tris:
        raise WingError(f"{path.name}: keine Dreiecke")
    return tris


def section(tris: list[Tri], k: int, c: float, i: int, j: int) -> list[list[Point]]:
    """Closed loops where the plane axis[k] = c cuts the mesh, as (axis i, axis j)."""
    segs: list[tuple[Point, Point]] = []
    for tri in tris:
        zs = [v[k] - c for v in tri]
        if all(z > 0 for z in zs) or all(z < 0 for z in zs):
            continue
        pts = []
        for a in range(3):
            va, vb = tri[a], tri[(a + 1) % 3]
            za, zb = zs[a], zs[(a + 1) % 3]
            if za == zb or min(za, zb) > 0 or max(za, zb) < 0:
                continue
            f = za / (za - zb)
            pts.append((va[i] + (vb[i] - va[i]) * f, va[j] + (vb[j] - va[j]) * f))
        uniq: list[Point] = []
        for p in pts:
            if all(math.dist(p, q) > 1e-9 for q in uniq):
                uniq.append(p)
        if len(uniq) == 2:
            segs.append((uniq[0], uniq[1]))
    return _link(segs)


def _key(p: Point) -> tuple[int, int]:
    return (round(p[0] * 1e4), round(p[1] * 1e4))


def _link(segs: list[tuple[Point, Point]]) -> list[list[Point]]:
    """Segments -> loops by joining matching endpoints. A plane through mesh
    vertices yields every edge in it twice (from both sides): drop duplicates."""
    seen: set[tuple] = set()
    uniq = []
    for a, b in segs:
        k = tuple(sorted((_key(a), _key(b))))
        if k not in seen and k[0] != k[1]:
            seen.add(k); uniq.append((a, b))
    segs = uniq
    ends: dict[tuple[int, int], list[int]] = {}
    for n, (a, b) in enumerate(segs):
        ends.setdefault(_key(a), []).append(n); ends.setdefault(_key(b), []).append(n)
    used = [False] * len(segs)
    loops: list[list[Point]] = []
    for start in range(len(segs)):
        if used[start]:
            continue
        used[start] = True
        a, b = segs[start]
        loop = [a, b]
        while True:
            cand = [n for n in ends.get(_key(loop[-1]), []) if not used[n]]
            if not cand:
                break
            n = cand[0]; used[n] = True
            p, q = segs[n]
            loop.append(q if _key(p) == _key(loop[-1]) else p)
            if _key(loop[-1]) == _key(loop[0]):
                loop.pop(); break
        loop = geom.dedupe(loop)
        if len(loop) > 2 and abs(geom.signed_area(loop)) > 1e-3:
            loops.append(loop)
    return loops


# ---------------------------------------------------------------- build ---
def _frame(spec: SliceSpec) -> tuple[int, int, int]:
    k = AXES3.index(spec.axis)
    j = AXES3.index(spec.up)
    i = ({0, 1, 2} - {k, j}).pop()
    return k, i, j


def _body(spec: SliceSpec) -> tuple[list[Tri], float, float, int]:
    p = Path(spec.stl).expanduser()
    if not p.exists():
        raise WingError(f"STL-Datei nicht gefunden: {spec.stl}")
    tris = load_stl(p)
    f = spec.scale
    if f != 1.0:
        tris = [tuple((v[0] * f, v[1] * f, v[2] * f) for v in t) for t in tris]
    k = AXES3.index(spec.axis)
    zs = [v[k] for t in tris for v in t]
    zmin, zmax = min(zs), max(zs)
    count = max(1, int(math.ceil((zmax - zmin) / spec.thickness - 1e-9)))
    return tris, zmin, zmax, count


def _section_at(tris, k, c, i, j, zmin, zmax) -> list[list[Point]]:
    """Section at c, nudged inward at the very ends where the body may close to a point."""
    for cc in (c, min(max(c, zmin + 0.05), zmax - 0.05), min(max(c, zmin + 0.5), zmax - 0.5)):
        loops = section(tris, k, cc, i, j)
        if loops:
            return loops
    raise WingError(f"kein Querschnitt bei {spec_axis_note(k)}={c:.1f}")


def spec_axis_note(k: int) -> str:
    return AXES3[k]


def _orient(loops: list[list[Point]], mirror: bool) -> list[list[Point]]:
    if mirror:
        loops = [[(-x, y) for x, y in l] for l in loops]
    return loops


def notch(loop: list[Point], x1: float, x2: float, y_end: float, side: str) -> tuple[list[Point], list[int]]:
    """Cut a spar slot into a CCW loop: from the top (side 'oben') or bottom
    edge between x1 < x2 down/up to y_end. Returns the new loop and the
    indices of its four slot corners (edge, bottom, bottom, edge)."""
    if x1 >= x2:
        raise WingError("Holmnut: Breite muss > 0 sein")
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
            raise WingError(f"Holmnut bei X={x:g} liegt ausserhalb des Querschnitts")
        return best
    (ya, ea), (yb, eb) = crossing(x1), crossing(x2)
    if (y_end >= min(ya, yb)) if top else (y_end <= max(ya, yb)):
        raise WingError(f"Holmnut: Nutgrund Y={y_end:g} liegt nicht innerhalb des Querschnitts")
    # rebuild with the two crossings as vertices, in order along their edges
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
    new = [pts[start], (pts[start][0], y_end), (pts[end][0], y_end)] + kept
    return new, [0, 1, 2, 3]


def _spar(spec: SliceSpec):
    if spec.spar_side == "keine":
        return None
    x = -spec.spar_x if spec.mirror else spec.spar_x
    return (x - spec.spar_w / 2, x + spec.spar_w / 2, spec.spar_y, spec.spar_side)


def _prepare(loops: list[list[Point]], spar) -> tuple[list[list[Point]], list[int] | None]:
    """CCW, deduped, the outline (largest) notched; keys = its slot corners."""
    loops = [geom.ccw(geom.dedupe(l)) for l in loops]
    if spar is None or not loops:
        return loops, None
    big = max(range(len(loops)), key=lambda i: abs(geom.signed_area(loops[i])))
    loops[big], keys = notch(loops[big], *spar)
    return loops, keys


def _pair_loft(a_loops, b_loops, n: int, kerf: float, spar=None) -> tuple[list[Point], list[Point]]:
    """Side paths for a lofted slab: one outline (plus holes) per side,
    resampled to the same point counts from the rearmost point (and the
    same slot corners, if a spar slot is cut); holes via a slit from the
    outline's rearmost point (ring scheme)."""
    a_loops, keys_a = _prepare(a_loops, spar)
    b_loops, keys_b = _prepare(b_loops, spar)
    oa = classify(a_loops, kerf); ob = classify(b_loops, kerf)
    if len(oa) != 1 or len(ob) != 1:
        raise WingError(f"verlaufender Schnitt braucht einen Umriss je Seite, hier {len(oa)} / {len(ob)} - "
                        "'loft = nein' waehlen oder duennere Scheiben")
    A, B = oa[0], ob[0]
    if len(A.holes) != len(B.holes):
        raise WingError(f"Loecher: {len(A.holes)} auf Seite A, {len(B.holes)} auf Seite B - 'loft = nein' waehlen")
    # classify keeps vertex order (loops are already CCW and deduped), so the
    # slot corner indices still hold; the rearmost vertex joins them as a key
    keys = None
    counts = None
    if keys_a:
        keys = sorted(set(keys_a) | {A.rear}) if A.rear not in keys_a else sorted(keys_a)
        start = keys.index(A.rear)
        keys = keys[start:] + keys[:start]                 # begin at the rear
        counts = geom.segment_counts(A.loop, keys, n)
        # side B: same corner indices, but its own rearmost vertex may differ in
        # index; the slot corners are the same indices by construction
        keys_bb = sorted(set(keys_b) | {B.rear}) if B.rear not in keys_b else sorted(keys_b)
        if len(keys_bb) != len(keys):
            keys_bb = sorted(set(keys_b) | {A.rear})       # fall back: same index as on side A
            if len(keys_bb) != len(keys):
                raise WingError("Holmnut: Schnittflaechen passen nicht zusammen - 'loft = nein' waehlen")
        start_b = keys_bb.index(B.rear if B.rear in keys_bb else A.rear)
        keys_b_ordered = keys_bb[start_b:] + keys_bb[:start_b]

    def path_for(o, key_list):
        if key_list:
            outer = geom.resample_keyed(o.loop, key_list, counts)
        else:
            outer = geom.resample(o.loop, n, o.rear)
        out = list(outer)
        m = max(24, n // 2)
        for h in sorted(o.holes, key=lambda h: h.loop[h.rear][1]):
            out.extend(geom.resample(h.loop, m, h.rear))
            out.append(outer[0])
        return out
    # holes paired by height order on both sides
    return path_for(A, keys), path_for(B, keys_b_ordered if keys else None)


def parse_indices(text: str, count: int) -> list[int]:
    """'3', '2,3,4', '1-5', 'alle' -> slab numbers, 1-based, in the order given."""
    t = text.strip().lower()
    if t in ("alle", "all", "*"):
        return list(range(1, count + 1))
    out: list[int] = []
    for tok in t.replace(";", ",").split(","):
        tok = tok.strip()
        if not tok:
            continue
        if "-" in tok:
            a, _, b = tok.partition("-")
            try:
                lo, hi = int(a), int(b)
            except ValueError:
                raise WingError(f"Scheiben: {tok!r} ist kein Bereich") from None
            out.extend(range(lo, hi + 1))
        else:
            try:
                out.append(int(float(tok)))
            except ValueError:
                raise WingError(f"Scheiben: {tok!r} ist keine Nummer") from None
    if not out:
        raise WingError("Scheiben: keine Nummer angegeben")
    bad = [n for n in out if n < 1 or n > count]
    if bad:
        raise WingError(f"Scheibe {bad[0]} gibt es nicht: {count} Scheiben ({'1' if count == 1 else '1..' + str(count)})")
    return out


@dataclass
class Slab:
    """One slice of the body as a cut part in body coordinates."""
    index: int
    z0: float
    z1: float
    parts: list[Part]               # one per outline (prismatic) or one lofted piece
    size: tuple[float, float]       # bounding box of all hulls, w x h
    origin: tuple[float, float]     # bounding box min corner (body coordinates)
    notes: list[str] = field(default_factory=list)

    def shifted(self, dx: float, dy: float) -> list[Part]:
        mv = lambda pts: [(x + dx, y + dy) for x, y in pts]
        return [Part(mv(p.a), mv(p.b), mv(p.hull), p.label) for p in self.parts]


def _slab(spec: SliceSpec, machine: Machine, tris, zmin, zmax, count, index: int) -> Slab:
    k, i, j = _frame(spec)
    z0 = zmin + (index - 1) * spec.thickness
    z1 = min(z0 + spec.thickness, zmax)
    notes: list[str] = []
    if spec.loft:
        a = _orient(_section_at(tris, k, z0, i, j, zmin, zmax), spec.mirror)
        b = _orient(_section_at(tris, k, z1, i, j, zmin, zmax), spec.mirror)
        pa, pb = _pair_loft(a, b, spec.points, machine.kerf_mm, _spar(spec))
        hull = geom.grow(geom.convex_hull(pa + pb), CLEARANCE)
        parts = [Part(pa, pb, hull, f"Scheibe {index}")]
        kind = "verlaufend"
        # how far the straight wire strays from the true, curved skin between the faces
        mid = _orient(_section_at(tris, k, (z0 + z1) / 2, i, j, zmin, zmax), spec.mirror)
        sag = _sagitta(pa, pb, mid)
        if sag is not None:
            notes.append(f"Scheibe {index}: Sehnenfehler max {sag:.2f} mm (gerader Draht gegen die runde Haut)")
    else:
        mid = _orient(_section_at(tris, k, (z0 + z1) / 2, i, j, zmin, zmax), spec.mirror)
        mid, _ = _prepare(mid, _spar(spec))
        outlines = classify(mid, machine.kerf_mm)
        parts = [part_from_outline(o, spec.tab, f"Scheibe {index}") for o in outlines]
        kind = "prismatisch"
    xs = [q[0] for p in parts for q in p.a + p.b]; ys = [q[1] for p in parts for q in p.a + p.b]
    notes.insert(0, f"Scheibe {index} von {count} ({spec.axis} = {z0:.1f}..{z1:.1f}), {kind}, "
                    f"{max(xs) - min(xs):.1f} x {max(ys) - min(ys):.1f} mm")
    return Slab(index, z0, z1, parts, (max(xs) - min(xs), max(ys) - min(ys)), (min(xs), min(ys)), notes)


def _sagitta(pa: list[Point], pb: list[Point], mid_loops: list[list[Point]]) -> float | None:
    """Largest distance from the true mid section to the straight-wire
    surface (the mean of both face paths) - the error of one slab."""
    if not mid_loops:
        return None
    n = min(len(pa), len(pb))
    chord = [((pa[i][0] + pb[i][0]) / 2, (pa[i][1] + pb[i][1]) / 2) for i in range(n)]
    big = max(mid_loops, key=lambda l: abs(geom.signed_area(l)))
    worst = 0.0
    for q in big[::max(1, len(big) // 60)]:
        d = min(_seg_dist(q, chord[i], chord[i + 1]) for i in range(n - 1))
        worst = max(worst, d)
    return worst


def _seg_dist(p: Point, a: Point, b: Point) -> float:
    ax, ay = b[0] - a[0], b[1] - a[1]
    l2 = ax * ax + ay * ay
    t = 0.0 if l2 == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * ax + (p[1] - a[1]) * ay) / l2))
    return math.dist(p, (a[0] + ax * t, a[1] + ay * t))


def _usable(spec: SliceSpec, machine: Machine) -> tuple[float, float]:
    """Width (X) and height (Y) of the board area the pieces may occupy."""
    if spec.block_len is not None:
        w = spec.block_len - spec.lead - spec.margin
    elif machine.has_travel():
        w = min(machine.travel_mm["X"], machine.travel_mm["U"]) - spec.margin - spec.block_x - spec.lead
    else:
        raise WingError("Plattenlaenge (block_len) angeben - der Verfahrweg ist nicht gemessen")
    if spec.block_h is not None:
        h = spec.block_h - 2 * spec.margin
    elif machine.has_travel():
        h = min(machine.travel_mm["Y"], machine.travel_mm["V"]) - spec.table_y - 2 * spec.margin
    else:
        raise WingError("Plattenhoehe (block_h) angeben - der Verfahrweg ist nicht gemessen")
    if w <= 0 or h <= 0:
        raise WingError("kein Platz auf der Platte: Laenge/Hoehe, Rand, Einlauf und Tisch pruefen")
    return w, h


def pack(slabs: list[Slab], w: float, h: float, gap: float) -> list[list[tuple[Slab, float, float]]]:
    """Shelf packing, rows from the bottom, tallest first; a slab that does
    not fit the current board starts the next. Returns per board
    [(slab, dx, dy)] with the offsets that move the slab's bounding-box
    corner to its place (area coordinates, origin bottom-rear)."""
    order = sorted(slabs, key=lambda s: -s.size[1])
    boards: list[list[tuple[Slab, float, float]]] = []
    for s in order:
        sw, sh = s.size
        if sw > w + 1e-6 or sh > h + 1e-6:
            raise WingError(f"Scheibe {s.index} ({sw:.0f} x {sh:.0f} mm) passt nicht auf die Platte ({w:.0f} x {h:.0f} nutzbar)")
        placed = False
        for board in boards:
            # rows: y of the shelf, its height, the x cursor
            rows = board_rows(board, gap)
            for ry, rh, rx in rows:
                if sh <= rh + 1e-6 and rx + sw <= w + 1e-6:
                    board.append((s, rx, ry)); placed = True; break
            if placed:
                break
            top = max((ry + rh for ry, rh, _ in rows), default=-gap) + gap
            if top + sh <= h + 1e-6:
                board.append((s, 0.0, top)); placed = True; break
        if not placed:
            boards.append([(s, 0.0, 0.0)])
    return boards


def board_rows(board: list[tuple[Slab, float, float]], gap: float) -> list[tuple[float, float, float]]:
    rows: dict[float, list[tuple[Slab, float, float]]] = {}
    for s, dx, dy in board:
        rows.setdefault(dy, []).append((s, dx, dy))
    out = []
    for ry, items in sorted(rows.items()):
        rh = max(s.size[1] for s, _, _ in items)
        rx = max(dx + s.size[0] for s, dx, _ in items) + gap
        out.append((ry, rh, rx))
    return out


@dataclass
class Board:
    number: int
    path: WingPath
    slabs: list[int]
    size: tuple[float, float]           # used area w x h


def build_boards(spec: SliceSpec, machine: Machine) -> tuple[list[Board], list[str]]:
    tris, zmin, zmax, count = _body(spec)
    indices = parse_indices(spec.index, count)
    slabs = [_slab(spec, machine, tris, zmin, zmax, count, n) for n in indices]
    w, h = _usable(spec, machine)
    boards: list[Board] = []
    notes: list[str] = []
    x0 = spec.block_x + spec.lead                     # rear edge of the usable area
    for b, placed in enumerate(pack(slabs, w, h, spec.gap), start=1):
        parts: list[Part] = []
        for s, dx, dy in placed:
            parts.extend(s.shifted(x0 + dx - s.origin[0], dy - s.origin[1]))
        entry = (spec.block_x, parts[0].a[0][1]) if len(placed) == 1 and len(parts) == 1 else (spec.block_x, 0.0)
        pa, pb, order = route_parts(parts, entry)
        y0 = entry[1]
        pa = [(x, y - y0) for x, y in pa]; pb = [(x, y - y0) for x, y in pb]
        path = loft(spec, pa, pb, machine)
        used_w = max(dx + s.size[0] for s, dx, _ in placed)
        used_h = max(dy + s.size[1] for s, _, dy in placed)
        nums = sorted(s.index for s, _, _ in placed)
        boards.append(Board(b, path, nums, (used_w, used_h)))
        notes.append(f"Platte {b}: Scheiben {', '.join(map(str, nums))} in Schnittreihenfolge "
                     f"{', '.join(parts[k].label.split()[-1] for k in order)}; belegt {used_w:.0f} x {used_h:.0f} mm "
                     f"von {w:.0f} x {h:.0f} nutzbar")
    for s in slabs:
        notes.extend(s.notes)
    return boards, notes


def build_path(spec: SliceSpec, machine: Machine) -> WingPath:
    boards, notes = build_boards(spec, machine)
    path = boards[0].path
    tris, zmin, zmax, count = _body(spec)
    path.notes.insert(1, f"Scheiben aus {Path(spec.stl).name}: {count} zu {spec.thickness:g} mm "
                         f"({spec.axis} {zmin:.1f}..{zmax:.1f}), {'verlaufend' if spec.loft else 'prismatisch'}, "
                         f"{len(boards)} Platte(n) zu {spec.thickness:g} mm Dicke")
    if spec.loft:
        # sides of different size: the wire lines converge and cross somewhere
        # beyond the smaller side; at a tower past that point the contour is inverted
        for tower, pts in ((1, path.tower1), (2, path.tower2)):
            if inverted(path.root, pts):
                path.notes.append(f"Drahtlinien kreuzen sich vor Turm {tower} - dort darf kein Schaum liegen; "
                                  "duennere Scheiben oder 'loft = nein' helfen")
        if spec.tab > 0:
            notes.append("Haltesteg nur beim prismatischen Schnitt - hier ohne")
    if spec.spar_side != "keine":
        notes.append(f"Holmnut von {spec.spar_side}: Mitte X={spec.spar_x:g}, Grund Y={spec.spar_y:g}, "
                     f"Breite {spec.spar_w:g} (Koerperkoordinaten)")
    path.notes.extend(notes)
    path.boards = boards
    return path


def generate(spec: SliceSpec, machine: Machine, airfoil_dir: Path | None = None) -> tuple[str, WingPath]:
    path = build_path(spec, machine)
    boards = path.boards
    feed, wire, warmup = machine.cut_feed, machine.wire_power, machine.warmup_s
    s_wire = wire if wire > 0 else 1
    out = ["; foamcut slice: " + path.notes[1],
           f"; Kerf {machine.kerf_mm:g}, Vorschub {feed:g} mm/min",
           "; " + path.notes[0], "G21 ; mm", "G90 ; absolut", "G94",
           f"M3 S{s_wire}" + (" ; Drahtleistung vom GUI-Schieber" if wire <= 0 else ""),
           f"G4 P{warmup:g} ; aufheizen"]
    total = 0.0
    for b in boards:
        p = b.path
        if b.number > 1:
            out += [f"G0 Y{p.entry_t1[1]:.3f} V{p.entry_t2[1]:.3f} ; Hoehe fuer Platte {b.number}",
                    f"M0 ; PLATTE {b.number} EINLEGEN: Scheiben {', '.join(map(str, b.slabs))}, Rueckseite X={p.block[0]:g}, "
                    f"unten Y={p.table_y:g}, mind. {p.min_block[2]:.0f} x {p.min_block[3]:.0f} x {p.min_block[5]:.0f} mm - dann Weiter",
                    f"M3 S{s_wire}", f"G4 P{warmup:g} ; aufheizen"]
        else:
            out.append(f"G0 Y{p.entry_t1[1]:.3f} V{p.entry_t2[1]:.3f} ; erst heben (Tisch!)")
        out += [f"G0 X{p.entry_t1[0]:.3f} U{p.entry_t2[0]:.3f} ; vor zur Plattenrueckseite",
                "G93 ; inverse Zeit: F = 1/min je Segment"]
        moves, minutes = contour_moves(p, feed)
        total += minutes
        out += moves
        out += ["G94", f"G1 X0 U0 F{feed:g} ; zurueck ueber dem Tisch, Draht noch heiss, Schnittvorschub"]
        if b.number < len(boards):
            out.append("M5 ; Draht aus bis zur naechsten Platte")
    out += ["M5 ; Draht aus, erst bei X0/U0", "G0 Y0 V0 ; dann senken", "M2"]
    path.notes.append(f"Schnittzeit ca. {total:.1f} min, {len(boards)} Platte(n)")
    mb = path.min_block
    out.insert(1, job_line((mb[2], mb[3], mb[5]), path.block[0], path.table_y, path.root_tower, path.s_root,
                           total, path.extents()))
    return "\n".join(out) + "\n", path


def slice_name(spec: SliceSpec) -> str:
    stem = Path(spec.stl).stem or "koerper"
    which = spec.index.strip().replace(" ", "").replace(",", "+")
    return f"{stem}_scheibe{which}_{spec.thickness:g}mm{'' if spec.loft else '_prisma'}.nc"


def slice_to_text(values: dict[str, str]) -> str:
    return to_text(values, FIELDS, "; foamcut slice")


def slice_from_text(text: str) -> dict[str, str]:
    return from_text(text, FIELDS)


def preview(spec: SliceSpec):
    """The body, its frame, the slab being cut and all slice planes."""
    tris, zmin, zmax, count = _body(spec)
    k = AXES3.index(spec.axis); j = AXES3.index(spec.up)
    try:
        chosen = parse_indices(spec.index, count)
    except WingError:
        chosen = []
    slabs = [(zmin + (n - 1) * spec.thickness, min(zmin + n * spec.thickness, zmax)) for n in chosen]
    planes = [zmin + n * spec.thickness for n in range(count + 1)]
    planes[-1] = min(planes[-1], zmax)
    return tris, k, j, slabs, planes


SLICE_MODEL = Model("Scheiben", "slices", FIELDS, SliceSpec.parse, generate, slice_name, slice_to_text,
                    slice_from_text, TEMPLATE, "slices (*.slices);;alle (*)", preview, "mesh")
