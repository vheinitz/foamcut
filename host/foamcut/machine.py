"""Persistent machine description: what `foamcut setup` measured.

grbl keeps steps/mm, direction bits and so on in its own EEPROM. What it
cannot keep for a machine without limit switches is the usable travel, because
its soft limits require homing. That number lives here and `foamcut run` enforces
it on the host instead.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import AXES

DEFAULT_PATH = Path("config/machine.json")
SETTINGS_FILE = Path("config/grbl_settings_foamcut.txt")


def parse_settings_file(text: str) -> dict[int, float]:
    """`$n=v` lines of the commented settings file -> {n: v}."""
    out = {}
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if line.startswith("$") and "=" in line:
            k, _, v = line[1:].partition("=")
            try:
                out[int(k)] = float(v)
            except ValueError:
                continue
    return out


def standard_settings(machine: "Machine", settings_file: Path = SETTINGS_FILE) -> dict[int, float]:
    """Everything the board must have: the file's values, overridden by what
    was measured into machine.json ($3, $100.., $110.., $130..)."""
    out = parse_settings_file(settings_file.read_text()) if settings_file.exists() else {}
    out.update(machine.grbl_settings())
    return out


# Measured on this machine, see config/grbl_settings_foamcut.txt for the log.
DEFAULT_STEPS_PER_MM = {"X": 1600.0, "Y": 8704.0, "U": 1600.0, "V": 8704.0}

# Step rate ceiling of grbl-Mega-5X on the ATmega2560 with four axes.
# Measured 2026-09-13: 24 kHz fine, 30 kHz locks the MCU up mid-move (the
# stepper ISR overruns and the main loop never runs again). 20 kHz leaves
# margin; every max_rate is derived from it.
MAX_STEP_HZ = 20000.0


def rate_cap(steps_per_mm: float, max_step_hz: float = MAX_STEP_HZ) -> float:
    """Highest mm/min an axis may be given without exceeding the step budget."""
    return round(max_step_hz / steps_per_mm * 60.0, 1)


DEFAULT_MAX_RATE = {a: rate_cap(s) for a, s in DEFAULT_STEPS_PER_MM.items()}


@dataclass
class Homing:
    """Limit switch referencing, with a per-axis work origin offset.

    The switches cannot be mounted to the tenth of a millimetre on four axes,
    and the wire between the towers is not level when both are at their
    switches. So the *machine* origin is wherever grbl's homing puts it, and
    the *work* origin (what every G-code program uses) sits `offset_mm`
    further in the positive direction on each axis - the G54 offset in CNC
    terms. `length_mm` is the usable travel from the switch, typed in by hand.
    """
    enabled: bool = False
    offset_mm: dict[str, float] = field(default_factory=lambda: {a: 0.0 for a in AXES})
    length_mm: dict[str, float] = field(default_factory=lambda: {a: 0.0 for a in AXES})
    pulloff: float = 3.0          # $27  back off the switch after triggering
    feed: float = 100.0           # $24  slow locate speed
    seek: float = 500.0           # $25  fast search speed (grbl clamps per axis)
    invert_switch: bool = False   # NC switches; documented only - the inversion lives in the firmware
    soft_limits: bool = True      # $20  grbl refuses moves outside the travel
    home_mpos: dict[str, float] | None = None   # MPos right after the last $H
    auto: bool = True             # run $H by itself when grbl reports "position unknown"

    DIR_MASK = 15                 # $23: all four switches at the negative (back/bottom) end

    def usable_travel(self, axis: str) -> float:
        """Work-coordinate range from the offset origin to the far end."""
        return max(0.0, self.length_mm[axis] - self.pulloff - self.offset_mm[axis])

    def work_origin(self, home_mpos: dict[str, float]) -> dict[str, float]:
        """G54 values: machine coordinates of the work origin."""
        return {a: home_mpos[a] + self.offset_mm[a] for a in AXES}

    def grbl_settings(self) -> dict[int, float]:
        if not self.enabled:
            return {20: 0.0, 22: 0.0}
        # $22 before $20: grbl refuses soft limits (error 10) while homing is off.
        # $5 stays 0 even for NC switches: grbl-Mega-5X ANDs MIN and MAX inputs
        # when $5=1 and the unwired MAX inputs would read as "hit". The NC
        # inversion is compiled in (INVERT_MIN_LIMIT_PIN_MASK, firmware/grbl5x).
        out = {22: 1.0, 5: 0.0, 20: 1.0 if self.soft_limits else 0.0,
               23: float(self.DIR_MASK), 24: self.feed, 25: self.seek, 27: self.pulloff}
        for i, a in enumerate(AXES):
            out[130 + i] = self.length_mm[a]
        return out


@dataclass
class Machine:
    steps_per_mm: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_STEPS_PER_MM))
    max_rate: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_MAX_RATE))
    invert_dir: dict[str, bool] = field(default_factory=lambda: {a: False for a in AXES})
    travel_mm: dict[str, float] = field(default_factory=lambda: {a: 0.0 for a in AXES})
    tower_gap_mm: float = 800.0  # distance between the two wire attachment points
    tower_gap_measured: bool = False   # False = the 800 is a placeholder, warn
    # The wire is clamped at one tower and weight-tensioned over a pulley at the
    # other. Only the clamped end is a precise reference, so wing roots go there.
    wire_fixed_tower: int = 2          # 1 = X/Y, 2 = U/V
    homing: Homing = field(default_factory=Homing)
    jog_feed: float = 750.0     # horizontal jog; vertical is clamped to max_rate
    cut_feed: float = 300.0
    wire_power: int = 0
    notes: str = ""

    # ------------------------------------------------------------ grbl -----
    def direction_mask(self) -> int:
        """$3 bit mask: bit 0 = X, 1 = Y, 2 = U, 3 = V."""
        return sum(1 << i for i, a in enumerate(AXES) if self.invert_dir[a])

    def grbl_settings(self) -> dict[int, float]:
        out = {3: float(self.direction_mask())}
        for i, a in enumerate(AXES):
            out[100 + i] = self.steps_per_mm[a]
            out[110 + i] = self.max_rate[a]
            out[130 + i] = self.travel_mm[a]
        out.update(self.homing.grbl_settings())     # $130.. become the switch lengths when homing
        return out

    def has_travel(self) -> bool:
        return all(self.travel_mm[a] > 0 for a in AXES)

    def apply_homing_travel(self) -> None:
        """With switches, the host-side travel follows from length and offset."""
        if self.homing.enabled:
            for a in AXES:
                self.travel_mm[a] = round(self.homing.usable_travel(a), 3)

    def clamp_rates(self) -> list[str]:
        """Pull every max_rate under the step budget. Returns what changed."""
        notes = []
        for a in AXES:
            cap = rate_cap(self.steps_per_mm[a])
            if self.max_rate[a] > cap:
                notes.append(f"{a}: max_rate {self.max_rate[a]:g} -> {cap:g} mm/min "
                             f"({MAX_STEP_HZ / 1000:g} kHz bei {self.steps_per_mm[a]:g} Schritten/mm)")
                self.max_rate[a] = cap
        return notes

    # ----------------------------------------------------------- checks ----
    def check_extents(self, extents: dict[str, tuple[float, float]],
                      margin: float = 0.01) -> list[str]:
        """Which axes a program (in reference coordinates) would overrun."""
        problems = []
        for a in AXES:
            lo, hi = extents[a]
            tr = self.travel_mm[a]
            if tr <= 0:
                problems.append(f"{a}: Verfahrweg nicht vermessen (foamcut setup)")
            elif lo < -margin:
                problems.append(f"{a}: faehrt bis {lo:.3f} mm, unter den Referenzpunkt")
            elif hi > tr + margin:
                problems.append(f"{a}: faehrt bis {hi:.3f} mm, Verfahrweg ist {tr:.3f}")
        return problems

    # -------------------------------------------------------------- io -----
    def save(self, path: Path | None = None) -> Path:
        """Write to `path`, else to wherever this machine was loaded from."""
        path = path or getattr(self, "_path", None) or DEFAULT_PATH
        self._path = path
        self.clamp_rates()
        self.apply_homing_travel()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2, sort_keys=True) + "\n")
        return path

    @classmethod
    def load(cls, path: Path = DEFAULT_PATH) -> "Machine":
        data = json.loads(path.read_text())
        m = cls()
        for key, value in data.items():
            if key == "homing" and isinstance(value, dict):
                h = Homing()
                for hk, hv in value.items():
                    if hasattr(h, hk) and hk != "DIR_MASK":
                        setattr(h, hk, hv)
                m.homing = h
            elif hasattr(m, key):
                setattr(m, key, value)
        m.wire_fixed_tower = 1 if m.wire_fixed_tower == 1 else 2
        m._path = path
        m.clamp_rates()
        m.apply_homing_travel()
        return m

    @classmethod
    def load_or_none(cls, path: Path = DEFAULT_PATH) -> "Machine | None":
        return cls.load(path) if path.exists() else None
