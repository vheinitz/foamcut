import json

import pytest

from foamcut import AXES
from foamcut.grbl import Grbl
from foamcut.homing import offset_from_current, reference
from foamcut.machine import Homing, Machine

from fake_grbl import FakeGrblLink


def homed_machine():
    m = Machine()
    m.homing.enabled = True
    m.homing.length_mm = {"X": 160.0, "Y": 105.0, "U": 160.0, "V": 105.0}
    m.homing.offset_mm = {"X": 0.0, "Y": 0.0, "U": 0.5, "V": 1.5}
    m.homing.pulloff = 3.0
    return m


# --------------------------------------------------------------- model ----
def test_homing_settings_when_enabled():
    s = homed_machine().grbl_settings()
    assert s[22] == 1 and s[20] == 1 and s[23] == 15 and s[27] == 3.0 and s[5] == 0
    assert s[130] == 160.0 and s[133] == 105.0


def test_homing_settings_when_disabled_force_homing_and_soft_limits_off():
    s = Machine().grbl_settings()
    assert s[22] == 0 and s[20] == 0
    assert 23 not in s


def test_usable_travel_subtracts_pulloff_and_offset():
    m = homed_machine()
    assert m.homing.usable_travel("V") == pytest.approx(105 - 3 - 1.5)
    m.apply_homing_travel()
    assert m.travel_mm["V"] == pytest.approx(100.5)
    assert m.travel_mm["X"] == pytest.approx(157.0)


def test_homing_round_trips_through_json(tmp_path):
    m = homed_machine()
    m.homing.invert_switch = True
    m.homing.home_mpos = {a: -1.0 for a in AXES}
    p = m.save(tmp_path / "m.json")
    back = Machine.load(p)
    assert back.homing == m.homing
    assert back.travel_mm["V"] == pytest.approx(100.5)
    assert json.loads(p.read_text())["homing"]["enabled"] is True


# ------------------------------------------------------------ reference ---
def test_reference_sets_the_work_origin_offset_from_home():
    m = homed_machine()
    link = FakeGrblLink(settings=m.grbl_settings())
    g = Grbl(link)
    g.connect()
    mpos = reference(g, m.homing)
    assert link.homed
    # grbl convention in the fake: -travel + pulloff at the switch end
    assert mpos["X"] == pytest.approx(-157.0)
    assert mpos["V"] == pytest.approx(-102.0)
    # work origin = home + offset, so work position is now -offset
    wpos = link.wpos()
    assert wpos["X"] == pytest.approx(0.0)
    assert wpos["V"] == pytest.approx(-1.5)
    assert m.homing.home_mpos == mpos
    assert any(s.startswith("G10 L2 P1 ") for s in link.sent) and "G54" in link.sent


def test_reference_fails_when_homing_is_off_on_the_board():
    link = FakeGrblLink(settings={22: 0.0})
    g = Grbl(link)
    g.connect()
    from foamcut.grbl import GrblError
    with pytest.raises(GrblError):
        reference(g, Homing())


def test_offset_from_current_position():
    m = homed_machine()
    link = FakeGrblLink(settings=m.grbl_settings())
    g = Grbl(link)
    g.connect()
    reference(g, m.homing)
    g.jog("V", 2.25, 100)                       # level the wire by eye
    assert offset_from_current(g, m.homing, "V") == pytest.approx(2.25)


def test_offset_from_current_needs_a_home_first():
    g = Grbl(FakeGrblLink())
    g.connect()
    with pytest.raises(RuntimeError):
        offset_from_current(g, Homing(), "X")


def test_cli_homing_set_and_show(tmp_path, capsys):
    from foamcut.cli import main
    mp = tmp_path / "machine.json"
    Machine().save(mp)
    rc = main(["--machine", str(mp), "homing", "set", "--enable", "--nc", "--pulloff", "2",
               "--offset", "V=1.5", "U=0.5", "--length", "X=160", "Y=105", "U=160", "V=105"])
    assert rc == 0
    m = Machine.load(mp)
    assert m.homing.enabled and m.homing.invert_switch and m.homing.pulloff == 2.0
    assert m.homing.offset_mm["V"] == 1.5 and m.homing.length_mm["Y"] == 105.0
    assert m.travel_mm["V"] == pytest.approx(105 - 2 - 1.5)
    capsys.readouterr()
    assert main(["--machine", str(mp), "homing", "show"]) == 0
    out = capsys.readouterr().out
    assert "AN" in out and "Oeffner" in out and "160.0" in out


def test_cli_homing_set_rejects_a_bad_axis(tmp_path, capsys):
    from foamcut.cli import main
    mp = tmp_path / "machine.json"
    assert main(["--machine", str(mp), "homing", "set", "--offset", "Z=1"]) == 2


def test_reference_backs_off_a_pressed_switch_first():
    from foamcut.homing import clear_switches
    m = homed_machine()
    link = FakeGrblLink(settings=m.grbl_settings())
    link.pressed = "U"; link.release_on_jog = True
    g = Grbl(link); g.connect()
    assert clear_switches(g) == ["U"]
    jogs = [s for s in link.sent if s.startswith("$J=")]
    assert jogs == ["$J=G91 U5 F100"] and "$X" in link.sent
    assert link.settings[20] == 1.0                     # soft limits back on afterwards
    link.pressed = "Y"; link.release_on_jog = False
    with pytest.raises(RuntimeError, match="Endschalter Y"):
        clear_switches(g)


def test_reference_runs_home_after_clearing():
    m = homed_machine()
    link = FakeGrblLink(settings=m.grbl_settings())
    link.pressed = "X"; link.release_on_jog = True
    g = Grbl(link); g.connect()
    reference(g, m.homing)
    assert link.homed and link.sent.index("$J=G91 X5 F100") < link.sent.index("$H")


def test_grbl_settings_keep_dollar5_off_and_homing_before_soft_limits():
    m = homed_machine()
    s = m.homing.grbl_settings()
    assert s[5] == 0.0 and list(s)[0] == 22 and s[20] == 1.0
