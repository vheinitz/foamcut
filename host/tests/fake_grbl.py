"""A stateful stand-in for grbl-Mega-5X: tracks position, settings, offsets.

Just enough protocol for the wizard: `$J=` jogs move the position, `?` reports
it, `$n=v` stores a setting, `G10 L20 P1` moves the work offset.
"""
from __future__ import annotations

import re

from foamcut import AXES

_WORD = re.compile(r"([XYUVF])(-?\d+\.?\d*)")


class FakeGrblLink:
    def __init__(self, settings: dict[int, float] | None = None, direction=None):
        self.settings = {3: 0.0, 100: 400.0, 101: 400.0, 102: 400.0, 103: 400.0,
                         130: 0.0, 131: 0.0, 132: 0.0, 133: 0.0}
        if settings:
            self.settings.update(settings)
        self.mpos = {a: 0.0 for a in AXES}
        self.wco = {a: 0.0 for a in AXES}
        self.state = "Idle"
        self.sent: list[str] = []
        self._pending = ["Grbl 1.2i ['$' for help]"]
        # physical direction per axis; the wizard's $3 flips make +jog move -mm
        self.direction = direction or {a: +1 for a in AXES}
        self.homed = False

    # -- link protocol ------------------------------------------------------
    def drain(self):
        out, self._pending = self._pending, []
        return out

    def read_line(self, timeout=0):
        return self._pending.pop(0) if self._pending else None

    def write_raw(self, data: bytes):
        self.sent.append(repr(data))
        if data == b"?":
            pos = ",".join(f"{self.mpos[a]:.3f}" for a in AXES)
            pn = f"|Pn:{self.pressed}" if getattr(self, "pressed", "") else ""
            self._pending.append(f"<{self.state}|MPos:{pos}|FS:0,0{pn}>")

    def close(self):
        pass

    def write_line(self, text: str):
        text = text.strip()
        self.sent.append(text)
        if text == "$$":
            self._pending += [f"${k}={v:g}" for k, v in sorted(self.settings.items())]
        elif text == "$#":
            self._pending.append("[G54:" + ",".join(f"{self.wco[a]:.3f}" for a in AXES) + "]")
        elif text.startswith("$") and "=" in text and not text.startswith("$J"):
            k, v = text[1:].split("=")
            self.settings[int(k)] = float(v)
        elif text.startswith("$J="):
            self._jog(text[3:])
            if getattr(self, "release_on_jog", False):
                self.pressed = ""
        elif text.startswith("G10 L20 P1"):
            for a, v in _WORD.findall(text):
                if a in AXES:
                    self.wco[a] = self.mpos[a] - float(v)
        elif text.startswith("G10 L2 P1"):
            for a, v in _WORD.findall(text):
                if a in AXES:
                    self.wco[a] = float(v)
        elif text == "$X":
            self.state = "Idle"
        elif text == "$H":
            if not self.settings.get(22):
                self._pending.append("error:5")
                return
            self.pressed = ""                     # the cycle ends off the switches
            # grbl 1.1: after homing toward the negative end the axis sits at
            # -max_travel + pulloff; toward the positive end at -pulloff.
            pulloff = self.settings.get(27, 1.0)
            mask = int(self.settings.get(23, 0))
            for i, a in enumerate(AXES):
                travel = self.settings.get(130 + i, 0.0)
                self.mpos[a] = (-travel + pulloff) if mask & (1 << i) else -pulloff
            self.homed = True
        self._pending.append("ok")

    def _jog(self, body: str):
        absolute = "G90" in body
        for a, v in _WORD.findall(body):
            if a not in AXES:
                continue
            v = float(v)
            inv = -1 if int(self.settings[3]) & (1 << AXES.index(a)) else 1
            phys = self.direction[a] * inv
            if absolute:
                self.mpos[a] = self.wco[a] + v          # work -> machine
            else:
                self.mpos[a] += v * phys

    # -- helpers for assertions ---------------------------------------------
    def wpos(self):
        return {a: self.mpos[a] - self.wco[a] for a in AXES}
