"""SVG outlines -> prismatic wire path: loader, slits, routing, model."""
import math
from pathlib import Path

import pytest

from foamcut import contour as ct
from foamcut import gcode as gc
from foamcut import geom
from foamcut.machine import Machine
from foamcut.svg import SvgError, load_svg, parse_transform, path_to_polylines
from foamcut.wing import WingError

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "config" / "beispiel.svg"


def machine(kerf=0.0):
    m = Machine(); m.tower_gap_mm = 615.0; m.tower_gap_measured = True; m.kerf_mm = kerf
    m.travel_mm = {"X": 218.0, "Y": 130.0, "U": 218.0, "V": 130.0}
    return m


def spec(**over):
    s = ct.ContourSpec.parse(ct.TEMPLATE.replace("svg          =             ", f"svg = {EXAMPLE}"))
    for k, v in over.items():
        setattr(s, k, v)
    return s


def svg_file(tmp_path, body, size="width=\"100mm\" height=\"60mm\" viewBox=\"0 0 100 60\""):
    p = tmp_path / "t.svg"
    p.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" {size}>{body}</svg>')
    return p


# ------------------------------------------------------------------ svg ----
def test_path_commands_relative_absolute_and_curves():
    subs = path_to_polylines("M 0 0 h 10 v 10 H 0 Z m 20 0 l 5 0 c 0 5 5 5 5 0 z")
    assert len(subs) == 2 and all(closed for _, closed in subs)
    pts = subs[0][0]
    assert pts == [(0, 0), (10, 0), (10, 10), (0, 10)]
    pts2 = subs[1][0]
    assert pts2[0] == (20, 0) and pts2[1] == (25, 0) and len(pts2) > 4       # curve flattened


def test_arc_is_flattened_onto_the_circle():
    (pts, _), = path_to_polylines("M 0 0 A 10 10 0 0 1 20 0 A 10 10 0 0 1 0 0 Z", step=0.5)
    assert all(math.dist(p, (10, 0)) == pytest.approx(10.0, abs=1e-6) for p in pts)


def test_transforms_compose():
    m = parse_transform("translate(10, 5) scale(2)")
    from foamcut.svg import _apply
    assert _apply(m, (1, 1)) == (12, 7)
    m = parse_transform("rotate(90)")
    x, y = _apply(m, (1, 0))
    assert (round(x, 9), round(y, 9)) == (0, 1)


def test_units_and_y_flip(tmp_path):
    p = svg_file(tmp_path, '<rect x="10" y="0" width="20" height="10"/>')
    loops, warnings = load_svg(p)
    (loop,) = loops
    assert min(q[0] for q in loop) == 10 and max(q[0] for q in loop) == 30
    assert min(q[1] for q in loop) == 50 and max(q[1] for q in loop) == 60     # y up: top of the page is high
    # unitless = px at 96 dpi
    p2 = svg_file(tmp_path, '<rect x="0" y="0" width="96" height="96"/>', size='width="96" height="96"')
    (loop,) = load_svg(p2)[0]
    assert max(q[0] for q in loop) == pytest.approx(25.4)


def test_text_is_reported_and_groups_walked(tmp_path):
    p = svg_file(tmp_path, '<g transform="translate(5,5)"><circle cx="10" cy="10" r="5"/></g><text x="1" y="1">Hi</text>')
    loops, warnings = load_svg(p)
    assert len(loops) == 1 and "Hi" in warnings[0]
    assert min(q[0] for q in loops[0]) == pytest.approx(10.0, abs=0.05)


def test_bad_files(tmp_path):
    p = tmp_path / "x.svg"; p.write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")
    with pytest.raises(SvgError, match="keine geschlossenen"):
        load_svg(p)
    p.write_text("not xml")
    with pytest.raises(SvgError):
        load_svg(p)


# ------------------------------------------------------------ planning ----
def test_hole_hangs_on_a_slit_straight_back():
    outer = [(0, 0), (40, 0), (40, 20), (0, 20)]
    hole = [(15, 5), (25, 5), (25, 15), (15, 15)]
    path, notes = ct.plan([outer, hole], kerf=0.0, entry_x=-10)
    assert path[0] == (-10, 0) and path[-1][0] == -12.0          # from the entry line, out behind the face
    # the slit runs from the hole's rearmost point (15, y) straight back to x = 0
    i = path.index((15, 5))
    assert path[i - 1] == (0, 5) and path[i + 4] == (15, 5) and path[i + 5] == (0, 5)
    assert "1 Teil(e), 1 Loch" in notes[0]


