"""Simulation of a program: the two carriage paths, drawn like a turtle.

Pure part here (testable), the tk window is in gui_sim.py.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import gcode as gc

Point = tuple[float, float]


@dataclass
class Segment:
    line_no: int
    rapid: bool
    t1_start: Point
    t1_end: Point
    t2_start: Point
    t2_end: Point
    seconds: float          # how long the machine takes for it

    @property
    def wire_on(self) -> bool:
        return not self.rapid


def segments(prog: gc.Program, rapid_feed: float = 750.0) -> list[Segment]:
    """One Segment per move, with tower 1 = (X, Y) and tower 2 = (U, V)."""
    out = []
    for m in prog.moves:
        if m.inverse_time and not m.rapid and m.feed:
            secs = 60.0 / m.feed
        else:
            f = rapid_feed if m.rapid else (m.feed or rapid_feed)
            secs = m.length() / f * 60.0 if f > 0 else 0.0
        out.append(Segment(m.line_no, m.rapid,
                           (m.start["X"], m.start["Y"]), (m.end["X"], m.end["Y"]),
                           (m.start["U"], m.start["V"]), (m.end["U"], m.end["V"]),
                           secs))
    return out


def bounds(segs: list[Segment]) -> tuple[tuple[float, float, float, float], tuple[float, float, float, float]]:
    """(xmin, xmax, ymin, ymax) for tower 1 and tower 2, origin included."""
    def box(pts):
        xs = [0.0] + [p[0] for p in pts]
        ys = [0.0] + [p[1] for p in pts]
        return (min(xs), max(xs), min(ys), max(ys))
    p1 = [s.t1_start for s in segs] + [s.t1_end for s in segs]
    p2 = [s.t2_start for s in segs] + [s.t2_end for s in segs]
    return box(p1), box(p2)


def total_seconds(segs: list[Segment]) -> float:
    return sum(s.seconds for s in segs)
