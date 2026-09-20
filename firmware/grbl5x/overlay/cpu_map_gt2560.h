/*
  cpu_map_gt2560.h - Geeetech GT2560 Rev.A / Rev.A+ pin map for grbl-Mega-5X,
  wired as a 4 axis XYUV hot wire foam cutter.

  Axis assignment (board silkscreen slot -> foam cutter axis):
      X  slot -> X   left tower, horizontal
      Y  slot -> Y   left tower, vertical
      Z  slot -> U   right tower, horizontal
      E0 slot -> V   right tower, vertical
      E1 slot -> unused (spare driver)

  This file is included from grbl/cpu_map.h when CPU_MAP_2560_GT2560 is
  defined in config.h. See docs/gt2560_pinout.md for the reasoning behind the
  non obvious choices (limit switch on EXP2, hot wire on timer 3).
*/

#ifndef cpu_map_gt2560_h
#define cpu_map_gt2560_h

#include "nuts_bolts.h"

// Serial port interrupt vectors
#define SERIAL_RX   USART0_RX_vect
#define SERIAL_UDRE USART0_UDRE_vect

// Port / pin indirection helpers
#define DDR(port) DDR##port
#define _DDR(port) DDR(port)
#define PORT(port) PORT##port
#define _PORT(port) PORT(port)
#define PIN(pin) PIN##pin
#define _PIN(pin) PIN(pin)

// ----------------------------------------------------------------- STEP ----
// X  D25 = PA3   Y  D31 = PC6   U(Z) D37 = PC0   V(E0) D43 = PL6
#define STEP_PORT_0 A
#define STEP_PORT_1 C
#define STEP_PORT_2 C
#if N_AXIS > 3
  #define STEP_PORT_3 L
#endif
#define STEP_BIT_0 3   // X step  - D25
#define STEP_BIT_1 6   // Y step  - D31
#define STEP_BIT_2 0   // U step  - D37 (board Z slot)
#if N_AXIS > 3
  #define STEP_BIT_3 6 // V step  - D43 (board E0 slot)
#endif
#define _STEP_BIT(i) STEP_BIT_##i
#define STEP_BIT(i) _STEP_BIT(i)
#define STEP_DDR(i) _DDR(STEP_PORT_##i)
#define _STEP_PORT(i) _PORT(STEP_PORT_##i)
#define STEP_PORT(i) _STEP_PORT(i)
#define STEP_PIN(i) _PIN(STEP_PORT_##i)

// ------------------------------------------------------------ DIRECTION ----
// X  D23 = PA1   Y  D33 = PC4   U(Z) D39 = PG2   V(E0) D45 = PL4
#define DIRECTION_PORT_0 A
#define DIRECTION_PORT_1 C
#define DIRECTION_PORT_2 G
#if N_AXIS > 3
  #define DIRECTION_PORT_3 L
#endif
#define DIRECTION_BIT_0 1   // X dir - D23
#define DIRECTION_BIT_1 4   // Y dir - D33
#define DIRECTION_BIT_2 2   // U dir - D39
#if N_AXIS > 3
  #define DIRECTION_BIT_3 4 // V dir - D45
#endif
#define _DIRECTION_BIT(i) DIRECTION_BIT_##i
#define DIRECTION_BIT(i) _DIRECTION_BIT(i)
#define DIRECTION_DDR(i) _DDR(DIRECTION_PORT_##i)
#define _DIRECTION_PORT(i) _PORT(DIRECTION_PORT_##i)
#define DIRECTION_PORT(i) _DIRECTION_PORT(i)
#define DIRECTION_PIN(i) _PIN(DIRECTION_PORT_##i)

// --------------------------------------------------------------- ENABLE ----
// X  D27 = PA5   Y  D29 = PA7   U(Z) D35 = PC2   V(E0) D41 = PG0
#define STEPPER_DISABLE_PORT_0 A
#define STEPPER_DISABLE_PORT_1 A
#define STEPPER_DISABLE_PORT_2 C
#if N_AXIS > 3
  #define STEPPER_DISABLE_PORT_3 G
#endif
#define STEPPER_DISABLE_BIT_0 5   // X enable - D27
#define STEPPER_DISABLE_BIT_1 7   // Y enable - D29
#define STEPPER_DISABLE_BIT_2 2   // U enable - D35
#if N_AXIS > 3
  #define STEPPER_DISABLE_BIT_3 0 // V enable - D41
#endif
#define STEPPER_DISABLE_BIT(i) STEPPER_DISABLE_BIT_##i
#define STEPPER_DISABLE_DDR(i) _DDR(STEPPER_DISABLE_PORT_##i)
#define STEPPER_DISABLE_PORT(i) _PORT(STEPPER_DISABLE_PORT_##i)
#define STEPPER_DISABLE_PIN(i) _PIN(STEPPER_DISABLE_PORT_##i)