def test_two_pieces_are_cut_one_after_the_other_without_crossing():
    a = [(0, 0), (20, 0), (20, 20), (0, 20)]
    b = [(30, 0), (50, 0), (50, 20), (30, 20)]                     # in front of a
    path, notes = ct.plan([a, b], kerf=0.0, entry_x=-10)
    # no travel segment cuts through a piece
    for p, q in zip(path, path[1:]):
        mid = ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)
        for loop in (a, b):
            if geom.inside(mid, loop):
                on_loop = any(geom.seg_intersect(p, q, loop[i], loop[(i + 1) % 4]) is not None for i in range(4))
                assert on_loop, (p, q)
    assert "2 Teil(e)" in notes[0]


def test_kerf_offsets_outer_out_and_hole_in():
    outer = [(0, 0), (40, 0), (40, 20), (0, 20)]
    hole = [(15, 5), (25, 5), (25, 15), (15, 15)]
    outs = ct.classify([outer, hole], kerf=2.0)
    assert len(outs) == 1 and len(outs[0].holes) == 1
    assert max(q[0] for q in outs[0].loop) == pytest.approx(41.0)
    assert max(q[0] for q in outs[0].holes[0].loop) == pytest.approx(24.0)


def test_route_goes_around_a_hull():
    hull = geom.convex_hull([(10, -5), (20, -5), (20, 5), (10, 5)])
    path = geom.route((0, 0), (30, 0), [hull])
    assert path[0] == (0, 0) and path[-1] == (30, 0) and len(path) > 2
    for p, q in zip(path, path[1:]):
        assert not geom.inside(((p[0] + q[0]) / 2, (p[1] + q[1]) / 2), [(10.1, -4.9), (19.9, -4.9), (19.9, 4.9), (10.1, 4.9)])


# --------------------------------------------------------------- model ----
def test_example_contour_generates_a_valid_prismatic_program():
    code, path = ct.generate(spec(), machine())
    prog = gc.Program.parse(code)
    assert not prog.errors
    assert path.root == path.tip                                   # parallel cut
    for m in prog.moves:
        assert m.end["X"] == pytest.approx(m.end["U"], abs=1e-6)
        assert m.end["Y"] == pytest.approx(m.end["V"], abs=1e-6)
    assert any("3 Teil(e), 2 Loch" in n for n in path.notes)
    assert "Parallelschnitt" in code.splitlines()[3] and code.splitlines()[1].startswith("; foamcut-job block=")


def test_width_scales_and_mirror_flips():
    a = ct.build_path(spec(width=50.0), machine())
    s = spec(width=50.0)
    assert max(q[0] for q in a.root) - (s.block_x + s.lead) == pytest.approx(50.0, abs=1e-6)   # rearmost point at lead
    b = ct.build_path(spec(width=50.0, mirror=True), machine())
    assert min(q[1] for q in b.root) == pytest.approx(min(q[1] for q in a.root), abs=1e-6)  # same height range
    assert a.root != b.root


def test_missing_file_and_legacy_keys():
    with pytest.raises(WingError, match="nicht gefunden"):
        ct.build_path(spec(svg="/nirgends/x.svg"), machine())
    s = ct.ContourSpec.parse(ct.TEMPLATE.replace("svg          =             ", f"svg = {EXAMPLE}") + "kerf = 2\n")
    assert s.svg.endswith("beispiel.svg")
    with pytest.raises(WingError, match="fehlt"):
        ct.ContourSpec.parse(ct.TEMPLATE)


def test_name_and_round_trip():
    s = spec(width=80.0, mirror=True)
    assert ct.contour_name(s) == "beispiel_b80_sp_30.nc"
    vals = ct.contour_from_text(ct.TEMPLATE)
    assert ct.ContourSpec.parse(ct.contour_to_text({**vals, "svg": str(EXAMPLE)})).panel == 30.0


def test_tab_leaves_a_bridge_on_every_loop():
    outer = [(0, 0), (40, 0), (40, 20), (0, 20)]
    hole = [(15, 5), (25, 5), (25, 15), (15, 15)]
    full, _ = ct.plan([outer, hole], kerf=0.0, entry_x=-10)
    tabbed, notes = ct.plan([outer, hole], kerf=0.0, entry_x=-10, tab=3.0)
    assert "Haltesteg 3 mm" in notes[0]
    # the outer walk no longer returns to its rear point (0, 0): it stops 3 mm short on the last edge
    assert (0, 0) in full and full.count((0, 0)) >= 2
    assert tabbed.count((0, 0)) == 1
    assert (0.0, 3.0) in tabbed                      # stop point on the left edge, 3 mm above the rear corner
    # the hole walk stops 3 mm before its rear point too
    assert tabbed.count((15, 5)) == 1 and (15.0, 8.0) in tabbed
    assert ct.trim_tail([(0, 0), (10, 0), (0, 0)], 30.0) == [(0, 0), (10, 0)]     # never eats the loop itself


