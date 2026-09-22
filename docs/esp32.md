# ESP32 vor dem Board: Programme ohne PC schneiden

Stand 2026-09-22, geschrieben ohne ESP32 in der Hand – gegen die
ESP3D‑3.x‑Dokumentation (esp3d.io) und den GT2560‑Schaltplan. Auftrag
(Valentin, 2026-09-21): „ESP32 kommuniziert über serielle mit dem GT2560, nimmt
die Aufträge von der Software und schneidet sie. Die Aufträge bleiben auf dem
ESP32 und können später auch ohne PC geschnitten werden. Die webbasierte SW
listet die Aufträge auf und sagt zu jedem, wie groß der Block sein soll und wo
er liegen soll.“ Abschnitt „Beim ersten Kontakt prüfen“ nennt, was am echten
Gerät noch zu verifizieren ist.

## Was wo läuft

| Teil | Aufgabe | Quelle |
|---|---|---|
| grbl‑Mega‑5X auf dem GT2560, Variante **UART1** | schneidet wie bisher; hört auf D18/D19 statt auf USB | `firmware/grbl5x`, `SERIAL=esp ./build.sh` |
| **ESP3D 3.x** auf einem ESP32‑DevKit | WLAN, Dateiablage im Flash, Streaming an grbl, Web‑Oberfläche, TCP‑Brücke (Port 23) | esp3d.io, fertig |
| `esp32/foamcut.html` im ESP‑Flash | Programmliste mit Block/Lage/Tisch/Laufzeit, Start/Pause/Abbruch | dieses Repo |
| `foamcut` auf dem PC | erzeugt Programme (Zeile 2: `; foamcut-job …`), lädt sie hoch (`foamcut esp put`), kann über `--port tcp://foamcut.local` weiter live fahren | dieses Repo |

Ohne PC heißt: **vorhandene Programme erneut schneiden.** Entwerfen (Flügel,
Formen, Kontur, Scheiben, Schachteln) bleibt am PC.

## Hardware

Ein ESP32‑DevKitC (WROOM‑32, 4 MB Flash) reicht; der Flash hält Dutzende
Programme (eine .nc hat 10–50 kB). SD‑Slot nur, wenn es hunderte werden.

### Verdrahtung – EXP1 des GT2560

grbl‑Mega‑5X hängt fest auf UART0, und UART0 ist beim GT2560 der USB‑Chip.
Die Variante `SERIAL=esp` verlegt grbl auf **UART1 = D18 (TX1) / D19 (RX1)**;
beide liegen auf dem LCD‑Stecker **EXP1**, Pin 1 und 2 (im Marlin‑Pinfile
`pins_GT2560_REV_A.h`: `EXP1_01_PIN 18 // TX1 / BEEPER`, `EXP1_02_PIN 19 //
RX1 / ENC`). EXP1 führt auch 5 V und GND (Pin 9/10 – am Stecker prüfen,
Aufdruck oder Multimeter).

```
GT2560 EXP1                      ESP32 DevKitC
Pin 1  D18 TX1 (5 V)  ──[2k2]──┬──  GPIO16 (RX2)
                             [3k3]
                               └──  GND
Pin 2  D19 RX1        ◄────────────  GPIO17 (TX2)      (3,3 V reicht dem Mega: V_IH = 3,0 V)
Pin 9/10  GND, +5 V   ───────────►  GND, 5V/VIN   (RepRapDiscount-Belegung: 9 = GND, 10 = +5 V; am Stecker pruefen)
```

- Spannungsteiler 2k2/3k3 am Mega‑TX: 5 V → 3,0 V, die ESP32‑Eingänge sind
  nicht 5‑V‑fest.
- ESP‑TX (3,3 V) direkt an RX1: über der Mega‑Schwelle von 3,0 V, knapp,
  aber gängige Praxis; wer sicher gehen will, nimmt einen Pegelwandler.
- Massen verbinden, kurze Leitungen (< 30 cm), 115200 Baud.
- USB des GT2560 danach nur noch für den Bootloader (Flashen); grbl meldet
  sich dort nicht mehr. Zurück zur USB‑Variante: `./build.sh flash`.

### Endschalter ohne PC

Der Schutz „Endschalter gedrückt während der Fahrt = Stopp“ sitzt heute im
Python‑Worker. Ohne PC gibt es ihn nur, wenn grbl ihn selbst hat:
`HW_LIMITS=1` beim Bauen (`ENABLE_RAMPS_HW_LIMITS`, Polling im
Stepper‑Interrupt, weil kein GT2560‑Endschaltereingang einen
Pin‑Change‑Interrupt hat) und dann `$21=1`. Kostet etwas maximale Schrittrate
– nach dem Umstellen die `MAX_STEP_HZ`‑Grenze (20 kHz, `machine.py`) mit
einem schnellen Eilgang nachprüfen. `$21` gehört danach in
`config/grbl_settings_foamcut.txt`.

## Firmware bauen und flashen

```bash
cd firmware/grbl5x
SERIAL=esp HW_LIMITS=1 ./build.sh          # -> vendor/grbl-esp.hex
SERIAL=esp HW_LIMITS=1 ./build.sh flash    # ueber USB flashen (Bootloader bleibt)
```

