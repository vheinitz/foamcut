import pytest

from foamcut.grbl import Grbl, GrblAlarm, GrblError, parse_status
from foamcut.link import FakeLink

BANNER = ["Grbl 1.2i ['$' for help]"]


def test_parse_status_full():
    st = parse_status("<Run|MPos:1.000,2.000,3.000,4.000|Bf:14,127|FS:300,128>")
    assert st["state"] == "Run"
    assert st["mpos"] == {"X": 1.0, "Y": 2.0, "U": 3.0, "V": 4.0}
    assert st["feed"] == 300.0
    assert st["spindle"] == 128.0
    assert st["planner_free"] == 14
    assert st["rx_free"] == 127


def test_parse_status_substate_is_stripped():
    assert parse_status("<Hold:0|MPos:0.000,0.000,0.000,0.000>")["state"] == "Hold"


def test_parse_status_rejects_junk():
    with pytest.raises(ValueError):
        parse_status("ok")


def test_connect_reads_the_banner():
    g = Grbl(FakeLink(banner=BANNER))
    g.connect()
    assert g.is_grbl()


def test_connect_soft_resets_a_silent_board():
    link = FakeLink(responder={}, banner=[])
    link._pending = []
    g = Grbl(link)
    # A soft reset makes the fake produce nothing, so connect must give up
    # rather than hang; the banner stays empty and is_grbl() is False.
    g.connect(timeout=0.2)
    assert not g.is_grbl()
    assert repr(b"\x18") in link.sent


def test_command_returns_lines_before_ok():
    link = FakeLink({"$$": ["$0=10", "$100=400.000", "ok"]}, banner=BANNER)
    g = Grbl(link)
    g.connect()
    assert g.command("$$") == ["$0=10", "$100=400.000"]


def test_command_raises_on_error_with_a_hint():
    link = FakeLink({"G1 X1": ["error:22"]}, banner=BANNER)
    g = Grbl(link)
    g.connect()
    with pytest.raises(GrblError) as e:
        g.command("G1 X1")
    assert e.value.code == 22
    assert "feed rate" in str(e.value)


def test_command_raises_on_alarm():
    link = FakeLink({"$H": ["ALARM:9"]}, banner=BANNER)
    g = Grbl(link)
    g.connect()
    with pytest.raises(GrblAlarm):
        g.command("$H")


def test_command_times_out_when_nothing_answers():
    link = FakeLink({"G1 X1": []}, banner=BANNER)
    g = Grbl(link)
    g.connect()
    with pytest.raises(TimeoutError):
        g.command("G1 X1", timeout=0.2)


def test_settings_are_parsed_into_numbers():
    link = FakeLink({"$$": ["$0=10", "$100=400.000", "$110=1500.000", "ok"]})
    assert Grbl(link).settings() == {0: 10.0, 100: 400.0, 110: 1500.0}


def test_apply_settings_skips_comments_and_blank_lines():
    text = (
        "# a comment\n"
        "\n"
        "$100=400.0   # steps per mm\n"
        "not a setting\n"
        "$110=1500.0\n"
    )
    link = FakeLink()
    applied = Grbl(link).apply_settings(text)
    assert applied == ["$100=400.0", "$110=1500.0"]
    assert link.sent == ["$100=400.0", "$110=1500.0"]


def test_hotwire_off_sends_m5_and_on_sends_m3():
    link = FakeLink()
    g = Grbl(link)
    g.hotwire(0)
    g.hotwire(200)
    assert link.sent == ["M5", "M3 S200"]


def test_zero_here_covers_all_four_axes():
    link = FakeLink()
    Grbl(link).zero_here()
    assert link.sent == ["G10 L20 P1 X0 Y0 U0 V0"]


def test_stream_skips_comments_and_counts_lines():
    link = FakeLink()
    g = Grbl(link)
    sent = g.stream(["; header", "", "G21", "G1 X1 F300 ; move", "M2"])
    assert sent == 3
    assert link.sent == ["G21", "G1 X1 F300", "M2"]


def test_wait_idle_returns_when_idle():
    link = FakeLink({"?": ["<Idle|MPos:0.000,0.000,0.000,0.000>"]})
    Grbl(link).wait_idle(timeout=1)


def test_wait_idle_raises_on_alarm():
    link = FakeLink({"?": ["<Alarm|MPos:0.000,0.000,0.000,0.000>"]})
    with pytest.raises(GrblAlarm):
        Grbl(link).wait_idle(timeout=1)


def test_find_port_passes_an_explicit_name_through():
    from foamcut.link import find_port
    assert find_port("/dev/ttyS9") == "/dev/ttyS9"


def test_find_port_picks_the_newest(monkeypatch):
    from foamcut import link as lk
    monkeypatch.setattr(lk, "list_ports", lambda: ["/dev/ttyUSB3", "/dev/ttyUSB0"])
    assert lk.find_port("auto") == "/dev/ttyUSB3"
    assert lk.find_port(None) == "/dev/ttyUSB3"


def test_find_port_error_mentions_power(monkeypatch):
    from foamcut import link as lk
    monkeypatch.setattr(lk, "list_ports", lambda: [])
    with pytest.raises(lk.LinkError, match="Strom"):
        lk.find_port("auto")


def test_serial_link_hands_the_boot_banner_to_connect():
    """Regression: SerialLink used to swallow the banner in __init__, so
    Hwtest.connect() saw nothing and declared the wrong firmware."""
    import foamcut.link as lk

    class Fake(lk.SerialLink):
        def __init__(self):
            self._lines = ["foamcut hwtest on GT2560 Rev.A / Rev.A+", "type ? for help"]
            self._buf = b""
            self._startup = self._read_pending()

        def _read_pending(self):
            out, self._lines = self._lines, []
            return out

    from foamcut.hwtest import Hwtest
    hw = Hwtest(Fake())
    assert hw.connect()
    assert hw.is_hwtest()


def test_tcp_link_talks_lines_over_a_socket():
    """tcp://host:port (ESP3D bridge) behaves like the serial link."""
    import socket, threading
    from foamcut.link import LinkError, TcpLink, open_link
    srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(1)
    port = srv.getsockname()[1]
    got = []

    def serve():
        conn, _ = srv.accept()
        data = b""
        while b"\n" not in data:
            data += conn.recv(64)
        got.append(data)
        conn.sendall(b"ok\r\n<Idle|MPos:0,0,0,0>\n")
        conn.close()
    t = threading.Thread(target=serve, daemon=True); t.start()
    link = open_link(f"tcp://127.0.0.1:{port}")
    assert isinstance(link, TcpLink)
    link.write_line("$$")
    assert link.read_line(timeout=2.0) == "ok"
    assert link.read_line(timeout=2.0).startswith("<Idle")
    t.join(2.0)
    assert got == [b"$$\n"]
    with pytest.raises(LinkError):
        link.read_line(timeout=1.0)           # server closed
    link.close()
    with pytest.raises(LinkError, match="cannot connect"):
        TcpLink("tcp://127.0.0.1:1", connect_timeout=0.5)
