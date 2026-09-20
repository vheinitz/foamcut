#!/usr/bin/env python3
"""Test one (or all) GT2560/Marlin axes: move N steps forward, pause 1 s, back.

Usage:
  ./test_axis.py X                 # X axis, 5000 steps (defaults)
  ./test_axis.py Y 2000            # Y axis, 2000 steps
  ./test_axis.py Z 5000 600        # Z axis, 5000 steps @ 600 mm/min
  ./test_axis.py E0 5000 1500      # E0 slot, 5000 steps @ 1500 mm/min
  ./test_axis.py E1 5000 1500      # E1 slot (selects extruder 1 first)
  ./test_axis.py ALL               # test all 5 axes in sequence
  ./test_axis.py X 5000 1200 80    # X, 5000 steps @1200 mm/min, 80 steps/mm

Arguments after the axis are optional, in this order:
  steps       number of motor steps (default 5000)
  feed        feedrate in mm/min (default 1200)
  spmm        steps per mm (default 80, matches the firmware M92 value)

The distance moved is  steps / steps_per_mm  millimetres.
"""
import argparse
import sys
import time
import serial

PORT = '/dev/ttyUSB0'
BAUD = 115200

AXES = ['X', 'Y', 'Z', 'E0', 'E1']


def send(s, cmd, wait=0.3):
    s.reset_input_buffer()
    s.write((cmd + '\n').encode())
    time.sleep(wait)
    return s.read(s.in_waiting or 4096).decode(errors='replace').strip()


def say(s, cmd, wait=0.3):
    out = send(s, cmd, wait)
    print(f">>> {cmd}")
    if out:
        print("   " + out)


def move_axis(s, axis, steps, feed, spmm):
    mm = steps / spmm
    move_time = mm * 60.0 / feed  # seconds per move
    wait = move_time + 1.0

    print(f"\n=== {axis}: {steps} steps = {mm:.3f} mm @ F{feed} ===")
    say(s, 'M17')                      # energize all steppers

    if axis in ('X', 'Y', 'Z'):
        say(s, 'G91')                  # relative positioning
        say(s, f'G1 {axis}{mm:.3f} F{feed}')
        time.sleep(wait)
        say(s, 'M114')                 # expect +N steps here
        say(s, 'G4 S1')                # 1 second dwell
        say(s, f'G1 {axis}-{mm:.3f} F{feed}')
        time.sleep(wait)
        say(s, 'M114')                 # expect back at 0
    else:                              # E0 / E1 extruder slots
        tool = '1' if axis == 'E1' else '0'
        say(s, f'T{tool}')             # select the extruder
        say(s, 'M83')                  # relative extrusion
        say(s, f'G1 E{mm:.3f} F{feed}')
        time.sleep(wait)
        say(s, 'M114')
        say(s, 'G4 S1')
        say(s, f'G1 E-{mm:.3f} F{feed}')
        time.sleep(wait)
        say(s, 'M114')
        say(s, 'T0')                   # back to extruder 0

    say(s, 'M84')                      # de-energize steppers


def main():
    ap = argparse.ArgumentParser(
        description='Test GT2560/Marlin axes with a forward/back step move.',
        epilog='Example: ./test_axis.py X 5000 1200 80',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument('axis', choices=AXES + ['ALL'], help='axis to test (or ALL)')
    ap.add_argument('steps', nargs='?', type=int, default=5000,
                    help='number of steps (default 5000)')
    ap.add_argument('feed', nargs='?', type=int, default=1200,
                    help='feedrate mm/min (default 1200)')
    ap.add_argument('spmm', nargs='?', type=float, default=80.0,
                    help='steps per mm (default 80)')
    args = ap.parse_args()

    try:
        s = serial.Serial(PORT, BAUD, timeout=0.3)
    except serial.SerialException as e:
        print(f"ERROR: cannot open {PORT}: {e}")
        sys.exit(1)

    time.sleep(1.5)
    s.read(s.in_waiting or 4096)  # drain boot banner

    targets = AXES if args.axis == 'ALL' else [args.axis]
    for i, a in enumerate(targets):
        move_axis(s, a, args.steps, args.feed, args.spmm)
        if i != len(targets) - 1:
            time.sleep(1.0)

    s.close()


if __name__ == '__main__':
    main()
