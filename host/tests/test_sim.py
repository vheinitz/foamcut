import pytest

from foamcut import gcode as gc
from foamcut.sim import bounds, segments, total_seconds


def test_segments_split_towers_and_time():
    prog = gc.Program.parse("G21\nG90\nG0 X10 U5\nG1 X20 Y5 U15 V2 F600\nG93\nG1 X30 U25 F120\n")
    segs = segments(prog, rapid_feed=750.0)
    assert len(segs) == 3
    assert segs[0].rapid and not segs[0].wire_on
    assert segs[0].t1_end == (10.0, 0.0) and segs[0].t2_end == (5.0, 0.0)
    assert segs[1].t1_start == (10.0, 0.0) and segs[1].t1_end == (20.0, 5.0)
    assert segs[1].t2_end == (15.0, 2.0)
    # G94: 4D length / feed; G93: 60 / F seconds
    assert segs[1].seconds == pytest.approx(((10**2 + 5**2 + 10**2 + 2**2) ** 0.5) / 600 * 60)
    assert segs[2].seconds == pytest.approx(0.5)
    assert total_seconds(segs) == pytest.approx(segs[0].seconds + segs[1].seconds + 0.5)


def test_bounds_include_origin_and_both_towers():
    prog = gc.Program.parse("G1 F300\nG1 X-5 Y30 U40 V-2\n")
    b1, b2 = bounds(segments(prog))
    assert b1 == (-5.0, 0.0, 0.0, 30.0)
    assert b2 == (0.0, 40.0, -2.0, 0.0)


def test_real_wing_program_simulates():
    from pathlib import Path
    text = (Path(__file__).resolve().parents[2] / "gcode" / "120_20_400_r.nc").read_text()
    segs = segments(gc.Program.parse(text))
    assert len(segs) > 100
    assert segs[0].rapid                      # G0 to the entry point
    assert all(not s.rapid for s in segs[1:-1])
