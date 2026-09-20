"""Free shapes: contours, angle resampling, rings, lofting, G-code."""
import math

import pytest

from foamcut import gcode as gc
from foamcut import shape as sh
from foamcut.machine import Machine
from foamcut.wing import WingError


def machine():
    m = Machine(); m.tower_gap_mm = 615.0; m.tower_gap_measured = True
    return m


def spec(**over):
    s = sh.ShapeSpec.parse(sh.TEMPLATE)
    for k, v in over.items():
        if k[:2] in ("a_", "b_"):
            setattr(getattr(s, k[0]), k[2:], v)
        else:
            setattr(s, k, v)
    return s


def test_contours_have_the_asked_extent():
    for kind in sh.KINDS:
        c = sh.contour(kind, 60.0, 40.0, 0.0)
        xs = [x for x, _ in c]; ys = [y for _, y in c]
        assert max(xs) == pytest.approx(30.0, abs=0.05) and min(xs) == pytest.approx(-30.0, abs=0.05)
        if kind == "kreis":
            assert max(ys) == pytest.approx(30.0, abs=0.05)         # circle: height = width
        else:
            assert max(ys) == pytest.approx(20.0, abs=0.05) and min(ys) == pytest.approx(-20.0, abs=0.05)


def test_rounded_corners_cut_the_corner_but_keep_the_sides():
    c = sh.contour("rechteck", 60.0, 40.0, 8.0)
    assert max(x for x, _ in c) == pytest.approx(30.0) and max(y for _, y in c) == pytest.approx(20.0)
    assert max(abs(x) + abs(y) for x, y in c) == pytest.approx(50.0 - 8.0 * (2 - math.sqrt(2)), abs=0.05)
    tri = sh.contour("dreieck", 60.0, 40.0, 5.0)
    assert max(y for _, y in tri) < 20.0 and min(y for _, y in tri) == pytest.approx(-20.0)


def test_angle_resampling_starts_at_the_rear_and_closes():
    pts = sh.by_angle(sh.contour("rechteck", 60.0, 40.0, 0.0), 8)
    assert len(pts) == 9 and pts[0] == pytest.approx((-30.0, 0.0)) and pts[-1] == pytest.approx(pts[0])
    assert pts[2] == pytest.approx((0.0, -20.0), abs=1e-9)          # CCW: rear -> bottom -> front -> top
    assert pts[4] == pytest.approx((30.0, 0.0), abs=1e-9)
    circ = sh.by_angle(sh.contour("kreis", 40.0, 40.0), 8)
    assert all(math.hypot(x, y) == pytest.approx(20.0, abs=0.05) for x, y in circ)


def test_ring_path_goes_through_a_rear_slit():
    s = spec(a_hole="kreis", b_hole="kreis", kerf=0.0)
    a = sh.side_path(s.a, 12, 0.0)
    n = 13
    assert len(a) == 2 * n + 1
    assert a[0] == pytest.approx((-30.0, 0.0)) and a[n] == pytest.approx((-10.0, 0.0))   # outer rear -> hole rear
    assert a[-1] == pytest.approx(a[0])                                                    # back out
    p = sh.build_path(s, machine())
    assert len(p.root) == len(p.tip) == 2 * n + 1 or len(p.root) == 2 * (s.points + 1) + 1


def test_different_kinds_on_both_sides_pair_point_for_point():
    s = spec(b_kind="ellipse", b_dx=5.0, b_dy=3.0)
    p = sh.build_path(s, machine())
    assert len(p.root) == len(p.tip) == s.points + 1
    # side B is shifted by (dx, dy) relative to A, rear point still leads
    assert min(x for x, _ in p.root) == pytest.approx(s.block_x + s.lead)         # lead ends at the rear-most wire point
    assert p.entry_root == (s.block_x, p.chord_y)
    assert p.block[1] == pytest.approx(s.table_y) and any(n.startswith("Form:") for n in p.notes)


def test_shape_spec_validation():
    with pytest.raises(WingError, match="Loch"):
        sh.ShapeSpec.parse(sh.TEMPLATE.replace("a_hole       = keine", "a_hole = kreis"))
    with pytest.raises(WingError, match="eines von"):
        sh.ShapeSpec.parse(sh.TEMPLATE.replace("a_kind       = rechteck", "a_kind = stern"))
    with pytest.raises(WingError, match="unbekannt"):
        sh.ShapeSpec.parse(sh.TEMPLATE + "\nc_w = 1\n")
    vals = sh.shape_from_text(sh.shape_to_text({"a_kind": "dreieck", "b_hole": "ellipse"}))
    assert vals["a_kind"] == "dreieck" and vals["b_hole"] == "ellipse"


def test_shape_gcode_is_valid_and_returns_to_the_entry():
    code, path = sh.generate(spec(a_hole="rechteck", b_hole="rechteck"), machine())
    prog = gc.Program.parse(code)
    assert not prog.errors and code.startswith("; foamcut shape: A rechteck")
    g1 = [l for l in code.splitlines() if l.startswith("G1 ")]
    assert f"X{path.entry_t1[0]:.3f}" in g1[-1] and sh.shape_name(spec(a_hole="kreis")).endswith("_ring.nc")
