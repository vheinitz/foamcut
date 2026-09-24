import math
from pathlib import Path

import pytest

from foamcut import airfoil as af
from foamcut import gcode as gc
from foamcut.machine import Machine
from foamcut.wing import TEMPLATE, WingError, WingSpec, build_path, generate

ROOT = Path(__file__).resolve().parents[2]
AIRFOILS = ROOT / "airfoil"

SELIG = """TEST SYMMETRIC
1.0 0.0
0.75 0.04
0.5 0.05
0.25 0.04
0.0 0.0
0.25 -0.04
0.5 -0.05
0.75 -0.04
1.0 0.0
"""
LEDNICER = """TEST LEDNICER
 5.  5.
0.0 0.0
0.25 0.04
0.5 0.05
0.75 0.04
1.0 0.0

0.0 0.0
0.25 -0.04
0.5 -0.05
0.75 -0.04
1.0 0.0
"""


def machine(gap=800.0, travel=None, fixed=2, kerf=1.0, **cut):
    m = Machine()
    for k, v in cut.items():
        setattr(m, k, v)
    m.tower_gap_mm = gap
    m.wire_fixed_tower = fixed
    m.kerf_mm = kerf
    if travel:
        m.travel_mm = travel
    return m


def spec(**over):
    s = WingSpec.parse(TEMPLATE)
    for k, v in over.items():
        setattr(s, k, v)
    return s


# ------------------------------------------------------------- airfoil ----
def test_parse_selig_and_lednicer_give_the_same_surfaces():
    _, u1, l1 = af.parse(SELIG)
    _, u2, l2 = af.parse(LEDNICER)
    assert u1 == u2 and l1 == l2
    assert u1[0] == (0.0, 0.0) and u1[-1][0] == 1.0


def test_resample_pairs_points_and_keeps_the_te_le_te_loop():
    _, u, l = af.parse(SELIG)
    loop = af.resample_loop(u, l, 11)
    assert len(loop) == 21
    assert loop[0][0] == 1.0 and loop[10] == (0.0, 0.0) and loop[-1][0] == 1.0
    assert all(y >= 0 for _, y in loop[:11]) and all(y <= 0 for _, y in loop[10:])


def test_offset_loop_moves_outward():
    _, u, l = af.parse(SELIG)
    loop = af.resample_loop(u, l, 21)
    out = af.offset_loop(loop, 0.01)
    mid_up = 5                      # upper surface, somewhere mid chord
    assert out[mid_up][1] > loop[mid_up][1]
    mid_lo = len(loop) - 6
    assert out[mid_lo][1] < loop[mid_lo][1]


def test_real_clarky_loads():
    name, u, l = af.load(AIRFOILS / "clarky.dat")
    assert "CLARK" in name.upper()
    thick = max(y for _, y in u) - min(y for _, y in l)
    assert 0.10 < thick < 0.13          # Clark Y is ~11.7 % thick


# ---------------------------------------------------------------- spec ----
def test_template_parses_and_fills_defaults():
    s = WingSpec.parse(TEMPLATE)
    assert s.tip_airfoil == s.root_airfoil
    assert s.mirror is False


def test_legacy_side_maps_to_mirror():
    """Old .wing files said side = links|rechts; rechts was root at tower 2 = the fixed wire."""
    from foamcut.wing import from_text
    assert WingSpec.parse(TEMPLATE + "\nside = rechts\n").mirror is False
    assert WingSpec.parse(TEMPLATE + "\nside = links\n").mirror is True
    assert from_text("side = links\n")["mirror"] == "ja"
    with pytest.raises(WingError, match="side"):
        WingSpec.parse(TEMPLATE + "\nside = oben\n")


def test_spec_errors():
    with pytest.raises(WingError, match="fehlt"):
        WingSpec.parse("root_chord = 100\n")
    with pytest.raises(WingError, match="unbekannt"):
        WingSpec.parse(TEMPLATE + "\nfoo = 1\n")
    with pytest.raises(WingError, match="Zahl"):
        WingSpec.parse(TEMPLATE.replace("root_chord   = 100", "root_chord = abc"))
    with pytest.raises(WingError, match="mirror"):
        WingSpec.parse(TEMPLATE.replace("mirror       = nein", "mirror = vielleicht"))


