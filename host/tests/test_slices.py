"""STL slabs: reader, sections, loft between the two faces, prismatic fallback."""
import math
import struct
from pathlib import Path

import pytest

from foamcut import gcode as gc
from foamcut import slices as sl
from foamcut.machine import Machine
from foamcut.wing import WingError

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "config" / "beispiel.stl"


def machine(kerf=0.0):
    m = Machine(); m.tower_gap_mm = 615.0; m.tower_gap_measured = True; m.kerf_mm = kerf
    m.travel_mm = {"X": 218.0, "Y": 130.0, "U": 218.0, "V": 130.0}
    return m


def spec(**over):
    s = sl.SliceSpec.parse(sl.TEMPLATE.replace("stl          =             ", f"stl = {EXAMPLE}"))
    for k, v in over.items():
        setattr(s, k, v)
    return s


def box_tris(w=40.0, h=20.0, d=100.0):
    """Closed axis-aligned box 0..w x 0..h x 0..d as triangles."""
    v = [(x, y, z) for z in (0, d) for y in (0, h) for x in (0, w)]
    faces = [(0, 2, 1), (1, 2, 3), (4, 5, 6), (5, 7, 6), (0, 1, 4), (1, 5, 4),
             (2, 6, 3), (3, 6, 7), (0, 4, 2), (2, 4, 6), (1, 3, 5), (3, 7, 5)]
    return [(v[a], v[b], v[c]) for a, b, c in faces]


def write_binary(path: Path, tris):
    out = bytearray(b"\0" * 80) + struct.pack("<I", len(tris))
    for a, b, c in tris:
        out += struct.pack("<12f", 0, 0, 0, *a, *b, *c) + b"\0\0"
    path.write_bytes(out)


# ------------------------------------------------------------------ stl ----
def test_binary_and_ascii_readers_agree(tmp_path):
    tris = box_tris()
    write_binary(tmp_path / "b.stl", tris)
    lines = ["solid box"]
    for a, b, c in tris:
        lines += ["facet normal 0 0 0", "outer loop"] + [f"vertex {p[0]} {p[1]} {p[2]}" for p in (a, b, c)] + ["endloop", "endfacet"]
    lines.append("endsolid box")
    (tmp_path / "a.stl").write_text("\n".join(lines))
    assert sl.load_stl(tmp_path / "b.stl") == sl.load_stl(tmp_path / "a.stl")
    (tmp_path / "x.stl").write_bytes(b"\0" * 90)
    with pytest.raises(WingError, match="falscher Laenge"):
        sl.load_stl(tmp_path / "x.stl")


def test_section_of_a_box_is_its_rectangle_even_through_vertices():
    tris = box_tris()
    for z in (50.0, 0.0, 100.0):                       # 0 and 100 run through mesh vertices
        loops = sl.section(tris, 2, z, 0, 1)
        assert len(loops) == 1
        xs = [p[0] for p in loops[0]]; ys = [p[1] for p in loops[0]]
        assert (min(xs), max(xs), min(ys), max(ys)) == (0.0, 40.0, 0.0, 20.0)


def test_slab_count_and_index_check(tmp_path):
    write_binary(tmp_path / "box.stl", box_tris(d=100.0))
    s = spec(stl=str(tmp_path / "box.stl"), thickness=30.0, index=4)
    _, path = sl.generate(s, machine())
    assert "Scheibe 4 von 4 (z = 90.0..100.0" in path.notes[1]
    with pytest.raises(WingError, match="gibt es nicht"):
        sl.build_path(spec(stl=str(tmp_path / "box.stl"), thickness=30.0, index=5), machine())


# ----------------------------------------------------------------- loft ----
def test_loft_uses_both_faces_and_prism_the_middle():
    a = sl.build_path(spec(index=2), machine())           # body grows from nose to middle
    assert a.root != a.tip
    assert max(q[0] for q in a.tip) - min(q[0] for q in a.tip) > max(q[0] for q in a.root) - min(q[0] for q in a.root)
    b = sl.build_path(spec(index=2, loft=False), machine())
    assert b.root == b.tip
    assert "prismatisch" in b.notes[1] and "verlaufend" in a.notes[1]


def test_lofted_program_is_valid_and_the_slab_is_the_block_width():
    code, path = sl.generate(spec(index=3), machine())
    prog = gc.Program.parse(code)
    assert not prog.errors
    assert path.block[3] > 0 and abs(path.block_s[0] - path.block_s[1]) == pytest.approx(40.0 + 10.0)   # thickness + margin
    assert path.min_block[5] == pytest.approx(50.0)
    assert "; foamcut slice: Scheibe 3 von 5" in code.splitlines()[0]


