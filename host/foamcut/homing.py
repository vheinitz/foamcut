"""Referencing with limit switches: $H, then the work origin from the offsets.

    home_mpos = machine position right after $H  (grbl's convention, whatever it is)
    G54       = home_mpos + offset_mm            (work origin, per axis)

So work coordinates start at 0 on the offset origin and grow forward / up,
exactly like the manual `foamcut ref` did - the switches just make it repeatable.
"""
from __future__ import annotations

from . import AXES
from .grbl import Grbl
from .machine import Homing


CLEAR_MM = 5.0        # back off this far first when a switch is already pressed


def clear_switches(g: Grbl) -> list[str]:
    """Move every axis whose switch is pressed 5 mm away from it (all switches
    sit at the negative end). grbl would otherwise start $H on a pressed switch,
    pull off its 1..3 mm and give up (ALARM:8) if the switch is still open."""
    pressed = [a for a in AXES if a in g.status().get("pn", "")]
    if not pressed:
        return []
    g.command("$X")
    g.command("$20=0")                                  # jogging must be allowed in unknown position
    try:
        g.command("$J=G91 " + " ".join(f"{a}{CLEAR_MM:g}" for a in pressed) + " F100")
        g.wait_idle(timeout=60)
    finally:
        g.command("$20=1")
    still = [a for a in AXES if a in g.status().get("pn", "")]
    if still:
        raise RuntimeError(f"Endschalter {' '.join(still)} bleibt nach {CLEAR_MM:g} mm Wegfahren gedrueckt - "
                           "Schalter/Kabel pruefen")
    return pressed


def reference(g: Grbl, homing: Homing, timeout: float = 300.0) -> dict[str, float]:
    """Run the homing cycle and set G54. Returns the machine position at home."""
    clear_switches(g)
    g.command("$H", timeout=timeout)
    mpos = g.status()["mpos"]
    origin = homing.work_origin(mpos)
    g.command("G10 L2 P1 " + " ".join(f"{a}{origin[a]:.3f}" for a in AXES))
    g.command("G54")
    homing.home_mpos = dict(mpos)
    return mpos


def offset_from_current(g: Grbl, homing: Homing, axis: str) -> float:
    """Offset that would make the current position this axis' work origin.

    Used in the calibration dialog: home, jog the axis to where zero should
    be (e.g. until the wire is level), press "= aktuelle Position".
    """
    if not homing.home_mpos:
        raise RuntimeError("erst Referenzfahrt, dann Offset uebernehmen")
    return round(g.status()["mpos"][axis] - homing.home_mpos[axis], 3)