def test_panel_longer_than_the_machine_is_only_a_warning():
    """A part can be meant as a body (STL) to be cut as ribs later, so an
    over-long panel is reported, not refused."""
    p = build_path(spec(panel=700.0, root_gap=150.0), machine(gap=615.0), AIRFOILS)
    assert any(n.startswith("ZU LANG FUER DIE MASCHINE") and "615" in n for n in p.notes)
    assert p.root and p.tip                                  # the geometry is still built
    from foamcut.wing import to_stl
    assert to_stl(spec(panel=700.0, root_gap=150.0), machine(gap=615.0), AIRFOILS)[:7] == b"foamcut"
    ok = build_path(spec(panel=400.0, root_gap=150.0), machine(gap=615.0), AIRFOILS)
    assert not any("ZU LANG" in n for n in ok.notes)


# ------------------------------------------------------------ geometry ----
def test_profiles_sit_where_the_spec_says():
    """The block face is the anchor; the trailing edge sits `lead` in front of it."""
    s = spec(root_chord=100.0, tip_chord=80.0, block_x=8.0, lead=12.0, chord_y=45.0, sweep=0.0)
    p = build_path(s, machine(kerf=0.0), AIRFOILS)
    assert p.root[0] == pytest.approx((20.0, 45.0), abs=1e-6)          # TE at block_x + lead
    assert max(x for x, _ in p.root) == pytest.approx(120.0, abs=1e-6)  # LE at TE + chord
    assert max(x for x, _ in p.tip) == pytest.approx(120.0, abs=1e-6)   # LE aligned, no sweep
    assert min(x for x, _ in p.tip) == pytest.approx(40.0, abs=1e-6)    # tip TE = 20 + 100 - 80
    assert p.entry_root == p.entry_tip == (8.0, 45.0)                    # wire enters at the block face


def test_lead_moves_the_profile_not_the_block():
    a = build_path(spec(lead=10.0), machine(kerf=0.0), AIRFOILS)
    b = build_path(spec(lead=25.0), machine(kerf=0.0), AIRFOILS)
    assert a.block[0] == b.block[0] == a.entry_root[0]
    assert b.root[0][0] - a.root[0][0] == pytest.approx(15.0)


def test_rearmost_trailing_edge_gets_the_lead():
    """Tip TE further back than the root TE (strong sweep): the tip TE is the one
    `lead` in front of the face, the root TE further forward."""
    s = spec(root_chord=100.0, tip_chord=80.0, sweep=40.0, block_x=8.0, lead=12.0)
    p = build_path(s, machine(kerf=0.0), AIRFOILS)
    assert min(x for x, _ in p.tip) == pytest.approx(20.0, abs=1e-6)
    assert min(x for x, _ in p.root) == pytest.approx(40.0, abs=1e-6)


def test_legacy_te_x_places_the_block_face_lead_behind_it():
    from foamcut.wing import from_text
    old = TEMPLATE.replace("block_x      = 20", "te_x = 20").replace("lead         = 12", "lead = 12")
    assert WingSpec.parse(old).block_x == pytest.approx(8.0)
    assert from_text("te_x = 20\nlead = 12\n")["block_x"] == "8"


def test_min_block_wraps_the_cut_with_the_margins():
    s = spec(margin=7.0)
    p = build_path(s, machine(kerf=0.0), AIRFOILS)
    bx, by, bl, bh, start, width = p.min_block
    pts = p.faces[0][1] + p.faces[1][1]
    assert bx == s.block_x and start == 0 and width == pytest.approx(s.panel + 7.0)
    assert by == pytest.approx(min(y for _, y in pts) - 7.0)
    assert bx + bl == pytest.approx(max(x for x, _ in pts) + 7.0)
    assert by + bh == pytest.approx(max(y for _, y in pts) + 7.0)
    assert p.block == (bx, by, bl, bh)                     # empty block fields = minimal block
    assert any(n.startswith("Mindestblock") for n in p.notes)
    assert not any("ragt" in n for n in p.notes)


def test_sweep_moves_the_tip_back():
    p = build_path(spec(sweep=10.0), machine(kerf=0.0), AIRFOILS)
    root_le = max(x for x, _ in p.root)
    assert max(x for x, _ in p.tip) == pytest.approx(root_le - 10.0, abs=1e-6)


def test_washout_puts_the_tip_nose_down():
    flat = build_path(spec(washout=0.0), machine(kerf=0.0), AIRFOILS)
    twisted = build_path(spec(washout=3.0), machine(kerf=0.0), AIRFOILS)
    i_le = len(flat.tip) // 2
    assert twisted.tip[i_le][1] < flat.tip[i_le][1]


def test_kerf_widens_the_contour():
    a = build_path(spec(), machine(kerf=0.0), AIRFOILS)
    b = build_path(spec(), machine(kerf=2.0), AIRFOILS)
    i = len(a.root) // 4               # upper surface
    assert b.root[i][1] > a.root[i][1]


