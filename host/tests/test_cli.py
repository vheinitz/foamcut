from pathlib import Path

import pytest

from foamcut.cli import main


def test_gen_and_check_round_trip(tmp_path, capsys):
    out = tmp_path / "taper.nc"
    assert main(["gen", "taper", "--size", "60", "-o", str(out)]) == 0
    assert main(["check", str(out)]) == 0
    report = capsys.readouterr().out
    assert "moves" in report
    assert "U:" in report


def test_check_reports_a_bad_file(tmp_path, capsys):
    bad = tmp_path / "bad.nc"
    bad.write_text("G64 P0.1\nG1 X10 Z5\n")
    assert main(["check", str(bad)]) == 1
    assert "ERROR" in capsys.readouterr().out


def test_gen_writes_to_stdout_without_o(capsys):
    assert main(["gen", "square"]) == 0
    assert "G1 X50.000 Y0.000 U50.000 V0.000" in capsys.readouterr().out


def test_shipped_gcode_files_are_valid(capsys):
    gdir = Path(__file__).resolve().parents[2] / "gcode"
    files = sorted(gdir.glob("*.nc"))
    assert files, "no test G-code shipped"
    for f in files:
        assert main(["check", str(f)]) == 0, f"{f.name} failed validation"


def test_bounce_rejects_a_step_period_the_firmware_cannot_hold(capsys):
    # stepUs is a uint16_t in the firmware; 100000 would silently wrap to 34464.
    assert main(["bounce", "X", "--step-us", "100000"]) == 2
    assert "65535" in capsys.readouterr().err


def test_check_enforces_travel_from_machine_json(tmp_path, capsys):
    from foamcut.machine import Machine
    m = Machine()
    m.travel_mm = {"X": 40.0, "Y": 300.0, "U": 400.0, "V": 300.0}
    mpath = m.save(tmp_path / "machine.json")
    nc = tmp_path / "wide.nc"
    nc.write_text("G21\nG90\nG1 F300\nG1 X60 Y10 U10 V10\n")
    assert main(["--machine", str(mpath), "check", str(nc)]) == 1
    out = capsys.readouterr().out
    assert "VERFAHRWEG" in out and "X:" in out and "40" in out


def test_check_without_travel_measured_does_not_block(tmp_path):
    from foamcut.machine import Machine
    mpath = Machine().save(tmp_path / "machine.json")   # travel all 0 = unmeasured
    nc = tmp_path / "ok.nc"
    nc.write_text("G21\nG90\nG1 F300\nG1 X60\n")
    assert main(["--machine", str(mpath), "check", str(nc)]) == 0


def test_machine_set_steps_per_mm_and_clamps_the_rate(tmp_path, capsys):
    from foamcut.machine import Machine
    mpath = tmp_path / "machine.json"
    Machine().save(mpath)
    assert main(["--machine", str(mpath), "machine", "set", "--steps", "Y=17408", "--steps", "V=17408"]) == 0
    m = Machine.load(mpath)
    assert m.steps_per_mm["Y"] == m.steps_per_mm["V"] == 17408.0
    assert m.max_rate["Y"] == pytest.approx(68.9, abs=0.1)          # 20 kHz budget
    out = capsys.readouterr().out
    assert "Y 17408" in out
    assert main(["--machine", str(mpath), "machine", "set", "--steps", "Q=1"]) == 2


def test_coarser_microstepping_gives_the_rate_back(tmp_path):
    # Going 1/32 -> 1/8 on Y/V is the whole point of the exercise: halve the
    # steps and the axis must be allowed to run faster again, otherwise the
    # wire still crawls through a spar slot and melts it wide.
    from foamcut.machine import Machine
    mpath = tmp_path / "machine.json"
    Machine().save(mpath)
    main(["--machine", str(mpath), "machine", "set", "--steps", "Y=17408", "--steps", "V=17408"])
    assert Machine.load(mpath).max_rate["Y"] == pytest.approx(68.9, abs=0.1)
    main(["--machine", str(mpath), "machine", "set", "--steps", "Y=4352", "--steps", "V=4352"])
    m = Machine.load(mpath)
    assert m.max_rate["Y"] == m.max_rate["V"] == pytest.approx(275.7, abs=0.1)
    assert m.slow_axes(250.0) == []


def test_a_hand_set_rate_is_not_raised_behind_your_back(tmp_path):
    from foamcut.machine import Machine
    mpath = tmp_path / "machine.json"
    m = Machine(); m.steps_per_mm["Y"] = 17408.0; m.max_rate["Y"] = 40.0   # chosen, not derived
    m.save(mpath)
    main(["--machine", str(mpath), "machine", "set", "--steps", "Y=4352"])
    assert Machine.load(mpath).max_rate["Y"] == 40.0