// ------------------------------------------------------------ LIMIT MIN ----
// The GT2560 has three endstop connector pairs (X/Y/Z), i.e. six inputs, but
// this machine has four axes. The four switches (all at the negative end,
// wired 2026-09-18) sit on the X and Y connector pairs, MIN and MAX each -
// conveniently all on PORTA:
//   X -> X-MIN (D22)   Y -> X-MAX (D24)   U -> Y-MIN (D26)   V -> Y-MAX (D28)
#define MIN_LIMIT_PORT_0 A
#define MIN_LIMIT_PORT_1 A
#define MIN_LIMIT_PORT_2 A
#if N_AXIS > 3
  #define MIN_LIMIT_PORT_3 A
#endif
#define MIN_LIMIT_BIT_0 0   // X min - D22 (X-MIN connector)
#define MIN_LIMIT_BIT_1 2   // Y min - D24 (X-MAX connector)
#define MIN_LIMIT_BIT_2 4   // U min - D26 (Y-MIN connector)
#if N_AXIS > 3
  #define MIN_LIMIT_BIT_3 6 // V min - D28 (Y-MAX connector)
#endif
#define _MIN_LIMIT_BIT(i) MIN_LIMIT_BIT_##i
#define MIN_LIMIT_BIT(i) _MIN_LIMIT_BIT(i)
#define MIN_LIMIT_DDR(i) _DDR(MIN_LIMIT_PORT_##i)
#define MIN_LIMIT_PORT(i) _PORT(MIN_LIMIT_PORT_##i)
#define MIN_LIMIT_PIN(i) _PIN(MIN_LIMIT_PORT_##i)

// ------------------------------------------------------------ LIMIT MAX ----
// Only relevant with LIMITS_TWO_SWITCHES_ON_AXES enabled; nothing is wired
// there. The remaining inputs are the Z pair, EXP2 pin 7 and EXP2 pin 5. All
// inputs are pulled up internally, so an unwired input reads "not triggered".
#define MAX_LIMIT_PORT_0 C
#define MAX_LIMIT_PORT_1 C
#define MAX_LIMIT_PORT_2 D
#if N_AXIS > 3
  #define MAX_LIMIT_PORT_3 G
#endif
#define MAX_LIMIT_BIT_0 7   // X max - D30 (Z-MIN connector)   - not fitted
#define MAX_LIMIT_BIT_1 5   // Y max - D32 (Z-MAX connector)   - not fitted
#define MAX_LIMIT_BIT_2 7   // U max - D38 (EXP2-7, SD detect) - not fitted
#if N_AXIS > 3
  #define MAX_LIMIT_BIT_3 1 // V max - D40 (EXP2-5)            - not fitted
#endif
#define _MAX_LIMIT_BIT(i) MAX_LIMIT_BIT_##i
#define MAX_LIMIT_BIT(i) _MAX_LIMIT_BIT(i)
#define MAX_LIMIT_DDR(i) _DDR(MAX_LIMIT_PORT_##i)
#define MAX_LIMIT_PORT(i) _PORT(MAX_LIMIT_PORT_##i)
#define MAX_LIMIT_PIN(i) _PIN(MAX_LIMIT_PORT_##i)

// None of the GT2560 endstop inputs sit on a pin change interrupt capable
// port (PORTA and PORTC have no PCINT on the ATmega2560), so hard limits can
// only be polled from the stepper ISR. Enable ENABLE_RAMPS_HW_LIMITS in
// config.h if you want $21=1 to actually do something.

// -------------------------------------------------------------- HOT WIRE ---
// M3/M5 + S value drive the wire. SPINDLE_ENABLE is the HEATER_0 MOSFET (D2),
// intended for an optional contactor or a second, hard on/off power path.
// The PWM itself is on HEATER_1 (D3) - see the timer 3 block further down.
#define SPINDLE_ENABLE_DDR      DDRE
#define SPINDLE_ENABLE_PORT     PORTE
#define SPINDLE_ENABLE_BIT      4  // D2  - HEATER_0 MOSFET
#define SPINDLE_DIRECTION_DDR   DDRE
#define SPINDLE_DIRECTION_PORT  PORTE
#define SPINDLE_DIRECTION_BIT   3  // D5  - EXP1-7, unused by a hot wire