def test_root_and_tip_at_the_towers_means_carriages_follow_the_profiles():
    """root_gap = 0 and panel = tower_gap: the carriage paths are the profiles."""
    s = spec(root_gap=0.0, panel=800.0)
    p = build_path(s, machine(gap=800.0, fixed=1, kerf=0.0), AIRFOILS)
    for a, b in zip(p.tower1, p.root):
        assert a == pytest.approx(b, abs=1e-9)
    for a, b in zip(p.tower2, p.tip):
        assert a == pytest.approx(b, abs=1e-9)


def test_root_sits_at_the_fixed_wire_tower():
    """The clamped wire end is the precise reference; the machine decides, not the wing."""
    at1 = build_path(spec(), machine(fixed=1, kerf=0.0), AIRFOILS)
    at2 = build_path(spec(), machine(fixed=2, kerf=0.0), AIRFOILS)
    assert at1.root_tower == 1 and at2.root_tower == 2
    assert at1.s_root == pytest.approx(at2.tower_gap - at2.s_root)
    for a, b in zip(at1.tower1, at2.tower2):
        assert a == pytest.approx(b, abs=1e-9)
    assert "Turm 2 (Draht fest" in at2.notes[0]


def test_mirror_flips_the_profiles_about_the_chord_line():
    """Mirrored = same span placement, profile upside down about its chord line
    (each version sits `margin` above the same table, so the chord heights differ).
    Turning the cut piece over yields the other-hand wing."""
    plain = build_path(spec(washout=3.0), machine(kerf=0.0), AIRFOILS)
    sp = spec(washout=3.0); sp.mirror = True
    mirr = build_path(sp, machine(kerf=0.0), AIRFOILS)
    assert mirr.s_root == plain.s_root and mirr.mirrored
    assert mirr.table_y == plain.table_y == sp.table_y
    for a, b in zip(plain.root, mirr.root):
        assert b[0] == pytest.approx(a[0])
        assert b[1] - mirr.chord_y == pytest.approx(-(a[1] - plain.chord_y))
    assert mirr.entry_root == (sp.block_x, mirr.chord_y)
    code, _ = generate(sp, machine(), AIRFOILS)
    assert "spiegelverkehrt" in code.splitlines()[0]


def test_profile_sits_margin_above_the_table():
    s = spec(table_y=17.0, margin=6.0)
    p = build_path(s, machine(kerf=0.0), AIRFOILS)
    pts = p.faces[0][1] + p.faces[1][1]
    assert min(y for _, y in pts) == pytest.approx(23.0)
    assert p.block[1] == pytest.approx(17.0) and p.table_y == 17.0
    assert p.chord_y > 17.0


def test_lowest_table_puts_the_carriages_at_zero():
    s = spec(root_chord=120.0, tip_chord=50.0)      # taper: tower paths dip below the block
    p = build_path(s, machine(kerf=0.0), AIRFOILS)
    s.table_y = p.table_range[0]
    q = build_path(s, machine(travel={"X": 220.0, "Y": 100.0, "U": 220.0, "V": 100.0}), AIRFOILS)
    assert min(y for _, y in q.tower1 + q.tower2) == pytest.approx(0.0, abs=1e-6)
    assert q.table_range[1] > q.table_range[0]
    s.table_y = q.table_range[1] + 5
    assert any(n.startswith("Tisch zu hoch") for n in build_path(s, machine(travel=q and {"X": 220.0, "Y": 100.0, "U": 220.0, "V": 100.0}), AIRFOILS).notes)
    s.table_y = p.table_range[0] - 5
    assert any(n.startswith("Tisch zu niedrig") for n in build_path(s, machine(), AIRFOILS).notes)


def test_table_extent_stops_where_the_wire_dips_under_it():
    """Rectangular untwisted panel: the wire never goes lower than in the block,
    the table may run tower to tower. Tapered: beyond the tip the extrapolated
    lower surface sinks, the table must end before the tower."""
    rect = build_path(spec(tip_chord=100.0, root_chord=100.0), machine(kerf=0.0), AIRFOILS)
    assert rect.table_max[0] == 0.0 and rect.table_max[1] == rect.tower_gap
    # strong taper: the wire lines cross at s~170 and the mirrored profile beyond
    # the apex reaches below the table height at tower 1
    tap = build_path(spec(root_chord=120.0, tip_chord=20.0, margin=1.0), machine(kerf=0.0), AIRFOILS)
    s_lo, s_hi, x_lo, x_hi = tap.table_max
    lo_b, hi_b = sorted(tap.block_s)
    assert s_lo <= lo_b and s_hi >= hi_b                 # always at least under the block
    assert s_lo > 0.0 or s_hi < tap.tower_gap            # ... but not all the way on the tip side
    assert x_lo == 5.0 and x_hi == tap.block[0] + tap.block[2]
    assert any(n.startswith("Tisch:") for n in tap.notes)


