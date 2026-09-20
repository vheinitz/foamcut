"""grbl-Mega-5X protocol: send a line, wait for ok, parse status and settings."""
from __future__ import annotations

import re
import time

from . import AXES

_STATUS = re.compile(r"<([^|>]+)\|([^>]*)>")
_SETTING = re.compile(r"^\$(\d+)=([-\d.]+)")
_OFFSET = re.compile(r"^\[(G5[4-9]|G28|G30|G92):([-\d.,]+)\]")

# The handful of grbl errors you actually hit when bringing a machine up.
ERROR_TEXT = {
    1: "unsupported or missing G-code letter",
    2: "bad number format",
    3: "invalid $ statement",
    4: "negative value where a positive one is required",
    5: "homing is not enabled ($22=0)",
    8: "$ command needs Idle state",
    9: "G-code locked out during alarm or jog",
    15: "jog exceeds the machine travel",
    20: "unsupported or unrecognised G-code command",
    22: "feed rate has not been set",
    24: "two G-code commands that both use axis words",
    33: "invalid motion target",
}


class GrblError(RuntimeError):
    def __init__(self, code: int, sent: str):
        self.code = code
        self.sent = sent
        hint = ERROR_TEXT.get(code, "see the grbl error code list")
        super().__init__(f"error:{code} on {sent!r} - {hint}")


class GrblAlarm(RuntimeError):
    pass


class Grbl:
    """Thin, synchronous grbl client. One line out, responses in."""

    def __init__(self, link):
        self.link = link
        self.banner: list[str] = []

    # ------------------------------------------------------------ plumbing --
    def connect(self, timeout: float = 3.0) -> list[str]:
        """Collect the startup banner. grbl announces itself as 'Grbl 1.1 ...'."""
        self.banner = [l for l in self.link.drain() if l]
        if not self.banner:
            # Board was already up; a soft reset makes it reintroduce itself.
            self.link.write_raw(b"\x18")
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                line = self.link.read_line(timeout=0.5)
                if line is None:
                    continue
                self.banner.append(line)
                if line.startswith("Grbl"):
                    break
        return self.banner

    def is_grbl(self) -> bool:
        return any(l.startswith("Grbl") for l in self.banner)

    def command(self, line: str, timeout: float = 30.0) -> list[str]:
        """Send one line, collect everything up to and including 'ok'."""
        self.link.write_line(line)
        out: list[str] = []
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            resp = self.link.read_line(timeout=0.5)
            if resp is None:
                continue
            if resp == "ok":
                return out
            if resp.startswith("error:"):
                raise GrblError(int(resp.split(":", 1)[1]), line)
            if resp.startswith("ALARM:"):
                raise GrblAlarm(f"{resp} while sending {line!r}")
            out.append(resp)
        raise TimeoutError(f"no ok for {line!r} after {timeout} s")

    # -------------------------------------------------------------- status --
    def status(self, timeout: float = 2.0) -> dict:
        """Ask for a real time status report and parse it."""
        self.link.write_raw(b"?")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            line = self.link.read_line(timeout=0.5)
            if line and line.startswith("<"):
                return parse_status(line)
        raise TimeoutError("no status report")

    def wait_idle(self, timeout: float = 600.0, poll: float = 0.25) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            st = self.status()
            if st["state"] == "Idle":
                return
            if st["state"] == "Alarm":
                raise GrblAlarm("machine went into alarm while waiting for Idle")
            time.sleep(poll)
        raise TimeoutError("machine never returned to Idle")

    # ------------------------------------------------------------ settings --
    def settings(self) -> dict[int, float]:
        out = {}
        for line in self.command("$$"):
            m = _SETTING.match(line)
            if m:
                out[int(m.group(1))] = float(m.group(2))
        return out

    def apply_settings(self, text: str) -> list[str]:
        """Send every `$n=v` line of a settings file, skipping comments."""
        applied = []
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line.startswith("$") or "=" not in line:
                continue
            self.command(line)
            applied.append(line)
        return applied

    def set_setting(self, number: int, value: float) -> None:
        self.command(f"${number}={value:g}")

    def work_offsets(self) -> dict[str, dict[str, float]]:
        """`$#` -> {'G54': {'X': .., ...}, 'G92': {...}, ...}"""
        out = {}
        for line in self.command("$#"):
            m = _OFFSET.match(line)
            if m:
                nums = [float(v) for v in m.group(2).split(",")]
                out[m.group(1)] = dict(zip(AXES, nums))
        return out

    # ------------------------------------------------------------ commands --
    def unlock(self) -> None:
        self.command("$X")

    def jog(self, axis: str, mm: float, feed: float, wait: bool = True) -> None:
        """Relative jog of one axis, blocking until the machine is idle."""
        self.command(f"$J=G91 G21 {axis}{mm:.3f} F{feed:g}")
        if wait:
            self.wait_idle()

    def jog_to(self, targets: dict[str, float], feed: float, wait: bool = True) -> None:
        """Absolute jog in work coordinates."""
        words = " ".join(f"{a}{v:.3f}" for a, v in targets.items())
        self.command(f"$J=G90 G21 {words} F{feed:g}")
        if wait:
            self.wait_idle()

    def cancel_jog(self) -> None:
        self.link.write_raw(b"\x85")

    def home(self) -> None:
        self.command("$H", timeout=180.0)

    def zero_here(self) -> None:
        """Set the current position as work zero for all four axes."""
        self.command("G10 L20 P1 " + " ".join(f"{a}0" for a in AXES))

    def hotwire(self, power: int) -> None:
        """0..255 with $30=255. M5 fully off, M3 S<n> otherwise."""
        if power <= 0:
            self.command("M5")
        else:
            self.command(f"M3 S{int(power)}")

    def stream(self, lines, progress=None) -> int:
        """Send a program one line at a time, waiting for ok on each.

        Simple and slow to fill the planner, but it reports the exact line that
        failed - which is what you want while bringing a machine up. Swap for
        character counting once the machine cuts reliably.
        """
        sent = 0
        for i, raw in enumerate(lines, start=1):
            line = raw.split(";", 1)[0].strip()
            if not line:
                continue
            self.command(line)
            sent += 1
            if progress:
                progress(i, line)
        return sent


def parse_status(line: str) -> dict:
    """'<Idle|MPos:1,2,3,4|FS:0,0>' -> {'state': 'Idle', 'mpos': {...}, ...}"""
    m = _STATUS.match(line.strip())
    if not m:
        raise ValueError(f"not a grbl status report: {line!r}")
    out: dict = {"state": m.group(1).split(":")[0], "raw": line.strip()}
    for field in m.group(2).split("|"):
        if ":" not in field:
            continue
        key, _, val = field.partition(":")
        if key in ("MPos", "WPos"):
            nums = [float(v) for v in val.split(",")]
            out[key.lower()] = dict(zip(AXES, nums))
        elif key == "FS":
            feed, _, speed = val.partition(",")
            out["feed"] = float(feed)
            out["spindle"] = float(speed or 0)
        elif key == "Bf":
            blocks, _, chars = val.partition(",")
            out["planner_free"] = int(blocks)
            out["rx_free"] = int(chars)
        else:
            out[key.lower()] = val
    return out
