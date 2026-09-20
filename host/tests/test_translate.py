from pathlib import Path

import pytest

from foamcut import gcode as gc
from foamcut.cli import main

WING = Path(__file__).resolve().parents[2] / "gcode" / "wing_program.nc"

HOTWIRE_SNIPPET = """G21
G90
G64 ; path control
X0.00 Y0.00 A0.00 Z0.00
M3 S1 ; relay on
G93
G1 X10.000 Y1.000 A12.000 Z1.500 F230.0
G1 X20.000 Y2.000 A24.000 Z3.000 F305.0 ; Iend=X
G94
G1 X0.00 Y0.00 A0.00 Z0.00
M5
M2
"""


def test_detects_hotwireairfoil_letters():
    assert gc.detect_axis_preset(HOTWIRE_SNIPPET) == "XYAZ"
    assert gc.detect_axis_preset("G1 X1 Y1 U1 V1 F100\n") == "XYUV"


def test_translate_maps_a_and_z_to_u_and_v():
    text, notes = gc.translate(HOTWIRE_SNIPPET)
    assert "G1 X10.000 Y1.000 U12.000 V1.500 F230.0" in text
    assert "A" not in [w[0] for l in text.splitlines() for w in gc.parse_words(l)]
    assert any("A->U" in n for n in notes)


def test_translate_keeps_comments_untouched():
    text, _ = gc.translate(HOTWIRE_SNIPPET)
    assert "; Iend=X" in text          # the 'X' inside the comment survives


def test_translate_drops_g64_with_a_note():
    text, notes = gc.translate(HOTWIRE_SNIPPET)
    assert "\nG64" not in text
    assert "; foamcut: entfernt (G64)" in text
    assert any("G64" in n for n in notes)


def test_translate_adds_feed_after_g94():
    text, notes = gc.translate(HOTWIRE_SNIPPET, default_feed=300)
    assert "G1 X0.00 Y0.00 U0.00 V0.00 F300" in text
    assert any("F300" in n for n in notes)
    # ... and the result parses without a feed error
    assert not gc.Program.parse(text).errors


def test_translate_without_default_feed_leaves_the_error_visible():
    text, _ = gc.translate(HOTWIRE_SNIPPET)
    assert any("without a feed" in e for e in gc.Program.parse(text).errors)


def test_translate_replaces_relay_style_wire_power():
    text, notes = gc.translate(HOTWIRE_SNIPPET, wire_power=180)
    assert "M3 S180 ; relay on" in text
    assert any("S180" in n for n in notes)


def test_translate_warns_when_wire_power_is_unset():
    _, notes = gc.translate(HOTWIRE_SNIPPET)
    assert any("kalt" in n for n in notes)


def test_translate_leaves_real_s_values_alone():
    text, _ = gc.translate("M3 S200\n", wire_power=50)
    assert "M3 S200" in text


def test_translate_is_a_no_op_for_our_own_files():
    own = gc.gen_taper()
    text, notes = gc.translate(own)
    assert text == own and notes == []


def test_g93_parsing_and_duration():
    prog = gc.Program.parse("G93\nG1 X10 F60\nG1 X20 F120\n")   # 1 s + 0.5 s
    assert not prog.errors
    assert prog.duration_s() == pytest.approx(1.5)
    assert all(m.inverse_time for m in prog.moves)


def test_g93_requires_f_on_every_line():
    prog = gc.Program.parse("G93\nG1 X10 F60\nG1 X20\n")
    assert any("G93" in e for e in prog.errors)


def test_g94_after_g93_forgets_the_feed():
    prog = gc.Program.parse("G93\nG1 X10 F60\nG94\nG1 X0\n")
    assert any("line 4" in e and "feed" in e for e in prog.errors)


def test_bare_axis_words_run_as_g0_like_grbl():
    prog = gc.Program.parse("G21\nX10 Y10\n")
    assert not prog.errors
    assert prog.moves[0].rapid


def test_real_wing_file_converts_clean(tmp_path, capsys):
    out = tmp_path / "wing_xyuv.nc"
    rc = main(["convert", str(WING), str(out), "--wire", "180"])
    text = capsys.readouterr().out
    assert rc == 0, text
    assert "U131.162" in out.read_text()
    assert "M3 S180" in out.read_text()
    assert "ERROR" not in text


def test_check_on_the_raw_wing_file_translates_automatically(capsys):
    assert main(["check", str(WING)]) == 0
    out = capsys.readouterr().out
    assert "Achsformat XYAZ" in out
    assert "kalt" in out            # S1 warning, because no --wire on check