def test_legacy_chord_y_gives_the_same_cut():
    new = build_path(spec(table_y=20.0), machine(kerf=0.0), AIRFOILS)
    old = TEMPLATE.replace("table_y      = 20", f"chord_y = {new.chord_y:.6f}") + "kerf = 0.7\n"   # old files carry a kerf: ignored
    p = build_path(WingSpec.parse(old), machine(kerf=0.0), AIRFOILS)
    assert p.table_y == pytest.approx(20.0, abs=1e-5)
    for a, b in zip(p.root + p.tip, new.root + new.tip):
        assert a == pytest.approx(b, abs=1e-5)
    with pytest.raises(WingError, match="table_y"):
        WingSpec.parse(TEMPLATE.replace("table_y      = 20", "table_y ="))


def test_area_and_taper_give_the_chords():
    from foamcut.wing import chords_from_area
    assert chords_from_area(15.0, 500.0, 1.0) == pytest.approx((300.0, 300.0))   # 15 dm² rectangle
    r, t = chords_from_area(15.0, 500.0, 0.5)
    assert (r + t) / 2 * 500.0 == pytest.approx(150000.0) and t == pytest.approx(r / 2)
    sp = WingSpec.parse(TEMPLATE.replace("area         =", "area = 0.4").replace("taper        = 1", "taper = 0.6"))
    assert (sp.root_chord + sp.tip_chord) / 2 * sp.panel == pytest.approx(4000.0)
    assert sp.tip_chord == pytest.approx(0.6 * sp.root_chord)
    with pytest.raises(WingError, match="area"):
        WingSpec.parse(TEMPLATE.replace("area         =", "area = -1"))


def test_aileron_hinge_cut_goes_up_from_the_lower_surface():
    from foamcut.wing import AILERON_STEPS
    plain = build_path(spec(), machine(kerf=1.0), AIRFOILS)
    s = spec(aileron=25.0, hinge_skin=2.0, hinge_v=4.0)
    p = build_path(s, machine(), AIRFOILS)
    extra = 2 * AILERON_STEPS
    assert len(p.root) == len(plain.root) + extra and len(p.tip) == len(p.root)
    assert p.root[:len(plain.root)] == pytest.approx(plain.root)      # profile untouched
    te_x = s.block_x + s.lead                                          # true TE (root[0] is kerf/2 behind)
    x_h = te_x + 0.25 * s.root_chord
    apex = p.root[len(plain.root) + AILERON_STEPS - 1]
    assert apex[0] == pytest.approx(x_h)
    y_upper = max(y for x, y in plain.root if abs(x - x_h) < 3.0)
    assert apex[1] == pytest.approx(y_upper - 1.0 - 2.0, abs=0.4)      # kerf + skin below the wire line
    legs = p.root[len(plain.root) + AILERON_STEPS - 2], p.root[len(plain.root) + AILERON_STEPS]
    assert legs[0][0] == pytest.approx(x_h - 2.0) and legs[1][0] == pytest.approx(x_h + 2.0)
    assert p.root[-1] == pytest.approx(plain.root[-1])                 # back at the trailing edge
    code, _ = generate(s, machine(), AIRFOILS)
    assert "Ruder 25" in code.splitlines()[0] and any(n.startswith("Ruderschnitt") for n in p.notes)
    assert not gc.Program.parse(code).errors


def test_block_bottom_is_the_table_and_old_block_y_becomes_table_y():
    p = build_path(spec(table_y=33.0), machine(kerf=0.0), AIRFOILS)
    assert p.block[1] == pytest.approx(33.0)
    old = TEMPLATE.replace("table_y      = 20", "table_y =").replace("block_h      =", "block_y = 12\nblock_h =")
    assert WingSpec.parse(old).table_y == 12.0
    from foamcut.wing import from_text
    assert from_text("block_y = 12\n")["table_y"] == "12"
    assert "block_y" not in from_text("")


def test_dihedral_is_reported_not_cut():
    plain = build_path(spec(), machine(kerf=0.0), AIRFOILS)
    p = build_path(spec(dihedral=5.0), machine(kerf=0.0), AIRFOILS)
    assert p.root == plain.root and p.tip == plain.tip
    note = next(n for n in p.notes if n.startswith("V-Form 5"))
    assert "schleifen" in note and "35 mm hoeher" in note           # 400 * sin 5 deg


