import time

import pytest

from foamcut import AXES
from foamcut.jog import JogModel
from foamcut.worker import GrblWorker
from foamcut.machine import Machine


def model(**kw):
    m = Machine()
    m.max_rate = {"X": 750.0, "Y": 137.9, "U": 750.0, "V": 137.9}
    return JogModel(m, **kw)


def test_jog_uses_horizontal_feed_for_x_and_u():
    jm = model(step=25.0, feed_h=600.0, feed_v=100.0)
    assert jm.jog({"X": +1}) == "$J=G91 G21 X25.000 F600"
    assert jm.jog({"U": -1}) == "$J=G91 G21 U-25.000 F600"


def test_jog_uses_vertical_feed_for_y_and_v():
    jm = model(step=5.0, feed_h=600.0, feed_v=100.0)
    assert jm.jog({"Y": +1}) == "$J=G91 G21 Y5.000 F100"
    assert jm.jog({"V": -1}) == "$J=G91 G21 V-5.000 F100"


def test_both_towers_move_in_one_command():
    jm = model(step=1.0, feed_h=600.0, feed_v=100.0)
    assert jm.jog({"X": +1, "U": +1}) == "$J=G91 G21 X1.000 U1.000 F600"
    assert jm.jog({"Y": -1, "V": -1}) == "$J=G91 G21 Y-1.000 V-1.000 F100"


def test_mixed_axes_take_the_faster_feed_and_let_grbl_clamp():
    # grbl limits each axis to its own $11x; sending the lower feed would
    # make the horizontal part crawl for no reason.
    jm = model(step=1.0, feed_h=600.0, feed_v=100.0)
    assert jm.jog({"X": 1, "Y": 1}).endswith("F600")


def test_feeds_are_clamped_to_the_machine_maximum():
    jm = model(feed_h=5000.0, feed_v=5000.0)
    assert jm.feed_h == 750.0
    assert jm.feed_v == 137.9


def test_reference_commands():
    jm = model()
    assert jm.set_reference() == "G10 L20 P1 X0 Y0 U0 V0"
    assert jm.goto_reference().startswith("$J=G90 G21 X0 Y0 U0 V0 F")


def test_record_travel_takes_the_current_work_position():
    jm = model()
    jm.wpos["U"] = 312.4567
    assert jm.record_travel("U") == 312.457
    assert jm.machine.travel_mm["U"] == 312.457


def test_hotwire_commands():
    jm = model()
    assert jm.hotwire(0) == "M5"
    assert jm.hotwire(128) == "M3 S128"


def test_worker_reports_a_missing_port_and_closes():
    w = GrblWorker("/dev/does-not-exist", poll=0.05)
    w.start()
    w.join(timeout=5)
    kinds = []
    while not w.events.empty():
        kinds.append(w.events.get_nowait()[0])
    assert kinds[0] == "error"
    assert kinds[-1] == "closed"


from fake_grbl import FakeGrblLink


def _collect(worker, timeout=5.0):
    worker.join(timeout=timeout)
    out = []
    while not worker.events.empty():
        out.append(worker.events.get_nowait())
    return out


def test_worker_streams_a_program_and_reports_progress():
    link = FakeGrblLink()
    w = GrblWorker("fake", poll=0.01, link_factory=lambda: link)
    w.start()
    w.submit("stream", ["G21", "; comment", "G1 X10 F300", "M2"])
    time.sleep(0.5)
    w.stop()
    ev = _collect(w)
    progress = [p for k, p in ev if k == "progress"]
    assert [p[2] for p in progress] == ["G21", "G1 X10 F300", "M2"]
    assert progress[-1][:2] == (4, 4)
    assert ("stream_done", True) in ev
    assert "G1 X10 F300" in link.sent and "; comment" not in link.sent


def test_worker_pushes_max_rates_from_machine_on_connect():
    link = FakeGrblLink()
    w = GrblWorker("fake", poll=0.01, settings={110: 1125.0, 111: 205.0},
                   link_factory=lambda: link)
    w.start()
    time.sleep(0.3)
    w.stop()
    _collect(w)
    assert link.settings[110] == 1125.0 and link.settings[111] == 205.0


class _StuckLink(FakeGrblLink):
    """Never acknowledges the second line - like a full planner mid-move."""
    def write_line(self, text):
        if text.strip() == "G1 X10 F300":
            self.sent.append(text.strip())
            return
        super().write_line(text)


def test_worker_abort_resets_and_reports_failure():
    link = _StuckLink()
    w = GrblWorker("fake", poll=0.01, link_factory=lambda: link)
    w.start()
    w.submit("stream", ["G21", "G1 X10 F300", "M2"])
    time.sleep(0.3)
    w.abort_stream()
    time.sleep(0.8)
    w.stop()
    ev = _collect(w)
    assert ("stream_done", False) in ev
    assert "M2" not in link.sent
    assert repr(b"!") in link.sent and repr(b"\x18") in link.sent


def test_worker_status_keeps_flowing_while_a_line_is_pending():
    link = _StuckLink()
    w = GrblWorker("fake", poll=0.02, link_factory=lambda: link)
    w.start()
    w.submit("stream", ["G21", "G1 X10 F300"])
    time.sleep(0.4)
    w.abort_stream()
    time.sleep(0.8)
    w.stop()
    ev = _collect(w)
    assert sum(1 for k, _ in ev if k == "status") >= 5


