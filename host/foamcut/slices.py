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

import copy
import math
import struct
from dataclasses import dataclass, field
from pathlib import Path

from . import geom
from .contour import Part, classify, clearance, cut_parts, part_from_outline
from .machine import Machine
from .wing import (Model, WingError, WingPath, _template, contour_moves, emit_gcode, from_text, inverted, loft,
                   to_text)

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
         "Welche Scheiben geschnitten werden, 1 = am Anfang der Achse. Eine Nummer, eine Liste '2,3,4', "
         "ein Bereich '1-5', '$' fuer die letzte, '*3' fuer jede dritte (von der ersten an) oder 'alle'. "
         "Alles mischbar: '1,*3,$' schneidet die erste, jede dritte und die letzte. Mehrere Scheiben werden "
         "nebeneinander auf der Platte angeordnet; passen nicht alle, gibt es ein Programm je Platte.", "text"),
        ("gap", "Zusatzabstand", "mm", "0",
         "Zusaetzlicher Abstand zwischen zwei Scheiben auf der Platte. Ohne ihn liegen sie so eng, wie der "
         "Fahrweg des Drahts erlaubt (2 x Schnittbreite zu jedem Teil).", "num"),
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
        ("root_gap", "Seite A ab Turm", "mm", "",
         "Abstand der Seite A der Platte vom Turm mit dem festen Draht, entlang des Drahts. "
         "Leer = die Software legt die Platte mittig zwischen die Tuerme; beim verlaufenden Schnitt "
         "teilt sich der Schraegversatz dann gleichmaessig auf beide Schlitten auf.", "num"),
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
_REQUIRED = {"stl", "thickness", "block_x", "table_y"}
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
    gap: float = 0.0
    loft: bool = True
    points: int = 120
    spar_side: str = "keine"
    spar_x: float = 0.0
    spar_y: float = 0.0
    spar_w: float = 6.0
    root_gap: float | None = None       # None: centre the board between the towers
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


def notch(loop, x1, x2, y_end, side):
    """Spar slot in a section - see geom.notch (WingError for the GUI)."""
    try:
        return geom.notch(loop, x1, x2, y_end, side)
    except ValueError as e:
        raise WingError(f"Holmnut: {e}") from None


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


def _match(a_outs: list, b_outs: list) -> list[tuple]:
    """Pair the outlines of the two cut faces: nearest centres first. A slab
    of a car gives a body and two wheels on both faces - each has to be cut
    together with its counterpart."""
    if len(a_outs) != len(b_outs):
        raise WingError(f"Die beiden Schnittflaechen haben {len(a_outs)} und {len(b_outs)} Umrisse - "
                        "duennere Scheiben waehlen oder 'verlaufend = nein'")
    free = list(range(len(b_outs)))
    pairs = []
    for A in sorted(a_outs, key=lambda o: -abs(geom.signed_area(o.loop))):
        ca = geom.centre_of(A.loop)
        k = min(free, key=lambda j: math.dist(ca, geom.centre_of(b_outs[j].loop)))
        free.remove(k)
        pairs.append((A, b_outs[k]))
    return pairs


