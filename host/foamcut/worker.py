"""GrblWorker - owns the serial link in a thread; GUIs talk to it via queues.

Commands in via submit(kind, payload), events out via `events`:
  ('banner', [lines]) ('status', dict) ('offset', dict) ('sent', line)
  ('reply', [lines]) ('error', text) ('progress', (i, n, line))
  ('stream_done', ok) ('needs_homing', None) ('homed', mpos) ('reset', None)
  ('closed', None)
"""
from __future__ import annotations

import queue
import threading
import time

from . import AXES
from . import homing as hm
from .grbl import Grbl, GrblAlarm, GrblError, parse_status
from .link import LinkError, SerialLink
from .machine import Homing

try:
    from serial import SerialException as _SerialException
except ImportError:                                   # pragma: no cover
    class _SerialException(Exception):
        pass

_LINK_ERRORS = (LinkError, _SerialException, OSError)


# --------------------------------------------------------------- worker -----
class GrblWorker(threading.Thread):
    """Owns the serial link. Commands in via submit(), events out via `events`.

    Events: ('banner', [lines]) ('status', dict) ('offset', dict)
            ('sent', line) ('reply', [lines]) ('error', text) ('closed', None)
    """

    def __init__(self, port: str, baud: int = 115200, poll: float = 0.2,
                 settings: dict[int, float] | None = None, link_factory=None,
                 reconnect: bool = True, hang_polls: int = 3,
                 status_timeout: float = 1.0, retry_delay: float = 1.5,
                 homing: Homing | None = None):
        super().__init__(daemon=True)
        self.homing = homing or Homing()
        self.port, self.baud, self.poll = port, baud, poll
        self.reconnect = reconnect
        self.hang_polls = hang_polls
        self.status_timeout = status_timeout
        self.retry_delay = retry_delay
        self.settings = settings or {}          # pushed to grbl on connect
        self.link_factory = link_factory or (lambda: SerialLink(port, baud))
        self.cmds: queue.Queue = queue.Queue()
        self.events: queue.Queue = queue.Queue()
        self._halt = threading.Event()
        self._abort = threading.Event()

    def submit(self, kind: str, payload=None) -> None:
        self.cmds.put((kind, payload))

    def stop(self) -> None:
        self._halt.set()
        self._abort.set()

    def abort_stream(self) -> None:
        self._abort.set()

    def run(self) -> None:
        """Connect, serve commands, poll status; reconnect on any link trouble.

        A reconnect reopens the port, which toggles DTR and resets the board.
        That is deliberate: it is also the only way to get grbl back after the
        MCU has locked up (a hung board stops answering '?' but the USB device
        stays). After a reset the position is unknown - the GUI says so.
        """
        first = True
        while not self._halt.is_set():
            try:
                link = self.link_factory()
            except LinkError as e:
                self.events.put(("error", str(e)))
                if first or not self.reconnect:
                    self.events.put(("closed", None))
                    return
                time.sleep(2.0)
                continue
            g = Grbl(link)
            try:
                banner = g.connect()
                self.events.put(("banner", banner))
                if not first:
                    self.events.put(("reset", None))
                if any("unlock" in l for l in banner):
                    if self.homing.enabled:
                        # Position is unknown until $H; $X would let soft limits
                        # work on a bogus position. Leave the alarm, say so.
                        self.events.put(("needs_homing", None))
                    else:
                        g.unlock()
                        self.events.put(("sent", "$X   (Alarm beim Start entsperrt)"))
                self._sync_settings(g)
                self._refresh_offset(g)
                first = False
                self._serve(g)                      # returns when the link is gone
            except _LINK_ERRORS as e:
                self.events.put(("error", f"Verbindung verloren: {e}"))
            finally:
                try:
                    link.close()
                except Exception:
                    pass
            if self._halt.is_set() or not self.reconnect:
                break
            self.events.put(("error", "verbinde neu ..."))
            time.sleep(self.retry_delay)
        self.events.put(("closed", None))

    def _serve(self, g: Grbl) -> None:
        last_poll = 0.0
        silent = 0
        while not self._halt.is_set():
            try:
                kind, payload = self.cmds.get(timeout=0.05)
            except queue.Empty:
                kind = None
            if kind == "line":
                self._line(g, payload)
            elif kind == "raw":
                self._raw(g, payload)
            elif kind == "offset":
                self._refresh_offset(g)
            elif kind == "sync":
                self._sync_settings(g)
            elif kind == "stream":
                self._stream(g, payload)
            elif kind == "home":
                self._home(g)
            elif kind in ("probe_pos", "probe_status"):
                try:
                    st = g.status(timeout=self.status_timeout)
                    payload.put(st["mpos"] if kind == "probe_pos" else st)
                except TimeoutError:
                    pass
            if time.monotonic() - last_poll >= self.poll:
                last_poll = time.monotonic()
                try:
                    st = g.status(timeout=self.status_timeout)
                    self.events.put(("status", st))
                    silent = 0
                    self._limit_guard(g, st)
                except TimeoutError:
                    silent += 1
                    if silent >= self.hang_polls:
                        raise LinkError("Board antwortet nicht mehr (MCU haengt?)")

    def _limit_guard(self, g: Grbl, st: dict) -> None:
        """A switch during Run/Jog means the work zero or the travel is wrong:
        hold, reset, and tell the GUI. (Homing itself presses them, of course.)"""
        pressed = [a for a in AXES if a in st.get("pn", "")]
        if pressed and st["state"] in ("Run", "Jog"):
            g.link.write_raw(b"!")
            time.sleep(0.2)
            g.link.write_raw(b"\x18")
            self._abort.set()
            time.sleep(0.5)
            g.link.drain()
            self.events.put(("limit", " ".join(pressed)))

    def _home(self, g: Grbl) -> None:
        self.events.put(("sent", "$H   (Referenzfahrt, bitte warten)"))
        try:
            mpos = hm.reference(g, self.homing)
            self._refresh_offset(g)
            self.events.put(("homed", dict(mpos)))
        except (GrblError, GrblAlarm, TimeoutError, RuntimeError) as e:
            self.events.put(("error", f"Referenzfahrt: {e}"))

    def _raw(self, g: Grbl, payload: bytes) -> None:
        g.link.write_raw(payload)
        if payload == b"\x18":
            time.sleep(0.5)
            g.link.drain()
            self._refresh_offset(g)

    def _sync_settings(self, g: Grbl) -> None:
        """The settings file + machine.json are the source of truth. A board
        that came back with factory defaults ($RST=*, reflash) gets them all
        back here, and the log shows exactly what was off."""
        try:
            current = g.settings()
            fixed = 0
            # $22 (homing) must land before $20 (soft limits), else error 10
            for k, v in sorted(self.settings.items(), key=lambda kv: (kv[0] != 22, kv[0])):
                if k not in current or abs(current[k] - v) > 1e-6:
                    g.set_setting(k, v)
                    self.events.put(("sent", f"${k}={v:g}   (war {current.get(k, '-')!s:>6}, korrigiert)"))
                    fixed += 1
            if fixed:
                self.events.put(("error", f"{fixed} Settings auf dem Board wichen ab - wiederhergestellt"))
        except (GrblError, GrblAlarm, TimeoutError) as e:
            self.events.put(("error", f"Settings: {e}"))

    def _stream(self, g: Grbl, lines: list[str]) -> None:
        """Send a program line by line, keeping status and STOP responsive.

        grbl answers 'ok' the moment it has taken a line into its buffer and
        holds the 'ok' back while the buffer is full, so a single line can
        block for the length of a move. Meanwhile we keep sending '?' and
        forward the reports, and we watch for an abort.
        """
        self._abort.clear()
        n = len(lines)
        aborted = False
        last_poll = 0.0
        for i, raw in enumerate(lines, start=1):
            line = raw.split(";", 1)[0].strip()
            if not line:
                continue
            g.link.write_line(line)
            while True:
                if self._abort.is_set():
                    aborted = True
                    break
                self._drain_raw_cmds(g)
                if time.monotonic() - last_poll >= self.poll:
                    last_poll = time.monotonic()
                    g.link.write_raw(b"?")
                resp = g.link.read_line(timeout=0.1)
                if resp is None:
                    continue
                if resp.startswith("<"):
                    try:
                        st = parse_status(resp)
                    except ValueError:
                        continue
                    self.events.put(("status", st))
                    pressed = [a for a in AXES if a in st.get("pn", "")]
                    if pressed and st["state"] in ("Run", "Jog"):
                        self.events.put(("limit", " ".join(pressed)))
                        aborted = True
                        break
                elif resp == "ok":
                    break
                elif resp.startswith("error:") or resp.startswith("ALARM:"):
                    self.events.put(("error", f"{resp} bei Zeile {i}: {line}"))
                    aborted = True
                    break
            if aborted:
                break
            self.events.put(("progress", (i, n, line)))
        if aborted:
            # feed hold, then soft reset: stops motion now and flushes the planner
            g.link.write_raw(b"!")
            time.sleep(0.2)
            self._raw(g, b"\x18")
            self.events.put(("stream_done", False))
        else:
            self.events.put(("stream_done", True))

    def _drain_raw_cmds(self, g: Grbl) -> None:
        """During a stream only real-time bytes (pause/resume) are honoured."""
        while True:
            try:
                kind, payload = self.cmds.get_nowait()
            except queue.Empty:
                return
            if kind == "raw":
                g.link.write_raw(payload)
            else:
                self.events.put(("error", "waehrend des Programms nicht moeglich"))

    def _line(self, g: Grbl, line: str) -> None:
        self.events.put(("sent", line))
        try:
            self.events.put(("reply", g.command(line, timeout=120)))
            if line.startswith("G10") or line.startswith("$X"):
                self._refresh_offset(g)
        except (GrblError, GrblAlarm, TimeoutError) as e:
            self.events.put(("error", str(e)))

    def _refresh_offset(self, g: Grbl) -> None:
        try:
            self.events.put(("offset", g.work_offsets().get("G54", {a: 0.0 for a in AXES})))
        except (GrblError, GrblAlarm, TimeoutError) as e:
            self.events.put(("error", str(e)))


