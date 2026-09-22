# GT2560 pinout for a 4 axis XYUV hot wire cutter

**The GT2560 is not RAMPS pin compatible.** A RAMPS sketch flashed onto a
GT2560 toggles pins that are not connected to the drivers, so nothing moves and
nothing complains. The simplest correct Arduino sketch is
`gt2560_motortest/`; the full self test is `firmware/hwtest/`. Every number
below comes from the Geeetech Rev.A schematic
by way of Marlin's `pins_GT2560_REV_A.h`, and both firmwares in this repo are
checked against each other by `host/tests/test_pinmap.py`.

| | RAMPS 1.4 | GT2560 Rev.A |
|---|---|---|
| X STEP | D54 (A0) | **D25** |
| X DIR  | D55 (A1) | **D23** |
| X EN   | D38      | **D27** |

## Axis assignment

The machine has two independent towers. Their four axes map onto the board's
five driver slots like this:

| axis | tower | slot | STEP | DIR | EN | MIN limit (fitted) | MAX limit (free) |
|------|-------|------|------|-----|----|--------------------|------------------|
| X | left, horizontal  | X  | D25 / PA3 | D23 / PA1 | D27 / PA5 | D22 / PA0, **X-MIN** connector | D30 / PC7 (Z-MIN) |
| Y | left, vertical    | Y  | D31 / PC6 | D33 / PC4 | D29 / PA7 | D24 / PA2, **X-MAX** connector | D32 / PC5 (Z-MAX) |
| U | right, horizontal | Z  | D37 / PC0 | D39 / PG2 | D35 / PC2 | D26 / PA4, **Y-MIN** connector | D38 / PD7 (EXP2-7) |
| V | right, vertical   | E0 | D43 / PL6 | D45 / PL4 | D41 / PG0 | D28 / PA6, **Y-MAX** connector | D40 / PG1 (EXP2-5) |

The four switches (normally closed, between S and GND, all at the negative end
of their axis) were wired to the X and Y connector pairs on 2026-09-18 and the
pin map follows that: every limit input sits on PORTA.

**EXP1 pins 1/2 are D18/D19 = TX1/RX1 (UART1).** That is where an ESP32
running ESP3D talks to grbl when the firmware is built with `SERIAL=esp`,
see `docs/esp32.md`.

The E1 slot is free. Keep a spare A4988 in it: when one driver dies you can
move a motor over and change four lines instead of waiting for a delivery.

## Outputs

| function | pin | notes |
|---|---|---|
| hot wire PWM, `M3 S…` | D3 / PE5 | HEATER_1 MOSFET, OC3C |
| hot wire hard enable, `M3`/`M5` | D2 / PE4 | HEATER_0 MOSFET, for a contactor |
| board fan, `M8`/`M9` | D7 / PH4 | FAN output |
| spindle direction (unused) | D5 / PE3 | |
| probe | D69 / PK7 | |

### Why the hot wire is on D3 and not on the bed MOSFET

The bed output (D4 / PG5) is the beefiest MOSFET on the board and the obvious
choice, but D4 is OC0B — **timer 0, which grbl uses for the step pulse reset
interrupt**. Taking it over for PWM breaks step generation. The heater outputs
D2 and D3 are on timer 3, which grbl leaves alone, so D3 gets the wire.

That MOSFET is sized for a hotend, roughly 40 W at 12 V. **A metre of 26 AWG
nichrome wants far more than that.** For anything beyond a short wire, use D3
as the gate signal for an external MOSFET or an adjustable DC-DC converter and
keep the wire current off the board entirely. The GT2560 in the reference
project died from exactly this class of thermal abuse.

## Two things the GT2560 cannot do

**No pin change interrupt on any endstop input.** The endstop pins live on
PORTA and PORTC, and on the ATmega2560 only PORTB, PE0, PORTJ and PORTK have
pin change interrupts. grbl's hard limit ISR therefore cannot be wired up.
grbl-Mega-5X's fallback is `ENABLE_RAMPS_HW_LIMITS`, which polls the switches
inside the stepper interrupt; it is left off in `config.h` and costs some
maximum step rate when you turn it on. Homing (`$H`) polls the switches
directly and works either way.

**Only three endstop connector pairs for four axes.** With one switch per axis
the X and Y pairs (MIN and MAX each) cover all four; the Z pair, EXP2 pin 7
(D38, SD detect) and EXP2 pin 5 (D40) stay free for optional far-end switches.
All limit inputs are internally pulled up, so an unwired input reads "not
triggered".

## Control inputs (reset / feed hold / cycle start / door)

grbl wants these four on one pin change capable port that carries no other
inputs. On a GT2560 that leaves only PORTK, and A8..A10 there are the thermistor
dividers, so the map uses **A11..A14** and the probe uses A15. None of these are
on a connector — you would have to solder to the MCU pads. Left unwired the
internal pull-ups keep all four inactive, which is the intended default.

## GT2560 V3 / V4

Different board, different pins — the V3 swaps X and Z and moves the endstops.
`firmware/hwtest` handles it (`pio run -e v3`); the grbl `cpu_map_gt2560.h` is
Rev.A only. Check `Marlin/Marlin/src/pins/mega/pins_GT2560_V3.h` and adapt if
that is what you have.