def test_rapids_lift_before_moving_over_the_table():
    code, path = generate(spec(), machine(kerf=0.0), AIRFOILS)
    g0 = [l for l in code.splitlines() if l.startswith("G0 ")]
    assert g0[0].startswith("G0 Y") and "X" not in g0[0].split(";")[0]
    assert g0[1].startswith("G0 X") and "Y" not in g0[1].split(";")[0]
    assert g0[-1].startswith("G0 Y0 V0")
    tail = [l.split(";")[0].strip() for l in code.splitlines() if l.split(";")[0].strip()][-4:]
    # back at cut feed with the wire still hot, off only once the carriages are at X0/U0
    assert tail == ["G1 X0 U0 F300", "M5", "G0 Y0 V0", "M2"]


def test_extrapolation_is_linear_in_span():
    s = spec()
    p = build_path(s, machine(kerf=0.0), AIRFOILS)
    i = 7
    r, t, t1, t2 = p.root[i], p.tip[i], p.tower1[i], p.tower2[i]
    # the four points are collinear when parametrised by s
    def at(sv):
        f = (sv - p.s_root) / (p.s_tip - p.s_root)
        return (r[0] + (t[0] - r[0]) * f, r[1] + (t[1] - r[1]) * f)
    assert t1 == pytest.approx(at(0.0), abs=1e-9)
    assert t2 == pytest.approx(at(p.tower_gap), abs=1e-9)


# -------------------------------------------------------------- g-code ----
def test_generated_gcode_is_valid_and_one_pass():
    code, path = generate(spec(), machine(wire_power=150), AIRFOILS)
    prog = gc.Program.parse(code)
    assert not prog.errors, prog.errors
    lines = code.splitlines()
    assert sum(1 for l in lines if l.startswith("M3")) == 1
    assert "M3 S150" in code
    assert sum(1 for l in lines if l.startswith("G93")) == 1
    assert lines[-1] == "M2"
    # ends where it entered: the exit move returns to the entry point
    g1 = [l for l in lines if l.startswith("G1 ")][:-1]       # the last G1 is the hot retreat to X0/U0
    assert g1[-1].split(" F")[0][3:] == " ".join(
        f"{a}{v:.3f}" for a, v in zip(AXES_ORDER, (path.entry_t1[0], path.entry_t1[1],
                                                  path.entry_t2[0], path.entry_t2[1])))


AXES_ORDER = ("X", "Y", "U", "V")


def test_feed_is_inverse_time_of_the_faster_plane():
    s = spec()
    code, path = generate(s, machine(kerf=0.0, cut_feed=200.0), AIRFOILS)
    first = [l for l in code.splitlines() if l.startswith("G1 ")][0]
    f = float(first.split("F")[-1])
    seg = max(math.dist(path.entry_root, path.root[0]), math.dist(path.entry_tip, path.tip[0]))
    assert f == pytest.approx(200.0 / seg, rel=1e-3)


def test_wire_zero_emits_s1_for_the_gui_slider():
    code, _ = generate(spec(), machine(wire_power=0), AIRFOILS)
    assert "M3 S1" in code


def test_travel_check_catches_a_too_big_wing():
    m = machine(travel={"X": 155.0, "Y": 100.0, "U": 155.0, "V": 100.0})
    _, path = generate(spec(root_chord=200.0, tip_chord=150.0), m, AIRFOILS)
    problems = m.check_extents(path.extents())
    assert any(p.startswith("X:") for p in problems)


def test_template_fits_the_measured_machine():
    m = machine(travel={"X": 155.0, "Y": 100.0, "U": 155.0, "V": 100.0})
    _, path = generate(spec(), m, AIRFOILS)
    assert m.check_extents(path.extents()) == []


def test_cli_wing_writes_a_file(tmp_path, capsys):
    from foamcut.cli import main
    w = tmp_path / "t.wing"
    w.write_text(TEMPLATE)
    out = tmp_path / "t.nc"
    assert main(["wing", str(w), "-o", str(out), "--airfoils", str(AIRFOILS)]) == 0
    assert out.exists() and "G93" in out.read_text()
    assert "Schlittenweg" in capsys.readouterr().out


def test_form_values_round_trip_through_text():
    from foamcut.wing import field_catalogue, from_text, to_text
    vals = {k: d for k, (_, _, d, _, _) in field_catalogue().items()}
    vals["root_chord"] = "123"
    vals["mirror"] = "ja"
    back = from_text(to_text(vals))
    assert back["root_chord"] == "123" and back["mirror"] == "ja"
    assert WingSpec.parse(to_text(back)).root_chord == 123.0


def test_every_field_has_a_label_unit_and_help():
    from foamcut.wing import FIELDS
    for _, _, fields in FIELDS:
        for key, label, unit, default, help_, kind in fields:
            assert label and help_, key
            assert kind in ("num", "int", "airfoil", "bool", "text", "opttext") or kind.startswith(("choice:", "file:")), key
            assert hasattr(WingSpec(), key), key


