"""Serial transport. Line oriented, no sleep based guessing."""
from __future__ import annotations

import glob
import os
import time


class LinkError(RuntimeError):
    pass


def list_ports() -> list[str]:
    """Candidate serial ports, most recently enumerated first.

    A GT2560 with a CH340 re-enumerates on every reset and does not always
    come back as the same ttyUSBn, so pinning the port in a script is a trap.
    """
    ports = glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*")
    return sorted(ports, key=lambda p: os.stat(p).st_mtime, reverse=True)


def find_port(preferred: str | None = None) -> str:
    """Resolve a port name. 'auto' or None picks the newest one present."""
    if preferred and preferred != "auto":
        return preferred
    ports = list_ports()
    if not ports:
        raise LinkError(
            "kein serieller Port gefunden - Board angesteckt und mit Strom "
            "versorgt? (ls /dev/ttyUSB*)"
        )
    return ports[0]


class SerialLink:
    """A newline delimited serial connection to the controller."""

    def __init__(self, port: str | None = "auto", baud: int = 115200,
                 reset_delay: float = 2.0):
        port = find_port(port)
        try:
            import serial  # noqa: PLC0415 - optional dependency
        except ImportError as e:  # pragma: no cover
            raise LinkError("pyserial is not installed: pip install pyserial") from e
        try:
            self._ser = serial.Serial(port, baud, timeout=0.1)
        except Exception as e:
            raise LinkError(f"cannot open {port}: {e}") from e
        self.port = port
        # Opening the port toggles DTR, which resets the ATmega2560.
        time.sleep(reset_delay)
        self._buf = b""
        # Opening the port reset the board, so the banner arrives now. Keep it:
        # connect() further up the stack needs it to tell the firmwares apart.
        self._startup = self._read_pending()

    def drain(self) -> list[str]:
        """Everything waiting, including the banner captured when we opened."""
        out, self._startup = self._startup, []
        return out + self._read_pending()

    def _read_pending(self) -> list[str]:
        out = []
        deadline = time.monotonic() + 0.3
        while time.monotonic() < deadline:
            line = self.read_line(timeout=0.1)
            if line is None:
                break
            out.append(line)
        return out

    def write_line(self, text: str) -> None:
        self._ser.write((text.rstrip("\r\n") + "\n").encode())
        self._ser.flush()

    def write_raw(self, data: bytes) -> None:
        """For grbl real time bytes such as 0x18 (soft reset) or '?'."""
        self._ser.write(data)
        self._ser.flush()

    def read_line(self, timeout: float = 2.0) -> str | None:
        deadline = time.monotonic() + timeout
        while True:
            if b"\n" in self._buf:
                line, self._buf = self._buf.split(b"\n", 1)
                return line.decode(errors="replace").strip()
            if time.monotonic() >= deadline:
                return None
            chunk = self._ser.read(max(1, self._ser.in_waiting))
            if chunk:
                self._buf += chunk

    def close(self) -> None:
        self._ser.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class FakeLink:
    """In-memory link for tests and dry runs.

    `responder` maps a sent line to the list of lines to answer with. Anything
    not in the map gets a plain "ok", which is what grbl does for a command it
    accepts and has nothing to say about.
    """

    def __init__(self, responder: dict[str, list[str]] | None = None,
                 banner: list[str] | None = None):
        self.responder = responder or {}
        self.sent: list[str] = []
        self._pending: list[str] = list(banner or [])
        self.closed = False

    def drain(self) -> list[str]:
        out, self._pending = self._pending, []
        return out

    def write_line(self, text: str) -> None:
        text = text.strip()
        self.sent.append(text)
        self._pending.extend(self.responder.get(text, ["ok"]))

    def write_raw(self, data: bytes) -> None:
        self.sent.append(repr(data))
        if data == b"?":
            self._pending.extend(
                self.responder.get("?", ["<Idle|MPos:0.000,0.000,0.000,0.000|FS:0,0>"])
            )

    def read_line(self, timeout: float = 2.0) -> str | None:
        return self._pending.pop(0) if self._pending else None

    def close(self) -> None:
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
