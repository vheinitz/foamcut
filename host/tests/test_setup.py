import json

import pytest

from foamcut import AXES
from foamcut.grbl import Grbl
from foamcut.machine import Machine
from foamcut.setup import Abort, ScriptedConsole, Wizard

from fake_grbl import FakeGrblLink


def make(link, answers):
    g = Grbl(link)
    g.connect()
    return Wizard(g, Machine(), ScriptedConsole(answers))


# ------------------------------------------------------------- machine ----
def test_machine_round_trip(tmp_path):
    m = Machine()
    m.steps_per_mm["U"] = 2560.0
    m.invert_dir["Y"] = True
    m.travel_mm = {"X": 400, "Y": 300, "U": 400, "V": 300}
    m.clamp_rates()                       # load() clamps too; compare like with like
    path = m.save(tmp_path / "m.json")
    back = Machine.load(path)
    assert back == m
    assert json.loads(path.read_text())["steps_per_mm"]["U"] == 2560.0


def test_direction_mask_bits():
    m = Machine()
    m.invert_dir["Y"] = True
    m.invert_dir["V"] = True
    assert m.direction_mask() == 0b1010


def test_check_extents_flags_overrun_and_unmeasured():
    m = Machine()
    m.travel_mm = {"X": 100, "Y": 100, "U": 100, "V": 0}
    ext = {"X": (0, 120), "Y": (-5, 50), "U": (0, 50), "V": (0, 10)}
    problems = m.check_extents(ext)
    assert any(p.startswith("X:") and "120" in p for p in problems)
    assert any(p.startswith("Y:") and "unter" in p for p in problems)
    assert any(p.startswith("V:") and "nicht vermessen" in p for p in problems)
    assert not any(p.startswith("U:") for p in problems)


# -------------------------------------------------------------- phases ----
def test_mapping_passes_when_slots_are_canonical():
    link = FakeGrblLink()
    w = make(link, [0, 1, 2, 3])          # each axis moved the expected thing
    assert w.phase_mapping() is True
    assert link.wpos() == {a: 0.0 for a in AXES}   # jogged back


def test_mapping_moves_visibly_and_ends_where_it_started():
    link = FakeGrblLink()
    w = make(link, [0, 1, 2, 3])
    w.jog_mm = 30.0
    assert w.phase_mapping() is True
    jogs = [s for s in link.sent if s.startswith("$J=")]
    assert "$J=G91 G21 X30.000 F750" in jogs and "$J=G91 G21 X-30.000 F750" in jogs
    assert link.wpos() == {a: 0.0 for a in AXES}


def test_mapping_repeat_option_drives_the_axis_again():
    link = FakeGrblLink()
    # 5 = "nochmal fahren" for X, then the real answer
    w = make(link, [5, 0, 1, 2, 3])
    assert w.phase_mapping() is True
    assert sum(1 for s in link.sent if s == "$J=G91 G21 X20.000 F750") == 2
    assert link.wpos() == {a: 0.0 for a in AXES}


def test_mapping_reports_the_swap_when_wrong():
    link = FakeGrblLink()
    # Y slot drives the right tower horizontal, Z slot the left vertical
    w = make(link, [0, 2, 1, 3])
    assert w.phase_mapping() is False
    text = "\n".join(w.con.log)
    assert "Steckplatz Y " in text and "rechter Turm, waagerecht" in text
    assert "umstecken" in text


def test_scale_corrects_steps_per_mm_from_the_measurement():
    link = FakeGrblLink()
    # X: commanded 20, measured 10 -> doubles; decline the check run.
    # Y, U, V: exact, no question asked.
    w = make(link, [10.0, False, 20.0, 20.0, 20.0])
    w.phase_scale(distance=20.0)
    assert w.machine.steps_per_mm["X"] == 800.0
    assert link.settings[100] == 800.0
    assert link.settings[101] == 400.0
    assert link.wpos() == {a: 0.0 for a in AXES}


def test_scale_check_run_after_a_correction():
    link = FakeGrblLink()
    # X: 20 -> measured 5 (=> 1600), yes check run, now measured 20 -> keep.
    w = make(link, [5.0, True, 20.0, 20.0, 20.0, 20.0])
    w.phase_scale(distance=20.0)
    assert w.machine.steps_per_mm["X"] == 1600.0
    assert sum(1 for s in link.sent if s == "$J=G91 G21 X20.000 F750") == 2
    assert link.wpos() == {a: 0.0 for a in AXES}


def test_scale_zero_means_drive_again():
    link = FakeGrblLink()
    w = make(link, [0, 20.0, 20.0, 20.0, 20.0])
    w.phase_scale(distance=20.0)
    assert sum(1 for s in link.sent if s == "$J=G91 G21 X20.000 F750") == 2
    assert link.wpos() == {a: 0.0 for a in AXES}


def test_direction_flips_the_bit_and_returns_home():
    link = FakeGrblLink(direction={"X": +1, "Y": -1, "U": +1, "V": -1})
    # Y and V are wrong (1); after the flip the check run must be right (0).
    w = make(link, [0, 1, 0, 0, 1, 0])
    w.phase_direction(distance=10.0)
    assert int(link.settings[3]) == 0b1010
    assert w.machine.invert_dir == {"X": False, "Y": True, "U": False, "V": True}
    for a in AXES:
        assert abs(link.wpos()[a]) < 1e-9, f"{a} did not return to start"


def test_direction_repeat_option():
    link = FakeGrblLink()
    w = make(link, [2, 0, 0, 0, 0])
    w.phase_direction(distance=10.0)
    assert sum(1 for s in link.sent if s == "$J=G91 G21 X10.000 F750") == 2
    assert int(link.settings[3]) == 0
    assert link.wpos() == {a: 0.0 for a in AXES}