def test_standard_settings_merge_file_and_machine(tmp_path):
    from foamcut.machine import Machine, standard_settings
    f = tmp_path / "s.txt"
    f.write_text("$20=0   # soft limits\n$22=0\n$100=400.0\n# comment\n$1=25\n")
    m = Machine()
    m.steps_per_mm["X"] = 1600.0
    s = standard_settings(m, f)
    assert s[20] == 0 and s[22] == 0 and s[1] == 25
    assert s[100] == 1600.0             # machine.json wins over the file
    assert s[110] == m.max_rate["X"]


def test_worker_unlocks_an_alarm_on_connect():
    link = FakeGrblLink()
    link._pending.append("[MSG:'$H'|'$X' to unlock]")
    w = GrblWorker("fake", poll=0.01, link_factory=lambda: link)
    w.start()
    time.sleep(0.3)
    w.stop()
    _collect(w)
    assert "$X" in link.sent


def test_worker_restores_factory_reset_settings():
    link = FakeGrblLink(settings={20: 1.0, 22: 1.0, 100: 400.0})
    w = GrblWorker("fake", poll=0.01, settings={20: 0.0, 22: 0.0, 100: 1600.0},
                   link_factory=lambda: link)
    w.start()
    time.sleep(0.3)
    w.stop()
    ev = _collect(w)
    assert link.settings[20] == 0.0 and link.settings[22] == 0.0 and link.settings[100] == 1600.0
    assert any(k == "error" and "wichen ab" in p for k, p in ev)


class _DyingLink(FakeGrblLink):
    """Answers status twice, then behaves like a hung MCU (silence)."""
    def __init__(self):
        super().__init__()
        self.polls = 0

    def write_raw(self, data):
        if data == b"?":
            self.polls += 1
            if self.polls > 2:
                return              # no report: the MCU is gone
        super().write_raw(data)


def test_worker_reconnects_after_the_board_stops_answering():
    links = []

    def factory():
        link = _DyingLink() if not links else FakeGrblLink()
        links.append(link)
        return link

    w = GrblWorker("fake", poll=0.02, hang_polls=3, status_timeout=0.05,
                   retry_delay=0.1, link_factory=factory)
    w.start()
    time.sleep(1.5)
    w.stop()
    ev = _collect(w)
    assert len(links) >= 2, "no reconnect happened"
    kinds = [k for k, _ in ev]
    assert "reset" in kinds
    assert any(k == "error" and "haengt" in p for k, p in ev)


def test_worker_gives_up_on_a_missing_port_when_reconnect_is_off():
    w = GrblWorker("/dev/does-not-exist", poll=0.05, reconnect=False)
    w.start()
    w.join(timeout=5)
    assert not w.is_alive()


def test_worker_does_not_unlock_when_homing_is_configured():
    from foamcut.machine import Homing
    link = FakeGrblLink(settings={22: 1.0})
    link._pending.append("[MSG:'$H'|'$X' to unlock]")
    h = Homing(); h.enabled = True
    w = GrblWorker("fake", poll=0.01, link_factory=lambda: link, homing=h)
    w.start()
    time.sleep(0.3)
    w.stop()
    ev = _collect(w)
    assert "$X" not in link.sent
    assert ("needs_homing", None) in ev


def test_worker_home_command_runs_reference_and_reports():
    from foamcut.machine import Homing
    h = Homing(); h.enabled = True
    h.length_mm = {"X": 160.0, "Y": 105.0, "U": 160.0, "V": 105.0}
    h.offset_mm["V"] = 1.5
    link = FakeGrblLink(settings=h.grbl_settings())
    w = GrblWorker("fake", poll=0.01, link_factory=lambda: link, homing=h)
    w.start()
    w.submit("home")
    time.sleep(0.5)
    w.stop()
    ev = _collect(w)
    homed = [p for k, p in ev if k == "homed"]
    assert homed and homed[0]["V"] == pytest.approx(-102.0)
    assert link.wpos()["V"] == pytest.approx(-1.5)
    assert h.home_mpos == homed[0]


def test_worker_probe_pos_answers_synchronously():
    import queue as q
    link = FakeGrblLink()
    link.mpos["X"] = 12.5
    w = GrblWorker("fake", poll=0.01, link_factory=lambda: link)
    w.start()
    got = q.Queue()
    w.submit("probe_pos", got)
    assert got.get(timeout=3)["X"] == 12.5
    w.stop()
    _collect(w)


def test_worker_probe_status_reports_pressed_switches():
    import queue as q
    link = FakeGrblLink()
    link.pressed = "XV"
    w = GrblWorker("fake", poll=0.01, link_factory=lambda: link)
    w.start()
    got = q.Queue()
    w.submit("probe_status", got)
    st = got.get(timeout=3)
    assert st["pn"] == "XV"
    w.stop()
    _collect(w)


import os


@pytest.mark.skipif(not os.environ.get("DISPLAY"), reason="needs an X display")
def test_main_window_builds_and_every_dialog_opens(tmp_path):
    """Regression: a callback defined after the button that used it crashed
    the GUI at startup; only constructing the real window catches that."""
    import tkinter as tk
    from foamcut.gui import build_gui
    from foamcut.machine import Machine
    mp = tmp_path / "machine.json"
    Machine().save(mp)
    root = build_gui(port="/dev/does-not-exist", machine_path=mp, autoconnect=False)
    try:
        root.update()
        api = root.foamcut
        api["load_program"]("G21\nG90\nG1 F300\nG1 X10 U10\nM2\n", "t.nc")
        root.update()
        assert api["program"]["lines"]
        for opener in ("open_sim", "open_wing", "open_homing"):
            win = None
            api[opener]()
            root.update()
        assert any(isinstance(w, tk.Toplevel) for w in root.winfo_children())
    finally:
        root.destroy()