# ---------------------------------------------------------------- chain ----
def circle(cx, cy, r, n=28):
    return [(cx + r * math.cos(2 * math.pi * k / n), cy + r * math.sin(2 * math.pi * k / n)) for k in range(n)]


def parts_of(loops, kerf=0.0):
    return [ct.part_from_outline(o, 0.0, f"P{i}", kerf) for i, o in enumerate(ct.classify(loops, kerf))]


def test_chain_cuts_every_piece_in_two_arcs_with_one_lead_in():
    parts = parts_of([circle(0, 40, 10), circle(26, 22, 12), circle(52, 40, 9)])
    pa, pb, order, entry = ct.chain_cut(parts, -12.0, 0.0)
    assert pa == pb and pa[0] == entry == (-12.0, 40.0) and pa[-1] == entry
    assert order[0] == 0                                    # top piece first, chain runs downwards
    # one lead-in: exactly one segment crosses the line x = -6 (in and back out on it)
    crossings = [1 for u, v in zip(pa, pa[1:]) if (u[0] + 6) * (v[0] + 6) < 0]
    assert len(crossings) == 2 and pa[1][0] == pytest.approx(-10.0)     # enters the top circle at its rear
    # every piece is walked completely: its whole outline is covered
    for p in parts:
        for q in p.a[:-1]:
            assert min(geom.seg_dist(q, u, v) for u, v in zip(pa, pa[1:])) < 1e-6
    # the hop between two pieces is used twice (out and back), so it is cut once
    hop = [(u, v) for u, v in zip(pa, pa[1:])
           if all(min(geom.seg_dist(w, x, y) for x, y in zip(p.a, p.a[1:])) > 1e-6 for p in parts for w in (u, v))]
    assert not hop                                           # hops start and end on contours


def test_chain_falls_back_to_single_pieces_when_a_hop_would_hit_a_third():
    a, b, c = circle(0, 0, 10), circle(60, 0, 10), circle(30, 0, 14)      # c sits between a and b
    parts = parts_of([a, b, c])
    _, _, _, _, how = ct.cut_parts(parts, -20.0, 0.0)
    assert how in ("Kette", "einzeln")                        # both are valid, but it must not crash
    _, _, _, _, how = ct.cut_parts(parts_of([a, b, c]), -20.0, 0.0, tab=2.0)
    assert how == "einzeln"                                  # a Haltesteg needs the piece-by-piece route


def test_chain_keeps_holes_and_pairs_both_sides():
    parts = parts_of([circle(0, 0, 20), circle(0, 0, 8), circle(50, 0, 15)])
    assert len(parts) == 2 and len(ct.classify([circle(0, 0, 20), circle(0, 0, 8)], 0.0)[0].holes) == 1
    pa, pb, order, entry = ct.chain_cut(parts, -30.0, 0.0)
    assert len(pa) == len(pb)
    inner = [q for q in pa if 7.9 < math.dist(q, (0, 0)) < 8.1]
    assert len(inner) > 10                                   # the hole is cut, on its slit


def test_pieces_packed_tighter_than_the_clearance_still_get_a_route():
    """Neighbours can sit closer than the travel clearance (their rings
    overlap). The wire may then graze a neighbour's ring - it must not give
    up, as long as it does not cut into the piece itself."""
    parts = parts_of([circle(0, 0, 10), circle(23, 0, 10), circle(46, 0, 10)], kerf=0.0)
    pa, pb, order, entry, how = ct.cut_parts(parts, -20.0, 6.0)      # clearance 6 > the 3 mm gaps
    assert how in ("Kette", "einzeln") and len(pa) > 30
    for u, v in zip(pa, pa[1:]):
        for p in parts:
            loop = p.a[:-1]
            mid = ((u[0] + v[0]) / 2, (u[1] + v[1]) / 2)
            if min(geom.seg_dist(mid, loop[i], loop[(i + 1) % len(loop)]) for i in range(len(loop))) < 1e-6:
                continue                                             # cutting along this piece
            assert not geom.inside(mid, loop)                        # never through one