def test_reference_sets_work_zero_where_the_pad_stopped():
    link = FakeGrblLink()
    # d = X+1mm, "3" = 10 mm step, w = Y+10, Enter
    w = make(link, ["d", "3", "w", "\r"])
    w.phase_reference()
    assert link.mpos["X"] == 1.0 and link.mpos["Y"] == 10.0
    assert link.wpos() == {a: 0.0 for a in AXES}
    assert w.origin == link.mpos


def test_travel_records_the_far_end_and_returns():
    link = FakeGrblLink()
    w = make(link, ["\r"])                # reference at the current spot
    w.phase_reference()
    # X: step 50 twice, Enter; Y: step 10, Enter; U: 50; V: 1 mm x3
    w.con.answers += ["4", "d", "d", "\r",
                      "3", "w", "\r",
                      "4", "l", "\r",
                      "2", "i", "i", "i", "\r"]
    w.phase_travel()
    assert w.machine.travel_mm == {"X": 100.0, "Y": 10.0, "U": 50.0, "V": 3.0}
    assert link.settings[130] == 100.0 and link.settings[133] == 3.0
    assert link.wpos() == {a: 0.0 for a in AXES}


def test_travel_ignores_a_key_for_another_axis():
    link = FakeGrblLink()
    w = make(link, ["\r"])
    w.phase_reference()
    w.con.answers += ["w", "d", "\r", "\r", "\r", "\r"]   # 'w' is Y, ignored on X
    w.phase_travel()
    assert w.machine.travel_mm["X"] == 1.0
    assert link.mpos["Y"] == 0.0


def test_jogpad_q_aborts():
    link = FakeGrblLink()
    w = make(link, ["q"])
    with pytest.raises(Abort):
        w.jogpad("x")


def test_full_run_saves_a_consistent_machine(tmp_path):
    link = FakeGrblLink()
    answers = [0, 1, 2, 3]                       # mapping
    answers += [20.0, 20.0, 20.0, 20.0]          # scale: exact, no check run asked
    answers += [0, 0, 0, 0]                      # direction: all right
    answers += ["\r"]                            # reference here
    answers += ["4", "d", "\r", "4", "w", "\r", "4", "l", "\r", "4", "i", "\r"]
    w = make(link, answers)
    assert w.run() == 0
    assert w.machine.travel_mm == {a: 50.0 for a in AXES}
    path = w.machine.save(tmp_path / "machine.json")
    assert Machine.load(path).has_travel()


def test_run_stops_after_a_failed_mapping():
    link = FakeGrblLink()
    w = make(link, [1, 0, 2, 3])
    assert w.run() == 1
    assert not any(s.startswith("$100=") for s in link.sent)


def test_every_move_is_announced_before_it_happens():
    """The operator must get a chance to look before an axis moves."""
    link = FakeGrblLink()
    w = make(link, [0, 1, 2, 3, 20.0, 20.0, 20.0, 20.0, 0, 0, 0, 0])
    w.phase_mapping()
    w.phase_scale()
    w.phase_direction()
    # every jog in the log is preceded by a '>>' announcement
    log = w.con.log
    announcements = [i for i, l in enumerate(log) if l.startswith(">>")]
    # mapping 4 + scale 8 (hin + zurueck) + direction 4
    assert len(announcements) == 16


def test_ready_q_aborts():
    from foamcut.setup import Console
    c = Console()
    c.ask = lambda prompt: "q"
    with pytest.raises(Abort):
        c.ready("x")


def test_max_rate_is_capped_by_the_step_budget(tmp_path):
    from foamcut.machine import MAX_STEP_HZ, Machine, rate_cap
    m = Machine()
    m.steps_per_mm = {"X": 1600.0, "Y": 8704.0, "U": 1600.0, "V": 8704.0}
    m.max_rate = {"X": 1125.0, "Y": 205.0, "U": 1125.0, "V": 205.0}   # the values that hung the MCU
    notes = m.clamp_rates()
    assert len(notes) == 4
    assert m.max_rate["X"] == rate_cap(1600.0) == pytest.approx(MAX_STEP_HZ / 1600 * 60, abs=0.1)
    # and load() applies the same clamp, so a hand-edited machine.json cannot bypass it
    p = m.save(tmp_path / "m.json")
    import json
    d = json.loads(p.read_text()); d["max_rate"]["X"] = 5000.0
    p.write_text(json.dumps(d))
    assert Machine.load(p).max_rate["X"] == rate_cap(1600.0)


def test_scale_phase_caps_the_max_rate_with_the_new_steps_per_mm():
    from foamcut.machine import rate_cap
    link = FakeGrblLink(settings={110: 750.0})
    # X: commanded 20, measured 12.5 -> 400 * 20/12.5 = 640 steps/mm; decline check run
    w = make(link, [12.5, False, 20.0, 20.0, 20.0])
    w.phase_scale(distance=20.0)
    assert link.settings[100] == 640.0
    assert link.settings[110] == rate_cap(640.0) == w.machine.max_rate["X"]


def test_scale_phase_can_be_limited_to_one_axis():
    link = FakeGrblLink()
    w = make(link, [25.0, False])            # only U is asked
    w.axes = ("U",)
    w.phase_scale(distance=50.0)
    assert link.settings[102] == 800.0        # 400 * 50 / 25
    assert link.settings[100] == 400.0        # X untouched
    assert not any(s.startswith("$J=G91 G21 X") for s in link.sent)
