import math

import pytest

from foamcut import AXES
from foamcut import gcode as gc


def test_parse_words_strips_comments():
    assert gc.parse_words("G1 X10 (rapid to start) Y-2.5 ; trailing") == [
        ("G", 1.0), ("X", 10.0), ("Y", -2.5)
    ]


def test_absolute_and_relative_positions():
    prog = gc.Program.parse(
        "G21\nG90\nG1 F300\nG1 X10 Y5 U10 V5\nG91\nG1 X5\n"
    )
    assert not prog.errors
    assert len(prog.moves) == 2
    assert prog.moves[0].end == {"X": 10.0, "Y": 5.0, "U": 10.0, "V": 5.0}
    assert prog.moves[1].end["X"] == 15.0
    assert prog.moves[1].end["Y"] == 5.0  # untouched axes keep their position


def test_inch_units_are_converted():
    prog = gc.Program.parse("G20\nG1 F10\nG1 X1\n")
    assert prog.moves[0].end["X"] == pytest.approx(25.4)
    assert any("inches" in w for w in prog.warnings)


def test_z_axis_word_is_an_error_on_an_xyuv_machine():
    prog = gc.Program.parse("G1 F300\nG1 X10 Z5\n")
    assert any("axis word Z" in e for e in prog.errors)


def test_unsupported_codes_are_reported():
    prog = gc.Program.parse("G64 P0.1\nM6 T1\nG1 F300\nG1 X1\n")
    assert any("G64" in e for e in prog.errors)
    assert any("M6" in e for e in prog.errors)


def test_g1_without_feed_is_an_error():
    prog = gc.Program.parse("G90\nG1 X10\n")
    assert any("without a feed" in e for e in prog.errors)


def test_rapid_does_not_need_a_feed():
    prog = gc.Program.parse("G90\nG0 X10\n")
    assert not prog.errors


def test_program_without_motion_warns_but_is_not_an_error():
    prog = gc.Program.parse("; nothing here\n")
    assert not prog.errors
    assert "no motion" in " ".join(prog.warnings)


def test_move_length_is_the_four_axis_norm():
    prog = gc.Program.parse("G1 F300\nG1 X3 Y4 U3 V4\n")
    move = prog.moves[0]
    assert move.length() == pytest.approx(math.sqrt(3**2 + 4**2 + 3**2 + 4**2))
    assert move.tower_length() == pytest.approx(5.0)


def test_tower_feed_ratio_flags_the_vector_feed_effect():
    both = gc.Program.parse("G1 F300\nG1 X10 U10\n")
    assert both.max_tower_feed_ratio() == pytest.approx(1 / math.sqrt(2))
    one = gc.Program.parse("G1 F300\nG1 X10\n")
    assert one.max_tower_feed_ratio() == pytest.approx(1.0)


def test_extents_include_the_origin():
    prog = gc.Program.parse("G1 F300\nG1 X10 Y-5 U0 V0\n")
    assert prog.extents()["X"] == (0.0, 10.0)
    assert prog.extents()["Y"] == (-5.0, 0.0)


def test_duration_matches_distance_over_feed():
    prog = gc.Program.parse("G1 F600\nG1 X10\n")  # 10 mm at 600 mm/min = 1 s
    assert prog.duration_s() == pytest.approx(1.0)


@pytest.mark.parametrize("text", [
    gc.gen_square(50, 300),
    gc.gen_taper(60, 30, 40, 300),
    gc.gen_axis_bounce("V", 25, 300),
])
def test_generated_programs_are_valid(text):
    prog = gc.Program.parse(text)
    assert not prog.errors, prog.errors


def test_generated_square_moves_both_towers_identically():
    prog = gc.Program.parse(gc.gen_square(50, 300))
    for m in prog.moves:
        assert m.end["X"] == m.end["U"]
        assert m.end["Y"] == m.end["V"]


def test_generated_taper_moves_the_towers_differently():
    prog = gc.Program.parse(gc.gen_taper(60, 30, 40, 300))
    assert any(m.end["X"] != m.end["U"] for m in prog.moves)


def test_generated_taper_extents():
    prog = gc.Program.parse(gc.gen_taper(60, 30, 40, 300))
    ext = prog.extents()
    assert ext["X"] == (0.0, 60.0)
    assert ext["U"] == (0.0, 30.0)


def test_gen_axis_bounce_rejects_a_bad_axis():
    with pytest.raises(ValueError):
        gc.gen_axis_bounce("Z")


def test_all_axes_are_the_foam_cutter_letters():
    assert AXES == ("X", "Y", "U", "V")