def test_template_is_generated_from_the_catalogue():
    from foamcut.wing import field_catalogue
    for key, (label, unit, default, help_, kind) in field_catalogue().items():
        assert f"{key}" in TEMPLATE and label in TEMPLATE


def test_block_span_position_gives_the_sections_actually_cut():
    # root 120 at s=750 (rechts, root_gap 50), tip 50 at s=350; a 140 mm block
    # 280 mm from the root sits at s=470..330 - what the user had on the table.
    s = spec(root_chord=120.0, tip_chord=50.0, root_gap=50.0,
             block_s=280.0, block_w=140.0)
    p = build_path(s, machine(kerf=0.0), AIRFOILS)
    assert p.block_s == pytest.approx((470.0, 330.0))
    (sa, face_a), (sb, face_b) = p.faces
    chord = lambda pts: max(x for x, _ in pts) - min(x for x, _ in pts)
    assert chord(face_a) == pytest.approx(71.0, abs=0.1)
    assert chord(face_b) == pytest.approx(46.5, abs=0.1)
    assert any("Block bei s=330..470" in n for n in p.notes)


def test_block_defaults_to_the_whole_panel_plus_margin():
    s = spec()
    p = build_path(s, machine(kerf=0.0), AIRFOILS)
    lo, hi = sorted(p.block_s)
    assert hi - lo == pytest.approx(s.panel + s.margin)
    assert p.s_root in (lo, hi)


def test_block_outside_the_towers_is_reported():
    p = build_path(spec(block_s=700.0, block_w=100.0), machine(kerf=0.0), AIRFOILS)
    assert any("ausserhalb" in n for n in p.notes)


def test_block_fit_check_uses_the_block_faces_not_the_root():
    # a 14 mm high block on the table, no margin: the 120 mm root (14.6 mm
    # thick) would not fit, the 60 mm section in the middle does
    s = spec(root_chord=120.0, tip_chord=50.0, root_gap=50.0,
             block_s=280.0, block_w=140.0, block_h=14.0, table_y=0.0, margin=0.0, kerf=0.0)
    p = build_path(s, machine(), AIRFOILS)
    assert not any("ragt" in n for n in p.notes)
    s.block_s, s.block_w = 0.0, 140.0          # now at the root
    p = build_path(s, machine(), AIRFOILS)
    assert any("ragt" in n for n in p.notes)


def test_unmeasured_tower_gap_is_flagged():
    m = machine()
    m.tower_gap_measured = False
    _, p = generate(spec(), m, AIRFOILS)
    assert any("NICHT GEMESSEN" in n for n in p.notes)
    m.tower_gap_measured = True
    _, p = generate(spec(), m, AIRFOILS)
    assert not any("NICHT GEMESSEN" in n for n in p.notes)


def test_apex_of_a_tapered_wing_is_reported():
    # 120 -> 50 over 400 with the root 50 from tower 2: lines cross 64 from tower 1
    p = build_path(spec(root_chord=120.0, tip_chord=50.0, root_gap=50.0),
                   machine(kerf=0.0), AIRFOILS)
    note = [n for n in p.notes if "kreuzen" in n]
    assert note and "s=64" in note[0]
    # a rectangular wing has no apex
    p = build_path(spec(root_chord=100.0, tip_chord=100.0), machine(kerf=0.0), AIRFOILS)
    assert not any("kreuzen" in n for n in p.notes)


def test_cli_machine_set_tower_gap(tmp_path, capsys):
    from foamcut.cli import main
    mp = tmp_path / "machine.json"
    Machine().save(mp)
    assert main(["--machine", str(mp), "machine", "show"]) == 0
    assert "NICHT gemessen" in capsys.readouterr().out
    assert main(["--machine", str(mp), "machine", "set", "--tower-gap", "642"]) == 0
    m = Machine.load(mp)
    assert m.tower_gap_mm == 642.0 and m.tower_gap_measured
    assert main(["--machine", str(mp), "machine", "set", "--tower-gap", "0"]) == 2


def test_every_program_carries_a_machine_readable_job_line():
    """Line 2: block, placement, root tower, time, travel - for a controller
    that holds the file without foamcut (ESP32 program page)."""
    code, path = generate(spec(), machine(kerf=0.0), AIRFOILS)
    line = code.splitlines()[1]
    assert line.startswith("; foamcut-job block=")
    kv = dict(tok.split("=", 1) for tok in line[len("; foamcut-job "):].split())
    mb = path.min_block
    assert kv["block"] == f"{mb[2]:.0f}x{mb[3]:.0f}x{mb[5]:.0f}" and kv["x"] == "20" and kv["root"] == "T2"
    assert kv["time"].endswith("min") and kv["travel"].startswith("X0..")


