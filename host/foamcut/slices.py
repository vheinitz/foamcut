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
from dataclasses import dataclass
from pathlib import Path

from . import geom
from .contour import classify, plan
from .machine import Machine
from .wing import (Model, WingError, WingPath, _template, emit_gcode, from_text, inverted, loft, to_text)

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
        ("index", "Scheibe Nr.", "", "1", "Welche Scheibe geschnitten wird, 1 = am Anfang der Achse.", "int"),
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
        ("block_len", "Block Laenge", "mm", "", "Leer = Mindestblock.", "num"),
        ("block_h", "Block Hoehe", "mm", "", "Ab Tischoberkante. Leer = Mindestblock.", "num"),
    ]),
]

TEMPLATE = _template(FIELDS, ("; Scheibe eines 3D-Koerpers (STL) fuer den Schaumschneider.",
                              "; Alle Masse in mm. Zeilen mit ; sind Kommentare."))
_NUMERIC = {"scale", "thickness", "index", "points", "spar_x", "spar_y", "spar_w", "tab", "root_gap", "block_x", "table_y", "lead", "margin",
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
    index: int = 1
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
                setattr(spec, key, int(num) if key in ("index", "points") else num)
            else:
                setattr(spec, key, value)
            seen.add(key)
        missing = _REQUIRED - seen
        if missing:
            raise WingError("fehlt: " + ", ".join(sorted(missing)))
        if spec.thickness <= 0 or spec.scale <= 0:
            raise WingError("thickness und scale muessen > 0 sein")
        if spec.index < 1:
            raise WingError("index: Scheiben zaehlen ab 1")
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


def build_path(spec: SliceSpec, machine: Machine) -> WingPath:
    tris, zmin, zmax, count = _body(spec)
    if spec.index > count:
        raise WingError(f"Scheibe {spec.index} gibt es nicht: {count} Scheiben zu {spec.thickness:g} mm "
                        f"({spec.axis} von {zmin:.1f} bis {zmax:.1f})")
    k, i, j = _frame(spec)
    z0 = zmin + (spec.index - 1) * spec.thickness
    z1 = min(z0 + spec.thickness, zmax)
    notes_extra: list[str] = []
    if spec.loft:
        a = _orient(_section_at(tris, k, z0, i, j, zmin, zmax), spec.mirror)
        b = _orient(_section_at(tris, k, z1, i, j, zmin, zmax), spec.mirror)
        pa, pb = _pair_loft(a, b, spec.points, machine.kerf_mm, _spar(spec))
        loops_all = a + b
        rear = min(min(q[0] for q in pa), min(q[0] for q in pb))
        shift = spec.block_x + spec.lead - rear
        y0 = pa[0][1]
        pa = [(x + shift, y - y0) for x, y in pa]
        pb = [(x + shift, y - y0) for x, y in pb]
        path = loft(spec, pa, pb, machine)
        kind = "verlaufend"
        if spec.tab > 0:
            notes_extra.append("Haltesteg nur beim prismatischen Schnitt - hier ohne")
        # sides of different size: the wire lines converge and cross somewhere
        # beyond the smaller side; at a tower past that point the contour is inverted
        n = spec.points + 1
        for tower, pts in ((1, path.tower1), (2, path.tower2)):
            if inverted(path.root[:n], pts[:n]):
                path.notes.append(f"Drahtlinien kreuzen sich vor Turm {tower} - dort darf kein Schaum liegen; "
                                  "duennere Scheiben oder 'loft = nein' helfen")
    else:
        mid = _orient(_section_at(tris, k, (z0 + z1) / 2, i, j, zmin, zmax), spec.mirror)
        mid, _ = _prepare(mid, _spar(spec))
        loops_all = mid
        rear = min(q[0] for l in mid for q in l)
        shift = spec.block_x + spec.lead - rear
        mid = [[(x + shift, y) for x, y in l] for l in mid]
        pts, notes_extra = plan(mid, machine.kerf_mm, spec.block_x, spec.tab)
        y0 = pts[0][1]
        rel = [(x, y - y0) for x, y in pts]
        path = loft(spec, rel, list(rel), machine)
        kind = "prismatisch"
    xs = [q[0] for l in loops_all for q in l]; ys = [q[1] for l in loops_all for q in l]
    path.notes.insert(1, f"Scheibe {spec.index} von {count} ({spec.axis} = {z0:.1f}..{z1:.1f} von {zmin:.1f}..{zmax:.1f}), "
                         f"{kind}, Querschnitt {max(xs) - min(xs):.1f} x {max(ys) - min(ys):.1f} mm, "
                         f"{Path(spec.stl).name}")
    if spec.spar_side != "keine":
        path.notes.append(f"Holmnut von {spec.spar_side}: Mitte X={spec.spar_x:g}, Grund Y={spec.spar_y:g}, "
                          f"Breite {spec.spar_w:g} (Koerperkoordinaten)")
    path.notes.extend(notes_extra)
    return path


def generate(spec: SliceSpec, machine: Machine, airfoil_dir: Path | None = None) -> tuple[str, WingPath]:
    path = build_path(spec, machine)
    header = ["; foamcut slice: " + path.notes[1],
              f"; Kerf {machine.kerf_mm:g}, Vorschub {machine.cut_feed:g} mm/min"]
    return emit_gcode(path, machine.cut_feed, machine.wire_power, machine.warmup_s, header), path


def slice_name(spec: SliceSpec) -> str:
    stem = Path(spec.stl).stem or "koerper"
    return f"{stem}_scheibe{spec.index}_{spec.thickness:g}mm{'' if spec.loft else '_prisma'}.nc"


def slice_to_text(values: dict[str, str]) -> str:
    return to_text(values, FIELDS, "; foamcut slice")


def slice_from_text(text: str) -> dict[str, str]:
    return from_text(text, FIELDS)


SLICE_MODEL = Model("Scheiben", "slices", FIELDS, SliceSpec.parse, generate, slice_name, slice_to_text,
                    slice_from_text, TEMPLATE, "slices (*.slices);;alle (*)")