// ---------------------------------------------------------------- COOLANT --
// M8 switches the board cooling fan. The GT2560 driver MOSFETs and the A4988s
// get hot with four axes energised, so this is a genuinely useful output.
#define COOLANT_FLOOD_DDR   DDRH
#define COOLANT_FLOOD_PORT  PORTH
#define COOLANT_FLOOD_BIT   4  // D7 - FAN output
#define COOLANT_MIST_DDR    DDRB
#define COOLANT_MIST_PORT   PORTB
#define COOLANT_MIST_BIT    5  // D11 - EXP header / servo, spare

// ------------------------------------------------- M62-M65 digital output --
#define DIGITAL_OUTPUT_DDR_0  DDRL
#define DIGITAL_OUTPUT_PORT_0 PORTL
#define DIGITAL_OUTPUT_BIT_0  7  // D42 - EXP2-3
#define DIGITAL_OUTPUT_DDR_1  DDRL
#define DIGITAL_OUTPUT_PORT_1 PORTL
#define DIGITAL_OUTPUT_BIT_1  5  // D44
#define DIGITAL_OUTPUT_DDR_2  DDRL
#define DIGITAL_OUTPUT_PORT_2 PORTL
#define DIGITAL_OUTPUT_BIT_2  3  // D46
#define DIGITAL_OUTPUT_DDR_3  DDRB
#define DIGITAL_OUTPUT_PORT_3 PORTB
#define DIGITAL_OUTPUT_BIT_3  6  // D12

// ---------------------------------------------------------------- CONTROL --
// Reset / feed hold / cycle start / safety door. Grbl needs these on one pin
// change interrupt capable port that carries no other inputs; on the GT2560
// only PORTK (A8..A15) qualifies. A8/A9/A10 carry the thermistor dividers, so
// the free bits are A11..A15. They are not on a connector - solder to the MCU
// pads or leave them unwired, in which case the internal pull-ups keep all
// four signals inactive.
#define CONTROL_DDR       DDRK
#define CONTROL_PIN       PINK
#define CONTROL_PORT      PORTK
#define CONTROL_RESET_BIT         3  // A11
#define CONTROL_FEED_HOLD_BIT     4  // A12
#define CONTROL_CYCLE_START_BIT   5  // A13
#define CONTROL_SAFETY_DOOR_BIT   6  // A14
#define CONTROL_INT       PCIE2
#define CONTROL_INT_vect  PCINT2_vect
#define CONTROL_PCMSK     PCMSK2
#define CONTROL_MASK      ((1<<CONTROL_RESET_BIT)|(1<<CONTROL_FEED_HOLD_BIT)|(1<<CONTROL_CYCLE_START_BIT)|(1<<CONTROL_SAFETY_DOOR_BIT))

// ------------------------------------------------------------------ PROBE --
#define PROBE_DDR       DDRK
#define PROBE_PIN       PINK
#define PROBE_PORT      PORTK
#define PROBE_BIT       7  // A15
#define PROBE_MASK      (1<<PROBE_BIT)

// -------------------------------------------------------- HOT WIRE PWM ----
// D3 = PE5 = OC3C. Timer 3 is the only 16 bit timer the GT2560 routes to a
// power MOSFET that grbl does not already use (timer 0 = step pulse reset,
// timer 1 = stepper). 16 MHz / 8 / 256 = 7.8 kHz, comfortably above audible
// and slow enough for the on board MOSFET gate drive.
// grbl-Mega-5X always builds with a variable spindle output.

  #define SPINDLE_PWM_MAX_VALUE     255.0
  #ifndef SPINDLE_PWM_MIN_VALUE
    #define SPINDLE_PWM_MIN_VALUE   1
  #endif
  #define SPINDLE_PWM_OFF_VALUE     0
  #define SPINDLE_PWM_RANGE         (SPINDLE_PWM_MAX_VALUE-SPINDLE_PWM_MIN_VALUE)

  #define SPINDLE_TCCRA_REGISTER    TCCR3A
  #define SPINDLE_TCCRB_REGISTER    TCCR3B
  #define SPINDLE_OCR_REGISTER      OCR3C
  #define SPINDLE_COMB_BIT          COM3C1

  // 1/8 prescaler, 8-bit fast PWM with ICR3 as TOP (WGM3 = 14)
  #define SPINDLE_TCCRA_INIT_MASK (1<<WGM31)
  #define SPINDLE_TCCRB_INIT_MASK ((1<<WGM32) | (1<<WGM33) | (1<<CS31))
  #define SPINDLE_OCRA_REGISTER   ICR3
  #define SPINDLE_OCRA_TOP_VALUE  0xFF

  #define SPINDLE_PWM_DDR   DDRE
  #define SPINDLE_PWM_PORT  PORTE
  #define SPINDLE_PWM_BIT   5  // D3 - HEATER_1 MOSFET


#endif // cpu_map_gt2560_h