`configure.py` benennt dafür in `serial.c` die UART0‑Register in UART1 um
(`UDR0→UDR1`, `UCSR0A/B`, `UBRR0H/L`, `U2X0`, `RXEN0`, `TXEN0`, `RXCIE0`,
`UDRIE0`) und setzt die Interrupt‑Vektoren `USART1_RX_vect` /
`USART1_UDRE_vect` in `cpu_map_gt2560.h`. Die USB‑Variante bleibt
byte‑identisch (geprüft am 2026-09-22 gegen das geflashte `grbl.hex`).

## ESP3D einrichten

1. ESP3D 3.x für den ESP32 flashen (esp3d.io → „ESP3D 3.0“, Web‑Installer
   oder PlatformIO), Ziel‑Firmware **GRBL**.
2. Beim ersten Start spannt ESP3D ein WLAN auf; dort das eigene WLAN
   eintragen, Hostname **foamcut** (dann `foamcut.local`), serielle
   Geschwindigkeit **115200**, Telnet/TCP‑Brücke aktivieren (Port 23).
3. ESP3D‑WebUI aufrufen, Konsole: `$$` muss die grbl‑Settings zeigen. Dann
   `config/grbl_settings_foamcut.txt` einmal per PC einspielen:
   `foamcut --port tcp://foamcut.local settings apply config/grbl_settings_foamcut.txt`.
4. `esp32/foamcut.html` über die ESP3D‑Oberfläche (Dateien / Filesystem) in
   das Flash‑Wurzelverzeichnis laden; Seite: `http://foamcut.local/foamcut.html`.
   Aufs Handy als Lesezeichen.

## Betrieb

- Programm am PC erzeugen (jede Seite → „G‑Code speichern…“), dann
  `foamcut esp put gcode/teil.nc` (oder Upload in der ESP3D‑Oberfläche).
- Auf `foamcut.html`: Liste zeigt je Programm **Block L×H×B, Rückseite X,
  Tisch Y, Wurzelturm, Laufzeit, Schlittenweg** – alles aus Zeile 2 der Datei
  (`; foamcut-job block=… x=… y=… root=… time=… travel=…`). Programm
  antippen → Start (mit Rückfrage), Pause / Weiter / Abbruch, Fortschritt
  alle 2 s.
- Heizleistung: Programme tragen `M3 S<wert>` aus `machine.json`
  (`wire_power`); mit `wire_power = 0` steht `S1` im Programm und der Draht
  bleibt kalt, weil hier kein PC den Schieberwert einsetzt. Vor dem Upload
  also **Heizleistung auf der Maschinenseite setzen**.
- Live vom PC über den ESP: `foamcut gui` mit Port `tcp://foamcut.local`
  oder `foamcut --port tcp://foamcut.local run …`. Beim Verbinden wird das
  Board nicht resettet (anders als über USB), grbl behält die Position.
- CLI ohne Browser: `foamcut esp ls | put | start NAME | status | pause |
  resume | abort` (`--host` für einen anderen Namen/IP).

## Beim ersten Kontakt prüfen

Alles unten ist aus der Dokumentation abgeleitet; die Stellen im Code sind
klein und leicht anzupassen.

1. **Dateiliste**: `GET /files?path=/` liefert JSON mit `files[]` (`name`,
   `size`). Code: `esp.py::list_files`, `foamcut.html::loadList`.
2. **Dateiinhalt per URL**: `GET /<name>` muss die .nc aus dem Flash‑Wurzel­
   verzeichnis liefern (ESP3D bedient das Web‑Wurzelverzeichnis aus /FS).
   Falls nicht: Datei über `/files?path=/&action=…` oder `[ESP720]` lesen.
3. **Upload‑Formular**: `POST /files`, Felder `path`, `<name>S` (Größe),
   `myfiles` (Datei) – so sendet die ESP3D‑WebUI. Code: `esp.py::upload`.
4. **Start**: `/command?cmd=[ESP700]/<name>`; Zustand `[ESP701]json=yes`
   (`status`, `total`, `processed`); Steuern `[ESP701]action=PAUSE|RESUME|ABORT`.
5. **Telnet‑Brücke** auf Port 23 antwortet zeilenweise ohne Echo; sonst in
   `link.py::TcpLink` das Echo filtern.
6. **Authentifizierung** in ESP3D aus lassen (sonst `pwd=` an jedes Kommando).
7. **grbl‑Banner** über TCP: `connect()` schickt Ctrl‑X, wenn kein Banner
   wartet – ESP3D reicht das Byte 0x18 durch? Wenn nicht, `[ESP…]`‑Alternativen
   prüfen oder das GUI‑„Reset“ über die ESP3D‑Konsole machen.

## Offen / später

- Raspberry Pi Zero 2 W statt ESP32, falls auch das Entwerfen aufs Gerät soll
  (Python‑Host, Browser‑GUI) – anderer Umfang, andere Nachteile (Boot, SD).
- Heizleistung im Programm variabel (`wire_power_max`, Heizsperre), sobald 24 V
  am Board sind.