# --------------------------------------------------------------- spars ----
def test_spar_syntax():
    from foamcut.wing import parse_spars
    a, b = parse_spars("0 6x4; 180 innen 8x5")
    assert (a.deg, a.inner, a.w, a.h) == (0.0, False, 6.0, 4.0)
    assert (b.deg, b.inner, b.w, b.h) == (180.0, True, 8.0, 5.0)
    assert parse_spars("90° 6x4")[0].deg == 90.0 and parse_spars("") == []
    assert parse_spars("aus 0 6x4") == []                    # switched off keeps its value
    old, = parse_spars("30% oben 6x4")                       # older files still work
    assert (old.dist, old.rel, old.where, old.deg) == (30.0, True, "oben", None)
    for bad in ("30 schraeg 6x4", "6x4", "0 6", "0 0x4"):
        with pytest.raises(WingError):
            parse_spars(bad)


def test_spar_notch_is_cut_square_to_the_skin_and_scales_with_the_chord():
    from foamcut import airfoil as af, geom
    from foamcut.wing import apply_spars, parse_spars, _profile_mm
    s = spec()
    _, up, lo = af.load(AIRFOILS / s.root_airfoil)
    base = _profile_mm(af.resample_loop(up, lo, s.points), s.root_chord, 0.0, 0.0, 0.0, 0.0, None)
    for chord, te_x in ((s.root_chord, 0.0), (s.tip_chord, 20.0)):
        prof = _profile_mm(af.resample_loop(up, lo, s.points), chord, te_x, 0.0, 0.0, 0.0, None)
        outer, holes, keys = apply_spars(prof, chord, te_x, parse_spars("0 6x4"))
        assert len(keys) == 4 and not holes
        corners = [outer[k] for k in keys]
        mouth = sorted(corners, key=lambda q: -q[1])[:2]          # the two at the skin
        floor = sorted(corners, key=lambda q: q[1])[:2]
        assert math.dist(floor[0], floor[1]) == pytest.approx(6.0, abs=1e-6)     # 6 mm wide
        wall = min(math.dist(m, f) for m in mouth for f in floor)
        assert wall == pytest.approx(4.0, abs=1e-6)                              # 4 mm deep
        # the slot sits where the ray straight up leaves the outline
        x = geom.centre_of(prof[:-1])[0]
        assert (mouth[0][0] + mouth[1][0]) / 2 == pytest.approx(x, abs=0.5)
        _, t, n = geom.surface_at(prof[:-1], x, True)
        v = (floor[0][0] - floor[1][0], floor[0][1] - floor[1][1])
        assert abs(v[0] * n[0] + v[1] * n[1]) < 1e-6                             # floor parallel to the skin


def test_spar_notch_pairs_both_sides_in_the_cut():
    s = spec(holm1="0 6x4")
    p = build_path(s, machine(kerf=0.0), AIRFOILS)
    plain = build_path(spec(), machine(kerf=0.0), AIRFOILS)
    assert len(p.root) == len(p.tip) and any("Holmnuten" in n for n in p.notes)
    assert abs(max(q[1] for q in p.root) - max(q[1] for q in plain.root)) < 0.05     # skin untouched


def test_several_spars_all_get_cut():
    s = spec(holm1="0 6x4", holm3="70 5x4", holm5="180 8x3")
    p = build_path(s, machine(kerf=0.0), AIRFOILS)
    plain = build_path(spec(), machine(kerf=0.0), AIRFOILS)
    assert len(p.root) == len(p.tip)
    note = next(n for n in p.notes if n.startswith("Holmnuten"))
    assert note.count("°") == 3
    # three slots -> the outline lost area; every slot floor is somewhere inside
    from foamcut import geom
    assert abs(geom.signed_area(p.root[:-1])) < abs(geom.signed_area(plain.root[:-1])) - 6 * 4 - 5 * 4 - 8 * 3 + 2


def test_legacy_one_line_spar_field_still_works():
    p = build_path(spec(spars="0 6x4"), machine(kerf=0.0), AIRFOILS)
    assert any("Holmnuten" in n for n in p.notes)


def test_inner_holes_are_only_in_the_body_not_in_the_wire_path():
    p = build_path(spec(holm1="0 innen 5x4"), machine(kerf=0.0), AIRFOILS)
    assert any("Innenloecher" in n and "STL" in n for n in p.notes)
    assert p.root == build_path(spec(), machine(kerf=0.0), AIRFOILS).root      # cut unchanged


