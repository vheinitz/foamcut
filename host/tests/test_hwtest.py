import pytest

from foamcut import hwtest as hwt
from foamcut.link import FakeLink

BANNER = ["foamcut hwtest on GT2560 Rev.A / Rev.A+", "type ? for help"]


def test_parse_endstops():
    line = "endstops:  Xmin=0 Xmax=0  Ymin=1 Ymax=0  Umin=0 Umax=0"
    assert hwt.parse_endstops([line]) == {
        "Xmin": False, "Xmax": False, "Ymin": True,
        "Ymax": False, "Umin": False, "Umax": False,
    }


def test_parse_endstops_ignores_other_lines():
    assert hwt.parse_endstops(["drivers ENABLED", "stepped 3200"]) == {}


@pytest.mark.parametrize("lines,want", [
    (["stepped 3200"], 3200),
    (["! endstop on pin 22 triggered, stopping", "stepped 41"], 41),
    (["drivers ENABLED"], None),
    (["stepped back"], None),
])
def test_parse_stepped(lines, want):
    assert hwt.parse_stepped(lines) == want


def test_command_reads_until_ok():
    link = FakeLink({"map": ["axis slot  step", " X   X    25", "ok"]}, banner=BANNER)
    hw = hwt.Hwtest(link)
    hw.connect()
    assert hw.command("map") == ["axis slot  step", " X   X    25"]


def test_command_times_out():
    link = FakeLink({"map": []}, banner=BANNER)
    hw = hwt.Hwtest(link)
    hw.connect()
    with pytest.raises(hwt.HwtestError):
        hw.command("map", timeout=0.2)


def test_is_hwtest_recognises_the_banner():
    hw = hwt.Hwtest(FakeLink(banner=BANNER))
    hw.connect()
    assert hw.is_hwtest()


def test_grbl_banner_is_not_the_hwtest_firmware():
    hw = hwt.Hwtest(FakeLink(banner=["Grbl 1.2i ['$' for help]"]))
    hw.connect()
    assert not hw.is_hwtest()


def _run_link(endstops="endstops:  Xmin=0 Xmax=0  Ymin=0 Ymax=0  Umin=0 Umax=0"):
    responder = {"es": [endstops, "ok"], "map": ["axis slot  step", "ok"]}
    for axis in ("X", "Y", "U", "V"):
        responder[f"bounce {axis} 3200"] = ["stepped 3200", "stepped back 3200", "ok"]
    return FakeLink(responder, banner=BANNER)


def test_auto_run_on_a_healthy_machine_passes(capsys):
    assert hwt.run(_run_link(), auto=True) == 0
    out = capsys.readouterr().out
    assert "Alle" in out and "bestanden" in out
    assert "FEHLER" not in out


def test_auto_run_flags_a_closed_endstop(capsys):
    link = _run_link("endstops:  Xmin=1 Xmax=0  Ymin=0 Ymax=0  Umin=0 Umax=0")
    assert hwt.run(link, auto=True) == 1
    assert "Xmin" in capsys.readouterr().out


def test_auto_run_flags_a_short_move(capsys):
    link = _run_link()
    link.responder["bounce V 3200"] = ["! endstop on pin 38 triggered, stopping",
                                       "stepped 12", "ok"]
    assert hwt.run(link, auto=True) == 1
    assert "12/3200" in capsys.readouterr().out


def test_run_refuses_when_grbl_is_flashed(capsys):
    assert hwt.run(FakeLink(banner=["Grbl 1.2i ['$' for help]"]), auto=True) == 1
    assert "hwtest-flash" in capsys.readouterr().out


def test_run_releases_the_motors_at_the_end():
    link = _run_link()
    hwt.run(link, auto=True)
    assert link.sent[-1] == "en 0"


def test_bounce_moves_every_axis_and_releases_the_motors():
    link = _run_link()
    for axis in ("X", "Y", "U", "V"):
        link.responder[f"bounce {axis} 8000"] = ["stepped 8000", "stepped back 8000", "ok"]
    assert hwt.bounce(link, steps=8000) == 0
    assert "guard 1" in link.sent and "en 1" in link.sent
    assert link.sent[-1] == "en 0"
    for axis in ("X", "Y", "U", "V"):
        assert f"bounce {axis} 8000" in link.sent


def test_bounce_can_disable_the_endstop_guard():
    link = _run_link()
    link.responder["bounce X 100"] = ["stepped 100", "ok"]
    hwt.bounce(link, axes=("X",), steps=100, guard=False)
    assert "guard 0" in link.sent


def test_bounce_reports_a_short_move(capsys):
    link = _run_link()
    link.responder["bounce X 8000"] = ["stepped 37", "ok"]
    assert hwt.bounce(link, axes=("X",), steps=8000) == 1
    assert "37/8000" in capsys.readouterr().out
