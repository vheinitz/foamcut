"""JogModel - turns pad clicks into grbl jog commands. Shared by both GUIs."""
from __future__ import annotations

from dataclasses import dataclass, field

from . import AXES
from .machine import Machine

STEP_SIZES = (1.0, 5.0, 25.0, 100.0)
HORIZONTAL = ("X", "U")
VERTICAL = ("Y", "V")


@dataclass
class JogModel:
    """Pure command builder - what a click turns into."""
    machine: Machine
    step: float = 5.0
    feed_h: float = 600.0
    feed_v: float = 138.0
    wpos: dict[str, float] = field(default_factory=lambda: {a: 0.0 for a in AXES})

    def __post_init__(self):
        # vertical axes are step-rate limited in grbl; do not offer more
        self.feed_v = min(self.feed_v, min(self.machine.max_rate[a] for a in VERTICAL))
        self.feed_h = min(self.feed_h, min(self.machine.max_rate[a] for a in HORIZONTAL))

    def feed_for(self, axes) -> float:
        """grbl limits every axis to its own $11x on its own, so a mixed move
        gets the higher feed and the vertical part is slowed only as much as
        it has to be - a 'zur Referenz' move must not crawl at vertical speed."""
        feeds = [self.feed_v if a in VERTICAL else self.feed_h for a in axes]
        return max(feeds)

    def jog(self, moves: dict[str, int]) -> str:
        """{'X': +1, 'U': +1} -> '$J=G91 G21 X5.000 U5.000 F600'"""
        words = " ".join(f"{a}{sign * self.step:.3f}" for a, sign in moves.items())
        return f"$J=G91 G21 {words} F{self.feed_for(moves):g}"

    def goto_reference(self) -> str:
        words = " ".join(f"{a}0" for a in AXES)
        return f"$J=G90 G21 {words} F{self.feed_for(AXES):g}"

    def set_reference(self) -> str:
        return "G10 L20 P1 " + " ".join(f"{a}0" for a in AXES)

    def record_travel(self, axis: str) -> float:
        """Current work position of `axis` becomes its travel; returns it."""
        value = round(self.wpos[axis], 3)
        self.machine.travel_mm[axis] = value
        return value

    def hotwire(self, power: int) -> str:
        return "M5" if power <= 0 else f"M3 S{int(power)}"




def straight_cut(length_mm: float, angle_deg: float, feed: float, warmup: float = 3.0,
                 wire: int = 0, back: bool = False, skew: tuple[float, float] = (0.0, 0.0)) -> str:
    """One straight cut from wherever the wire is now, both towers alike.

    angle 0 = forward (+X/+U), 90 = up (+Y/+V), 180 = back, 270 = down.
    `back` returns to the start afterwards, wire still on, so a slit is cut
    twice (cleaner) and the wire ends where it began.
    `skew` = (dU, dV): tower 2 is first offset by that much (wire still cold),
    so the wire is tilted and the cut becomes a tilted plane - dU with an
    up/down cut gives a swept (Pfeilung) face, dV with a forward/back cut a
    face sloping across the span. The offset is undone at the end.
    """
    import math
    if length_mm <= 0 or feed <= 0:
        raise ValueError("Laenge und Vorschub muessen > 0 sein")
    dx = length_mm * math.cos(math.radians(angle_deg))
    dy = length_mm * math.sin(math.radians(angle_deg))
    du, dv = skew
    s_wire = wire if wire > 0 else 1                  # S1 = slider value, see gcode.translate
    lines = [
        f"; foamcut Freischnitt {length_mm:g} mm, {angle_deg:g} deg, {feed:g} mm/min"
        + (f", Turm 2 versetzt U{du:g} V{dv:g}" if (du or dv) else ""),
        "G21", "G91 ; relativ ab hier", "G94",
    ]
    if du or dv:
        lines.append(f"G1 U{du:.3f} V{dv:.3f} F{feed:g} ; Draht schraeg stellen (kalt)")
    lines += [
        f"M3 S{s_wire}", f"G4 P{warmup:g}",
        f"G1 X{dx:.3f} Y{dy:.3f} U{dx:.3f} V{dy:.3f} F{feed:g}",
    ]
    if back:
        lines.append(f"G1 X{-dx:.3f} Y{-dy:.3f} U{-dx:.3f} V{-dy:.3f} F{feed:g}")
    lines.append("M5")
    if du or dv:
        lines.append(f"G1 U{-du:.3f} V{-dv:.3f} F{feed:g} ; Draht wieder gerade (kalt)")
    lines += ["G90", "M2"]
    return "\n".join(lines) + "\n"