def test_stl_is_a_watertight_body_with_the_spar_slots():
    from collections import Counter
    from foamcut import geom, slices as sl
    from foamcut.wing import to_stl
    s = spec(holm1="0 6x4", holm2="180 innen 5x4", panel=400.0)
    data = to_stl(s, machine(), AIRFOILS)
    assert data[:7] == b"foamcut" and len(data) > 84
    tris = sl.load_stl_bytes(data) if hasattr(sl, "load_stl_bytes") else None
    import tempfile, pathlib
    with tempfile.TemporaryDirectory() as d:
        f = pathlib.Path(d) / "w.stl"; f.write_bytes(data)
        tris = sl.load_stl(f)
    edges = Counter()
    for a, b, c in tris:
        for u, v in ((a, b), (b, c), (c, a)):
            edges[tuple(sorted((tuple(round(x, 4) for x in u), tuple(round(x, 4) for x in v))))] += 1
    assert all(v == 2 for v in edges.values())            # closed surface: every edge exactly twice
    for z, chord in ((1.0, s.root_chord), (399.0, s.tip_chord)):
        loops = sl.section(tris, 2, z, 0, 1)
        assert len(loops) == 2                            # outline plus the spar hole
        hole = min(loops, key=lambda l: abs(geom.signed_area(l)))
        assert abs(geom.signed_area(hole)) == pytest.approx(20.0, abs=0.1)     # 5 x 4 mm
        outer = max(loops, key=lambda l: abs(geom.signed_area(l)))
        assert max(q[0] for q in outer) - min(q[0] for q in outer) == pytest.approx(chord, abs=0.2)


def test_a_spar_can_be_switched_off_without_losing_its_value():
    from foamcut.wing import spar_list
    s = spec(holm1="0 6x4", holm2="aus 90 5x4")
    assert [sp.deg for sp in spar_list(s)] == [0.0]            # only the active one is cut
    p = build_path(s, machine(kerf=0.0), AIRFOILS)
    assert next(n for n in p.notes if n.startswith("Holmnuten")).count("°") == 1
    s.holm2 = "90 5x4"
    assert [sp.deg for sp in spar_list(s)] == [0.0, 90.0]      # the value was still there


# ---------------------------------------------------------------- NACA ----
def test_naca_numbers_are_computed_instead_of_loaded():
    from foamcut import airfoil as af
    name, up, lo = af.naca4("2412")
    xs = [k / 200 for k in range(201)]
    thick = max(af._interp(up, x) - af._interp(lo, x) for x in xs)
    camber = max((af._interp(up, x) + af._interp(lo, x)) / 2 for x in xs)
    at = max(((af._interp(up, x) + af._interp(lo, x)) / 2, x) for x in xs)[1]
    assert name == "NACA 2412"
    assert thick == pytest.approx(0.12, abs=0.002)          # 12 % thick
    assert camber == pytest.approx(0.02, abs=0.002)         # 2 % camber
    assert at == pytest.approx(0.40, abs=0.02)              # at 40 % of the chord
    assert af._interp(up, 1.0) == pytest.approx(af._interp(lo, 1.0), abs=1e-6)   # closed trailing edge
    sym_up, sym_lo = af.naca4("0012")[1:]
    assert af._interp(sym_up, 0.3) == pytest.approx(-af._interp(sym_lo, 0.3), abs=1e-9)
    for bad in ("241", "naca24123", "abc"):
        with pytest.raises(ValueError):
            af.naca4(bad)


def test_a_wing_can_be_cut_straight_from_naca_numbers():
    p = build_path(spec(root_airfoil="naca2412", tip_airfoil="0012", root_chord=100.0, tip_chord=100.0),
                   machine(kerf=0.0), AIRFOILS)
    root_t = max(q[1] for q in p.root) - min(q[1] for q in p.root)
    tip_t = max(q[1] for q in p.tip) - min(q[1] for q in p.tip)
    assert root_t == pytest.approx(12.0, abs=0.3) and tip_t == pytest.approx(12.0, abs=0.3)
    assert len(p.root) == len(p.tip)                        # still paired point for point
    # the cambered root sits higher than the symmetric tip
    assert max(q[1] for q in p.root) > max(q[1] for q in p.tip) + 1.0
    code, path = generate(spec(root_airfoil="2412"), machine(), AIRFOILS)
    assert "naca" in code.lower() or "2412" in code
    with pytest.raises(WingError, match="nicht gefunden"):
        build_path(spec(root_airfoil="gibtsnicht"), machine(), AIRFOILS)
    with pytest.raises(WingError, match="fuenfstellige"):
        build_path(spec(root_airfoil="naca23012"), machine(), AIRFOILS)
