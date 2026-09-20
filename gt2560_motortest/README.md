# gt2560_motortest — einfacher Arduino-Sketch fuer 4 Motoren

Ein einzelnes `.ino`, das die vier Motoren eines Geeetech **GT2560 Rev.A /
Rev.A+** (ATmega2560) ohne jede Library testet. Es ist das "plain Arduino
IDE"-Gegenstueck zu `firmware/hwtest/` (PlatformIO, mit Endschaltern und
Heizdraht) — nur STEP/DIR/EN, ein Menue auf der seriellen Konsole, fertig.

Das GT2560 ist **nicht** RAMPS-pinkompatibel. Die Pins sind aus
`Marlin/Marlin/src/pins/mega/pins_GT2560_REV_A(_PLUS).h` uebernommen:

| Achse | Board-Slot | STEP | DIR | EN |
|---|---|---|---|---|
| X | X  | D25 | D23 | D27 |
| Y | Y  | D31 | D33 | D29 |
| Z | Z  | D37 | D39 | D35 |
| U | E0 | D43 | D45 | D41 |
| E | E1 | D49 | D47 | D48 |

`E` ist der Reserve-Slot E1 — praktisch, wenn z.B. der E0-Steckplatz kaputt
ist (Motor umstecken, `a e` auswaehlen, testen). Wenn Deine Achsen X/Y/U/V
heissen statt X/Y/Z/U, aendere nur die Buchstaben in `AXIS_NAME[5]`.

## Flashen

**Arduino IDE:** Board = *Arduino Mega or Mega 2560*, Processor =
*ATmega2560*, Port = der GT2560-USB-Port. Dann hochladen.

**arduino-cli:**

```bash
arduino-cli compile --fqbn arduino:avr:mega gt2560_motortest
arduino-cli upload  --fqbn arduino:avr:mega -p /dev/ttyUSB0 gt2560_motortest
arduino-cli monitor -p /dev/ttyUSB0 -c baudrate=115200
```

## Konsole (115200 Baud)

Ein Befehl pro Parameter, mehrere Befehle pro Zeile mit `;` getrennt —
z.B. `a x; m 16; +; -`. Zeilenende ist egal (LF, CR oder auch nur eine
Tipppause von ~1 s).

| Befehl | Wirkung |
|---|---|
| `a x` / `a y` / `a z` / `a u` / `a e` | Achse auswaehlen (auch `a 0`..`a 4` = Slot; `e` = E1) |
| `+` / `-` | ausgewaehlte Achse vor / zurueck. Ohne Zahl: 200 × Mikrostepping = 1 Umdrehung |
| `+ 3200` / `- 3200` | ... alternativ mit expliziter Schrittanzahl |
| `m 1` ... `m 64` | Mikrostepping (Jumper-Stellung angeben: 1, 2, 4, 8, 16, 32, 64) |
| `u 2000` | Schrittperiode in µs (HIGH+LOW, min 20; groesser = langsamer). Mit Anlauf-Rampe. |
| `b` | ausgewaehlte Achse hin und zurueck (optional `b 3200`) |
| `t` | alle 4 Achsen **nacheinander** testen (optional `t 3200`) |
| `g` | alle 4 Achsen **gleichzeitig** (optional `g 3200`) |
| `e 1` / `e 0` | Treiber aktivieren (Motoren fest) / freigeben |
| `?` | aktuelle Parameter anzeigen |
| `h` | Hilfe |

Beim ersten `+`/`-`/`b`/`t`/`g` werden die Treiber automatisch aktiviert.

## Mikrostepping ist Jumper-Sache

Bei A4988/DRV8825 (MS1/MS2/MS3) und TMC2209 (MS1/MS2) wird das
Mikrostepping durch die **Jumper unter dem jeweiligen Treiber-Steckplatz**
eingestellt — nicht per Software. `m 64` sagt dem Sketch nur, welche
Jumper-Stellung Du gesteckt hast, damit er weiss, dass eine Umdrehung
200 × 64 = 12800 Schritte sind.

**TMC2209** (MS-Jumper):

| MS1 | MS2 | Mikrostepping |
|---|---|---|
| offen | offen | 1/8 |
| zu    | offen | 1/32 |
| offen | zu    | 1/64 |
| zu    | zu    | 1/16 |

Dein Fall: **MS2 zu, MS1 offen → `m 64`**.

### Warum "schnell" trotzdem langsam wirkt

- Eine Umdrehung sind bei 1/64 **12800 Schritte** — viermal mehr als bei 1/16.
  Bei gleicher Schrittfrequenz dreht der Motor also viermal langsamer.
- Der Sketch faehrt jetzt mit **Anlauf-Rampe** los (startet langsam und
  beschleunigt). Ohne Rampe stallen die Motoren bei kleinen Perioden und
  drehen nur langsam/ruckelnd weiter.
- Unter ~200 µs Periode brauchst Du genug Treiberstrom, sonst stallen die
  Motoren beim Anlauf trotz Rampe.

Vor dem ersten Fahren den Treiberstrom einstellen: Trimmer des Treibers erst
herunterdrehen, bis der Motor stehen bleibt, dann wieder hoch, bis er sauber
laeuft — und nicht weiter. Ein Motor, der heiss wird, bekommt zu viel Strom.

Dreht ein Motor nur brummt aber nicht, siehe `docs/bringup.md` ("Motor
brummt, dreht aber nicht"): meist sind die Spulenpaare im Stecker verschraenkt.