def _pair_loft(A, B, n: int, keys_a: list[int], keys_b: list[int]) -> tuple[list[Point], list[Point]]:
    """Side paths for one lofted piece: the two outlines resampled to the same
    point counts from their rearmost point (and the same slot corners, if a
    spar slot is cut); holes via a slit from the outline's rearmost point."""
    if len(A.holes) != len(B.holes):
        raise WingError(f"Loecher: {len(A.holes)} auf der einen, {len(B.holes)} auf der anderen "
                        "Schnittflaeche - 'verlaufend = nein' waehlen")
    keys = counts = keys_b_ordered = None
    if keys_a:
        keys = sorted(set(keys_a) | {A.rear})
        start = keys.index(A.rear)
        keys = keys[start:] + keys[:start]                 # begin at the rear
        counts = geom.segment_counts(A.loop, keys, n)
        keys_bb = sorted(set(keys_b) | {B.rear})
        if len(keys_bb) != len(keys):
            raise WingError("Holmnut: Schnittflaechen passen nicht zusammen - 'verlaufend = nein' waehlen")
        start_b = keys_bb.index(B.rear)
        keys_b_ordered = keys_bb[start_b:] + keys_bb[:start_b]

    def path_for(o, key_list):
        outer = geom.resample_keyed(o.loop, key_list, counts) if key_list else geom.resample(o.loop, n, o.rear)
        out = list(outer)
        m = max(24, n // 2)
        for h in sorted(o.holes, key=lambda h: h.loop[h.rear][1]):
            out.extend(geom.resample(h.loop, m, h.rear))
            out.append(outer[0])
        return out
    # holes paired by height order on both sides
    return path_for(A, keys), path_for(B, keys_b_ordered)


def parse_indices(text: str, count: int) -> list[int]:
    """Which slabs to cut, out of `count`:

        3          eine
        2,3,4      mehrere
        1-5        ein Bereich, 3-$ bis zur letzten
        $          die letzte
        *3         jede dritte, von der ersten an: 1, 4, 7, ...
        alle       alle

    Mixed freely - '1,*3,$' is the first, every third after it and the last.
    Doubles are dropped, the result comes back in order.
    """
    t = text.strip().lower()
    if t in ("alle", "all", "*"):
        return list(range(1, count + 1))
    out: list[int] = []

    def one(tok: str) -> int:
        tok = tok.strip()
        if tok in ("$", "letzte", "last"):
            return count
        try:
            return int(float(tok))
        except ValueError:
            raise WingError(f"Scheiben: {tok!r} ist keine Nummer ($ = letzte, *n = jede n-te)") from None

    for tok in t.replace(";", ",").split(","):
        tok = tok.strip()
        if not tok:
            continue
        if tok.startswith("*"):
            try:
                step = int(float(tok[1:]))
            except ValueError:
                raise WingError(f"Scheiben: {tok!r} - nach dem * gehoert eine Zahl, z. B. *3") from None
            if step < 1:
                raise WingError("Scheiben: *n braucht n >= 1")
            out.extend(range(1, count + 1, step))
        elif "-" in tok[1:]:                      # 1-5, 3-$ (not a leading minus)
            a, _, b = tok[0] + tok[1:].partition("-")[0], "-", tok[1:].partition("-")[2]
            out.extend(range(one(a), one(b) + 1))
        else:
            out.append(one(tok))
    if not out:
        raise WingError("Scheiben: keine Nummer angegeben")
    bad = [n for n in out if n < 1 or n > count]
    if bad:
        raise WingError(f"Scheibe {bad[0]} gibt es nicht: {count} Scheiben "
                        f"({'1' if count == 1 else '1..' + str(count)})")
    return sorted(dict.fromkeys(out))


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
    deg: int = 0                    # quarter turns applied in the board plane

    def shifted(self, dx: float, dy: float) -> list[Part]:
        mv = lambda pts: [(x + dx, y + dy) for x, y in pts]
        return [Part(mv(p.a), mv(p.b), mv(p.hull), p.label, list(p.outer)) for p in self.parts]


def _slab(spec: SliceSpec, machine: Machine, tris, zmin, zmax, count, index: int, deg: int = 0) -> Slab:
    """The slab as a cut part; `deg` turns the section in the board plane
    (quarter turns, for tighter packing) before the paths are built, so the
    rearmost point, the pairing of the faces and the slits all follow."""
    k, i, j = _frame(spec)
    z0 = zmin + (index - 1) * spec.thickness
    z1 = min(z0 + spec.thickness, zmax)
    notes: list[str] = []
    turn = lambda loops: [_rotated(l, deg) for l in loops]
    if spec.loft:
        # both cut faces, each piece paired with its counterpart: the two
        # towers run independently, exactly as for a wing
        a_loops, keys_a = _prepare(turn(_orient(_section_at(tris, k, z0, i, j, zmin, zmax), spec.mirror)), _spar(spec))
        b_loops, keys_b = _prepare(turn(_orient(_section_at(tris, k, z1, i, j, zmin, zmax), spec.mirror)), _spar(spec))
        oa, ob = classify(a_loops, machine.kerf_mm), classify(b_loops, machine.kerf_mm)
        parts = []
        mid = turn(_orient(_section_at(tris, k, (z0 + z1) / 2, i, j, zmin, zmax), spec.mirror))
        for n_pair, (A, B) in enumerate(_match(oa, ob), start=1):
            pa, pb = _pair_loft(A, B, spec.points, keys_a, keys_b)
            label = f"Scheibe {index}" + (f".{n_pair}" if len(oa) > 1 else "")
            parts.append(Part(pa, pb, geom.convex_hull(pa + pb), label, list(range(len(pa)))))
            sag = _sagitta(pa, pb, mid)
            if sag is not None and sag > 0.05:
                notes.append(f"{label}: Sehnenfehler max {sag:.2f} mm (gerader Draht gegen die runde Haut)")
        kind = "verlaufend"
    else:
        mid = turn(_orient(_section_at(tris, k, (z0 + z1) / 2, i, j, zmin, zmax), spec.mirror))
        mid, _ = _prepare(mid, _spar(spec))
        outlines = classify(mid, machine.kerf_mm)
        # a section can fall into several outlines (a car body and its wheels):
        # number them, the cut order note names them
        parts = [part_from_outline(o, spec.tab, f"Scheibe {index}" + (f".{n + 1}" if len(outlines) > 1 else ""),
                                   machine.kerf_mm) for n, o in enumerate(outlines)]
        kind = "prismatisch"
        # prismatic throws the taper away - say how much, it is easy to leave
        # this switch on by accident
        span = lambda loops: (max(q[0] for l in loops for q in l) - min(q[0] for l in loops for q in l),
                              max(q[1] for l in loops for q in l) - min(q[1] for l in loops for q in l))
        try:
            fa = span(_section_at(tris, k, z0, i, j, zmin, zmax))
            fb = span(_section_at(tris, k, z1, i, j, zmin, zmax))
            drop = max(abs(fa[0] - fb[0]), abs(fa[1] - fb[1]))
        except WingError:
            drop = 0.0
        if drop > 0.5:
            notes.append(f"Scheibe {index} prismatisch geschnitten, aber die beiden Schnittflaechen "
                         f"unterscheiden sich um {drop:.1f} mm - mit 'Verlaufend = ja' bekommt sie ihren Winkel")
    # pieces are packed with half the gap around each: two pieces end up
    # `gap` apart (cut path to cut path), which the wire can still pass
    half = pack_gap(spec, machine) / 2
    parts = [Part(p.a, p.b, geom.grow(p.hull, half), p.label, list(p.outer)) for p in parts]
    xs = [q[0] for p in parts for q in p.a + p.b]; ys = [q[1] for p in parts for q in p.a + p.b]
    hx = [q[0] for p in parts for q in p.hull]; hy = [q[1] for p in parts for q in p.hull]
    notes.insert(0, f"Scheibe {index} von {count} ({spec.axis} = {z0:.1f}..{z1:.1f}), {kind}, "
                    f"{max(xs) - min(xs):.1f} x {max(ys) - min(ys):.1f} mm"
                    + (f", {len(parts)} Teile" if len(parts) > 1 else ""))
    return Slab(index, z0, z1, parts, (max(hx) - min(hx), max(hy) - min(hy)), (min(hx), min(hy)), notes, deg)


def pack_gap(spec: SliceSpec, machine: Machine) -> float:
    """Foam left between two pieces: enough for the wire to travel between
    them (one kerf from each), or more if asked."""
    return max(spec.gap, clearance(machine.kerf_mm) + 0.5)


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
        d = min(geom.seg_dist(q, chord[i], chord[i + 1]) for i in range(n - 1))
        worst = max(worst, d)
    return worst


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


def _rotated(pts: list[Point], deg: int) -> list[Point]:
    if deg == 0:
        return list(pts)
    c, sn = {90: (0, 1), 180: (-1, 0), 270: (0, -1)}[deg]
    return [(x * c - y * sn, x * sn + y * c) for x, y in pts]


def _overlap(a: list[Point], b: list[Point]) -> bool:
    """Convex polygons overlap (separating axis theorem); touching counts as free."""
    for poly in (a, b):
        n = len(poly)
        for i in range(n):
            ex, ey = poly[(i + 1) % n][0] - poly[i][0], poly[(i + 1) % n][1] - poly[i][1]
            nx, ny = -ey, ex
            pa = [nx * x + ny * y for x, y in a]; pb = [nx * x + ny * y for x, y in b]
            if max(pa) <= min(pb) + 1e-9 or max(pb) <= min(pa) + 1e-9:
                return False
    return True


@dataclass
class Placement:
    slab: Slab                      # the chosen rotation variant
    dx: float
    dy: float
    parts: list[Part]               # shifted into area coordinates (origin bottom-rear of the usable area)

    @property
    def hulls(self) -> list[list[Point]]:
        return [p.hull for p in self.parts]

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        xs = [q[0] for h in self.hulls for q in h]; ys = [q[1] for h in self.hulls for q in h]
        return min(xs), min(ys), max(xs), max(ys)

    @property
    def deg(self) -> int:
        return self.slab.deg


def _place(slab: Slab, dx: float, dy: float) -> Placement:
    ox, oy = dx - slab.origin[0], dy - slab.origin[1]       # hull bounding box corner -> (dx, dy)
    return Placement(slab, dx, dy, slab.shifted(ox, oy))


def _fits(pl: Placement, w: float, h: float, others: list[Placement]) -> bool:
    x0, y0, x1, y1 = pl.bbox
    if x0 < -1e-9 or y0 < -1e-9 or x1 > w + 1e-9 or y1 > h + 1e-9:
        return False
    return not any(_overlap(hp, ho) for hp in pl.hulls for o in others for ho in o.hulls)


Variants = dict[int, Slab]          # rotation -> slab


def pack_board(items: list[Variants], w: float, h: float, prefer: str = "low") -> tuple[list[Placement], list[Variants]]:
    """Bottom-left packing of the slabs' hulls into w x h: every slab tries
    the candidate corners (area origin, right of / above every placed slab)
    in every rotation variant and takes the lowest, then rearmost, spot.
    Returns the placements and the items that did not fit."""
    placed: list[Placement] = []
    left: list[Variants] = []
    for variants in items:
        cands = [(0.0, 0.0)]
        for o in placed:
            x0, y0, x1, y1 = o.bbox
            cands += [(x1, y0), (x0, y1), (x1, 0.0), (0.0, y1)]
        best = None
        for dx, dy in cands:
            for deg, slab in variants.items():
                pl = _place(slab, dx, dy)
                if _fits(pl, w, h, placed):
                    x0, y0, x1, y1 = pl.bbox
                    # keep the used rectangle low then short, or short then low
                    key = (y1, x1, deg) if prefer == "low" else (x1, y1, deg)
                    if best is None or key < best[0]:
                        best = (key, pl)
        if best is None:
            left.append(variants)
        else:
            placed.append(best[1])
    return placed, left


def pack(items: list[Variants], w: float, h: float) -> list[list[Placement]]:
    """Boards of placements: the order the slabs are tried in matters, so a
    few orders are tried and the one with the fewest boards, then the
    smallest enclosing rectangle on the first board, wins."""
    for variants in items:
        if not any(sl.size[0] <= w + 1e-6 and sl.size[1] <= h + 1e-6 for sl in variants.values()):
            sl = variants[0]
            raise WingError(f"Scheibe {sl.index} ({sl.size[0]:.0f} x {sl.size[1]:.0f} mm) passt nicht auf die Platte "
                            f"({w:.0f} x {h:.0f} nutzbar)")
    area = lambda v: v[0].size[0] * v[0].size[1]
    orders = [
        sorted(items, key=lambda v: -area(v)),
        sorted(items, key=lambda v: -v[0].size[1]),
        sorted(items, key=lambda v: -v[0].size[0]),
        list(items),
    ]
    best = None
    for order, prefer in ((o, p) for o in orders for p in ("low", "rear")):
        boards: list[list[Placement]] = []
        todo = list(order)
        while todo:
            placed, todo = pack_board(todo, w, h, prefer)
            if not placed:
                raise WingError(f"Scheibe {todo[0][0].index} passt nicht auf die Platte ({w:.0f} x {h:.0f} nutzbar)")
            boards.append(placed)
        x1 = max(pl.bbox[2] for pl in boards[0]); y1 = max(pl.bbox[3] for pl in boards[0])
        key = (len(boards), x1 * y1, x1)
        if best is None or key < best[0]:
            best = (key, boards)
    return best[1]


@dataclass
class Board:
    number: int
    path: WingPath
    slabs: list[int]
    size: tuple[float, float]           # used area w x h
    entry_y: float = 0.0                # board-plane height of the entry line (path y = board y - entry_y + chord_y)


def build_boards(spec: SliceSpec, machine: Machine) -> tuple[list[Board], list[str]]:
    spec = copy.copy(spec)
    tris, zmin, zmax, count = _body(spec)
    indices = parse_indices(spec.index, count)
    w, h = _usable(spec, machine)
    boards: list[Board] = []
    notes: list[str] = []
    if spec.root_gap is None:
        # centred: the wire lines run out to both towers by the same amount,
        # so a tapered slab costs both carriages the same travel
        spec.root_gap = max((machine.tower_gap_mm - spec.thickness) / 2, 0.0)
        notes.append(f"Platte mittig zwischen den Tuermen: Seite A ab Turm {spec.root_gap:.0f} mm "
                     f"(Feld 'Seite A ab Turm' fuellen, um sie anders zu legen)")
    x0 = spec.block_x + spec.lead                     # rear edge of the usable area
    # turning pieces by quarter turns packs tighter; not with a spar slot (its
    # "oben" would turn too), not with a tab (the walk is no longer closed),
    # and pointless for a single piece
    rotations = (0,) if spec.spar_side != "keine" or spec.tab > 0 or len(indices) == 1 else (0, 90, 180, 270)
    items: list[Variants] = [{deg: _slab(spec, machine, tris, zmin, zmax, count, n, deg) for deg in rotations}
                             for n in indices]
    slabs = [v[0] for v in items]
    for b, placed in enumerate(pack(items, w, h), start=1):
        parts: list[Part] = []
        for pl in placed:
            # placed with the packing gap around them; routing wants the bare hulls back
            parts.extend(Part([(x + x0, y) for x, y in p.a], [(x + x0, y) for x, y in p.b],
                              geom.convex_hull([(x + x0, y) for x, y in p.a + p.b]), p.label, list(p.outer))
                         for p in pl.parts)
        pa, pb, order, entry, how = cut_parts(parts, spec.block_x, machine.kerf_mm, spec.tab)
        y0 = entry[1]
        pa = [(x, y - y0) for x, y in pa]; pb = [(x, y - y0) for x, y in pb]
        path = loft(spec, pa, pb, machine)
        used_w = max(pl.bbox[2] for pl in placed)
        used_h = max(pl.bbox[3] for pl in placed)
        nums = sorted(pl.slab.index for pl in placed)
        boards.append(Board(b, path, nums, (used_w, used_h), entry[1]))
        turned = [f"{pl.slab.index} um {pl.deg}°" for pl in placed if pl.deg]
        notes.append(f"Platte {b}: Scheiben {', '.join(map(str, nums))}, Schnittreihenfolge ({how}) "
                     f"{', '.join(parts[k].label.split()[-1] for k in order)}; {len(parts)} Teil(e), "
                     f"belegt {used_w:.0f} x {used_h:.0f} mm "
                     f"von {w:.0f} x {h:.0f} nutzbar" + (f"; gedreht: {', '.join(turned)}" if turned else ""))
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


def board_prompt(b: "Board") -> str:
    p = b.path
    return (f"PLATTE {b.number} EINLEGEN: Scheiben {', '.join(map(str, b.slabs))}, Rueckseite X={p.block[0]:g}, "
            f"unten Y={p.table_y:g}, mind. {p.min_block[2]:.0f} x {p.min_block[3]:.0f} x {p.min_block[5]:.0f} mm "
            f"(Laenge x Hoehe x Dicke)")


def generate(spec: SliceSpec, machine: Machine, airfoil_dir: Path | None = None) -> tuple[str, WingPath]:
    """One complete program per board (the pieces already cut stay in the
    old board, so the next board gets its own file, loaded after the user
    has swapped boards). Returns board 1's program; all of them are in
    path.programs as (name, code)."""
    path = build_path(spec, machine)
    boards = path.boards
    total = 0.0
    stem = slice_name(spec)[:-3]
    for b in boards:
        p = b.path
        header = [f"; foamcut slice: Platte {b.number} von {len(boards)} - " + path.notes[1],
                  "; " + board_prompt(b),
                  f"; Kerf {machine.kerf_mm:g}, Vorschub {machine.cut_feed:g} mm/min"]
        code = emit_gcode(p, machine.cut_feed, machine.wire_power, machine.warmup_s, header)
        total += contour_moves(p, machine.cut_feed)[1]
        name = f"{stem}_platte{b.number}.nc" if len(boards) > 1 else f"{stem}.nc"
        path.programs.append((name, code))
    path.notes.append(f"Schnittzeit ca. {total:.1f} min, {len(boards)} Platte(n)"
                      + (" - ein Programm je Platte" if len(boards) > 1 else ""))
    return path.programs[0][1], path


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
                    slice_from_text, TEMPLATE, "slices (*.slices);;alle (*)",
                    preview=preview, preview_kind="mesh")
