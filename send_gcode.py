#!/usr/bin/env python3
"""Send G-code to the GT2560 (Marlin) over USB serial at 115200 baud.

Usage:
  ./send_gcode.py                       # interactive console
  ./send_gcode.py "G1 X10 F2000" "M114" # send one or more commands
"""
import sys
import time
import serial

PORT = '/dev/ttyUSB0'
BAUD = 115200


def send(s, cmd):
    s.reset_input_buffer()
    s.write((cmd + '\n').encode())
    time.sleep(0.4)
    out = s.read(s.in_waiting or 4096).decode(errors='replace').strip()
    print(f">>> {cmd}")
    if out:
        print(out)


def main():
    s = serial.Serial(PORT, BAUD, timeout=0.3)
    time.sleep(1.5)  # let the board settle after reset
    s.read(s.in_waiting or 4096)  # drain boot banner

    if len(sys.argv) > 1:
        for c in sys.argv[1:]:
            send(s, c)
    else:
        print("GT2560 G-code console (type a command, or 'quit'/'exit').")
        print("Tip: start with M17 to energize the motors.")
        while True:
            try:
                line = input("gcode> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not line:
                continue
            if line.lower() in ('quit', 'exit'):
                break
            send(s, line)
    s.close()


if __name__ == '__main__':
    main()