def test_axes_can_be_chosen_and_mirrored(tmp_path):
    write_binary(tmp_path / "box.stl", box_tris(w=40.0, h=20.0, d=100.0))
    s = spec(stl=str(tmp_path / "box.stl"), thickness=100.0, index=1, axis="x", up="z", loft=False)
    p = sl.build_path(s, machine())
    xs = [q[0] for q in p.root]; ys = [q[1] for q in p.root]
    # slicing along x: the section is y (20) forward by z (100) up
    assert max(xs) - (s.block_x + s.lead) == pytest.approx(20.0, abs=1e-6)
    assert max(ys) - min(ys) == pytest.approx(100.0, abs=1e-6)
    m = sl.build_path(spec(stl=str(tmp_path / "box.stl"), thickness=100.0, index=1, axis="x", up="z", loft=False,
                           mirror=True), machine())
    assert max(q[0] for q in m.root) - (s.block_x + s.lead) == pytest.approx(20.0, abs=1e-6)


def test_extreme_taper_is_flagged():
    path = sl.build_path(spec(index=1), machine())         # nose: a point at z = 0 against 45 mm at z = 40
    assert any("kreuzen" in n for n in path.notes)


def test_parse_rules_and_name():
    with pytest.raises(WingError, match="verschiedene Achsen"):
        sl.SliceSpec.parse(sl.TEMPLATE.replace("stl          =             ", f"stl = {EXAMPLE}").replace("up           = y", "up = z"))
    s = spec(index=2)
    assert sl.slice_name(s) == "beispiel_scheibe2_40mm.nc"
    s.loft = False
    assert sl.slice_name(s).endswith("_prisma.nc")
    assert s.panel == 40.0                                 # nesting reads the thickness as the span
    vals = sl.slice_from_text(sl.TEMPLATE)
    assert sl.SliceSpec.parse(sl.slice_to_text({**vals, "stl": str(EXAMPLE)})).thickness == 40.0


# ----------------------------------------------------------------- spar ----
def test_notch_cuts_a_slot_from_the_chosen_edge():
    square = [(0, 0), (40, 0), (40, 20), (0, 20)]
    new, keys = sl.notch(square, 15, 21, 12, "oben")
    assert [new[k] for k in keys] == [(21, 20.0), (21, 12), (15, 12), (15, 20.0)]
    assert abs(sl.geom.signed_area(new)) == pytest.approx(40 * 20 - 6 * 8)
    new, keys = sl.notch(square, 15, 21, 8, "unten")
    assert [new[k] for k in keys] == [(15, 0.0), (15, 8), (21, 8), (21, 0.0)]
    with pytest.raises(WingError, match="ausserhalb"):
        sl.notch(square, 50, 56, 12, "oben")
    with pytest.raises(WingError, match="Nutgrund"):
        sl.notch(square, 15, 21, 25, "oben")


def test_spar_slot_is_cut_on_both_faces_and_in_prism_mode():
    from foamcut.contour import classify
    tris, zmin, zmax, count = sl._body(spec(index=3))
    k, i, j = sl._frame(spec())
    for z in (80.0, 120.0):                                   # both faces of slab 3
        loops, keys = sl._prepare(sl.section(tris, k, z, i, j), (-3.0, 3.0, 5.0, "oben"))
        corners = [loops[0][q] for q in keys]
        assert corners[1] == (3.0, 5.0) and corners[2] == (-3.0, 5.0)         # slot floor, body coordinates
        assert corners[0][0] == 3.0 and corners[3][0] == -3.0 and corners[0][1] > 5.0
    p = sl.build_path(spec(index=3, spar_side="oben", spar_x=0.0, spar_y=5.0, spar_w=6.0), machine(kerf=0.0))
    assert len(p.root) == len(p.tip) and any("Holmnut von oben" in n for n in p.notes)
    pr = sl.build_path(spec(index=3, loft=False, spar_side="oben", spar_x=0.0, spar_y=5.0, spar_w=6.0), machine(kerf=0.0))
    assert any("Holmnut" in n for n in pr.notes)
    # kerf: the wire path runs kerf/2 inside the slot walls and above the floor
    notched, keys = sl.notch([(0, 0), (40, 0), (40, 20), (0, 20)], 15, 21, 12, "oben")
    o = classify([notched], kerf=2.0)[0]
    floor = sorted(o.loop[q] for q in keys[1:3])
    assert floor[0] == pytest.approx((16.0, 13.0)) and floor[1] == pytest.approx((20.0, 13.0))
