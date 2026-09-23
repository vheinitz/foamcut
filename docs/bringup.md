# Bring-up checklist

Work down the list. Each step either passes or tells you exactly which wire to
look at. Do not skip ahead: the point of the order is that a failure at step *n*
can only have been caused by something in step *n*.

Before anything else: **fit a fan blowing on the board.** Four energised
A4988s plus the wire MOSFET is more heat than a GT2560 shrugs off, and `$1=255`
in the shipped settings keeps the motors powered continuously so the wire does
not sag while hot.

---

## 1. Toolchain

```bash
make deps          # pip install -e host, pytest
make test          # 77 offline tests, no hardware needed
```

`make test` also cross-checks the two firmwares' pin maps against each other.
If it fails, fix that before flashing anything.

## 2. Firmware: grbl, und nur grbl

Auf dem Board läuft **grbl-Mega-5X**, dauerhaft. Es gibt keinen Grund, die
Firmware zu wechseln: Jog je Achse, alle vier zugleich, Draht-PWM und der
Endschalter-Zustand (`Pn:` im Statusreport, in der GUI oben rechts) sind
alle in grbl.

`firmware/hwtest/` bleibt als Notnagel für den Fall, dass ein Board
*überhaupt kein* Lebenszeichen gibt — bit-gebangte Pins ohne Planer, um
Pinbelegung und Treiber zu isolieren. Für diese Maschine ist das erledigt;
im normalen Betrieb nicht flashen (`foamcut hwtest`/`bounce` brauchen es).

## 3. Flash grbl

Einmalig, und nach jedem Firmware-Update:

```bash
make grbl-flash
foamcut probe                  # muss "Grbl 1.2i" melden
foamcut settings apply config/grbl_settings_foamcut.txt
```

## 4. Maschine vermessen: `foamcut setup`

Ohne Endschalter kann grbl weder referenzieren noch den Verfahrweg kennen.
`foamcut setup` macht beides von Hand und speichert das Ergebnis in
`config/machine.json` und in grbls Settings. Fünf Phasen, jede auch einzeln
(`foamcut setup --phases scale`):

| Phase | was passiert | schreibt |
|---|---|---|
| `mapping` | jede grbl-Achse fährt 5 mm, du sagst, was sich bewegt hat. Stimmt die Steckplatz-Belegung nicht, sagt es dir, welche Stecker zu tauschen sind, und bricht ab | — |
| `scale` | jede Achse fährt 20 mm, du misst nach | `$100..$103` |
| `direction` | jede Achse fährt +20 mm, du sagst ob "vorne" bzw. "oben". Falsch → Bit in `$3`, nicht umverdrahten | `$3` |
| `reference` | Tastatur-Jog in die Referenzecke (X, U hinten; Y, V unten), Enter → Arbeitsnull | `G10 L20 P1` |
| `travel` | jede Achse per Tastatur bis kurz vors andere Ende, Enter → Verfahrweg | `$130..$133`, `machine.json` |

Tastatur im Jog: `a/d` X, `s/w` Y, `j/l` U, `k/i` V, `1`..`4` Schrittweite
0.1 / 1 / 10 / 50 mm, Enter fertig, `q` Abbruch.

**Oder alles mit der Maus:** `foamcut gui` (Qt). Seiten: **Maschine**
(Verbindung, Jog-Pads beider Türme, Referenz, Verfahrweg, Endschalter,
Heizdraht und Schnittwerte; hier stehen auch Turmabstand und der Turm mit
dem festen Draht – sie gelten für alle Entwürfe), **Flügel** (Schritte links, Zeichnung rechts live, Warnungen
inline, letzte Werte gemerkt; Schritt *Block* nennt Mindestblock und
Tischhöhe/-ausdehnung; Schritt *Holme* hat sechs Zeilen für Nuten und
Löcher, je eine Leiste, jede mit einem Häkchen ein- und ausschaltbar (der Wert
bleibt stehen; in der Datei steht dann „aus“ davor). Format für Flügel **und**
Formen gleich: **`<Winkel> [innen] <b>x<h>`** – Winkel in Grad um die Mitte des
Querschnitts, im Uhrzeigersinn von oben (0 oben, 90 vorn/Nase, 180 unten, 270
hinten). Die Nut sitzt dort, wo dieser Strahl die Kontur verlässt, und steht
senkrecht auf ihr, damit die Leiste flach darin liegt; `innen` macht daraus ein
geschlossenes Loch 1 mm unter der Haut (nur im Körper, der Draht käme nicht
hinein). Ist das Teil länger als der Turmabstand, ist das **kein Fehler mehr**,
sondern ein Hinweis: am Stück lässt es sich nicht schneiden, als Körper (STL)
und für Rippen aus Scheiben ist es weiter brauchbar.
Ältere Flügeldateien mit `30% oben 6x4` (Lage ab Nasenleiste) werden
weiter gelesen – das ist der Weg, wenn es auf eine bestimmte Profiltiefe
ankommt. „STL speichern…“ gibt den Flügel als
Körper aus, mit Nuten und Löchern: daraus lassen sich später auf der Seite
*Scheiben* Rippen schneiden und mit Holzleisten zu einem größeren Flügel
zusammensetzen. Innenlöcher schneidet der Draht am Flügel selbst nicht – er
käme nicht hinein, ohne ihn aufzuschlitzen), **Formen** (freie Querschnitte je Seite, Scheibe
oder Ring – Rumpfsegmente; Schritt *Holme* mit demselben Format wie beim
Flügel, „STL speichern…“ gibt auch hier den Körper aus), **Kontur** (SVG-Zeichnung aus Inkscape als
Parallelschnitt X=U/Y=V: Buchstaben, Silhouetten; Löcher über einen Schlitz
nach hinten, mehrere Teile nacheinander, Text vorher in Pfade umwandeln),
**Scheiben** (STL-Körper in Scheiben einer Dicke; Scheiben „2,3,4“, „1-5“
oder „alle“ werden nebeneinander auf einer Schaumplatte der Scheibendicke
angeordnet (Platte Länge/Höhe, sonst Verfahrweg): Umrisse statt Rechtecke,
Vierteldrehungen erlaubt, kleinstes umschließendes Rechteck, Scheiben
2 × Schnittbreite + 0,5 mm auseinander; die Teile werden als **Kette**
geschnitten: ein Einlauf, dann je Teil ein Bogen, über den Steg zum Nachbarn
(entlang der Verbindung der Mittelpunkte), am Ende umkehren und auf dem
Rückweg den jeweils anderen Bogen – die Kanäle dazwischen werden zweimal
befahren, nicht neu geschnitten. Die Kette läuft von oben nach unten, also
kommt beim Rückweg das unterste Teil zuerst frei und der Draht fährt von ihm
weg. Wo ein Steg ein drittes Teil träfe (oder ein Haltesteg gesetzt ist),
fährt die Software wie bisher Teil für Teil von hinten an; Scheibenliste mit Enter bestätigen; der Draht
fährt zwischen ihnen um die schon geschnittenen herum; passen nicht alle, gibt es **ein
Programm je Platte** (`…_platte1.nc`, `_platte2.nc`): die Programmseite zeigt
nach dem Ende von Platte 1, welche Platte einzulegen ist, und lädt Platte 2
erst über „Nächste Platte laden…“ – dann wie immer Start; **verlaufend** ist der Normalfall: beide Türme
fahren unabhängig, die Scheibe bekommt ihre beiden echten Schnittflächen und
damit den Winkel eines konischen Rumpfs (Sehnenfehler je Scheibe im Ergebnis);
zerfällt ein Schnitt in mehrere Umrisse, wird jeder mit seinem Gegenstück
gepaart. **Prismatisch** (`verlaufend = nein`) ist der Rückfall, wenn die
beiden Flächen nicht zusammenpassen. Die Plattenlage entlang des Drahts kommt
von der Software (mittig zwischen den Türmen, so teilt sich der Schrägversatz
gleichmäßig auf beide Schlitten) oder aus dem Feld *Seite A ab Turm*;
Holmnut von oben/unten in Körperkoordinaten, also in jeder Scheibe an
derselben Stelle – Rümpfe und große Flügel aus Schaumscheiben auf Holmen;
Reiter „Objekt“ zeigt Zeichnung bzw. drehbaren Körper mit markierter Scheibe),
**Programm & Sim** (laden/umsetzen,
Turtle-Simulation beider Schlittenwege, Start/Pause/Stop). Beim Verbinden
gleicht die GUI alle grbl-Settings mit `config/` ab.

**Schachteln (mehrere Teile in einem Block):** Seite „Schachteln“ oder
`foamcut nest LISTE.batch`. Gespeicherte `.wing`/`.shape`/`.contour`/`.slices` in die Liste laden,
Reihenfolge = Schnittreihenfolge von oben nach unten (das letzte Teil liegt
auf dem Tisch). Die Teile werden in Y gestapelt, Abstand „gap“ dazwischen –
geprüft über die ganze Blockbreite, weil der Draht bei kürzeren Teilen hinter
deren Ende weiterschneidet. Haken „Paar“ an einem Flügel: zusätzlich das
Spiegelbild (in Spannrichtung umgedreht, Wurzel am Gewichtsturm) darüber,
dünnes Ende über dickem. Zwischen den Teilen fährt der Draht 5 mm hinter der
Blockrückseite (kein Schaum) senkrecht zum nächsten Einlauf, nie über
Geschnittenes. Ein Programm, ein `M3`. Die Liste lässt sich als `.batch`
speichern (`config/beispiel.batch`).

**Lauf live:** Während ein Programm läuft, zeigen die beiden Ansichten auf
„Programm & Sim“ die echte Position (rotes Fadenkreuz mit Koordinaten, aus den
Statusmeldungen 5×/s) und die tatsächlich gefahrene Spur (rosé); die geplante
Bahn füllt sich in Farbe, sobald grbl die Zeilen angenommen hat (bis ~16
Bewegungen voraus), der Rest liegt blass darunter. Die Spur bleibt nach dem
Ende stehen, bis das nächste Programm startet.

**Freischnitt (Maschine-Seite):** an eine Stelle joggen, Länge und Vorschub
eintippen, **vor / zurück / hoch / runter** (oder Winkel + „schräg“) — ein
gerader Schnitt ab der aktuellen Position, beide Türme gleich, optional „und
zurück“. Läuft als Programm (Pause/Stopp/Fortschritt), die Bereichsprüfung
rechnet ab der aktuellen Position. **Turm 2 versetzt U/V:** Turm 2 fährt
vorher (Draht kalt) um U nach vorn bzw. V nach oben, der Draht steht schräg
und der Schnitt wird eine schräge Ebene — U mit ↑/↓ ergibt eine Pfeilungs-
fläche (Winkel = atan U/Turmabstand), V mit →/← eine über die Spannweite
geneigte Fläche. Am Ende stellt sich der Draht wieder gerade. Eine V-Form-
Wurzelfläche (aus der Senkrechten gekippt) kann der Draht nicht.

**Kontrollschnitt nach Skalen-Änderung:** 100-mm-Freischnitt „und zurück“ in
eine Platte, an beiden Türmen nachmessen — beide Enden gleich lang, sonst
stimmen Schritte/mm (`$100..$103`) nicht. Gespiegelt und normal ergeben
denselben Umriss (nur kopfüber); Abweichungen zwischen beiden kommen von der
Maschine oder der Messstelle (ein Trapez ist alle 10 cm ~1 cm anders breit).

**Block und Tisch:** der Block liegt auf dem Tisch, seine Unterkante *ist*
`table_y`; nur waagerecht (Länge, Spannbereich) sind Block und Tisch getrennt.
Alte `.wing`/`.shape` mit `block_y` werden umgerechnet.

**U läuft mit 3200 Schritten/mm** (Treiber im Z-Slot steht auf 1/32,
Lineal-Test 16.09.): so steht es jetzt in `machine.json`; ein Rechteckflügel
wurde vorher als Trapez geschnitten, weil U nur halb so weit fuhr. Jumper auf
1/16 umstecken und `foamcut setup --phases scale --jog-mm 50 --axes U` gäbe U
wieder 750 mm/min statt 375.

**Nach jedem Einschalten:** `foamcut ref` oder in der GUI „Referenz hier setzen". grbl weiß nach einem Neustart nicht
mehr, wo es steht — die Referenzecke einmal anfahren, Enter, fertig. Danach
prüft `foamcut run` jedes Programm gegen den gespeicherten Verfahrweg und lehnt ab,
was darüber hinausfährt.

## 5. Sync und Schnitt

### Four axis synchronisation

```bash
foamcut check gcode/05_sync_diagonal.nc     # offline first
foamcut run   gcode/05_sync_diagonal.nc
```

Every move changes all four axes by different amounts. Both towers must start
and stop together. If one arrives late, it is losing steps: lower `$110..$113`
or raise the driver current.

### The wire

With the wire strung and tensioned but nothing to cut:

```bash
foamcut run gcode/03_wire_ramp.nc
```

Find the lowest `S` value that melts foam without the wire glowing red. With
`$30=255` the `S` value *is* the PWM count, so `S128` is 50 % duty.

### First cut

```bash
foamcut run gcode/01_square.nc      # prismatic block, both towers identical
foamcut run gcode/02_taper.nc       # tapered block, towers travel different distances
```

The taper is the test a 3 axis controller cannot pass. Measure both ends: left
should be 60 mm, right 30 mm, minus the kerf. The cut settings - feed,
wire power, warm-up and kerf (Schnittbreite) - are entered once on the
machine page (or `foamcut machine set --feed 300 --wire 180 --warmup 3
--kerf 1.2`); they live in `machine.json` and apply to wings, shapes, batches
and the free cut alike. `feed`, `wire`, `warmup`, `kerf` lines in old
`.wing`/`.shape` files are ignored.

Then set feed and wire power together — see "Feed rate and temperature" in the
[reference project's README](https://github.com/rahulsarchive/4AxisFoamCutter).
Faster feed needs a hotter wire; too slow at any temperature widens the kerf
because the foam keeps melting while the wire dawdles.

---

## Endschalter und Referenzfahrt

Vier Öffner (NC, zwischen S und GND), alle am negativen Ende (X/U hinten,
Y/V unten), verdrahtet am 18.09.2026: **X an X_MIN, Y an X_MAX, U an Y_MIN,
V an Y_MAX** — die GT2560 hat keinen vierten Endschalter-Stecker, die X/Y-
Paare decken alle vier ab (gt2560_pinout.md). Die Öffner-Umkehr ist in der
Firmware fest (`INVERT_MIN_LIMIT_PIN_MASK`); `$5` bleibt 0, weil grbl-Mega-5X
bei `$5=1` MIN- und MAX-Eingang verknüpft und die leeren MAX-Eingänge dann wie
gedrückt aussehen (ALARM:8 beim Homing).

Gelernt am 19.09.2026: `machine.json` hatte `invert_dir` für Y/V verloren,
der Abgleich schrieb `$3=0` — +Y fuhr nach unten, das Homing nach oben,
Kollision. `$3=10` ist Pflicht (Y und V invertiert); `foamcut settings dump`
zeigt es, der Abgleich beim Verbinden stellt es aus `machine.json` wieder her.

Dass vier Schalter nicht auf den Zehntelmillimeter fluchten und der Draht bei
"beide Türme am Schalter" nicht waagerecht hängt, ist eingeplant: die
Schalter liefern den **Maschinen-Nullpunkt**, der **Arbeitsnullpunkt** liegt
pro Achse um einen Versatz in + davon (G54). Alle Programme laufen im
Arbeitskoordinatensystem.

GUI → **Endschalter…**:

1. Schalterart (NO/NC), Pull-off, Geschwindigkeiten. Haken "Endschalter
   verwenden". **Schalterzustand lesen** und jeden Schalter von Hand drücken:
   es muss genau die richtige Achse erscheinen — das prüft Verdrahtung und
   NO/NC, bevor sich etwas bewegt.
2. **Referenzfahrt jetzt ($H)** — gedrückte Schalter werden erst 5 mm
   freigefahren, dann fahren alle vier Achsen langsam auf ihre Schalter,
   Pull-off 2 mm (bei 0 ist kein Schalter ausgelöst). Beim ersten Mal die
   Hand am Netzschalter: fährt eine Achse *vom* Schalter weg, stimmt ihre
   Richtung nicht (`$3`-Bit der Achse), grbl bricht nach 1,5× Länge ab.
   Beim Verbinden läuft die Referenzfahrt automatisch (`homing.auto`).
3. Versatz: alle Achsen im Hauptfenster joggen, bis sie stehen, wo Null sein
   soll (Draht waagerecht!), dann **Referenz hier setzen** — das speichert den
   Versatz ab Schalter für alle vier Achsen und setzt G54. (Im Dialog geht es
   auch je Achse mit **= aktuelle Position**.)
4. Je Achse **Länge ab Schalter** eintippen (nutzbarer Weg, nicht anfahren;
   die Suchfahrt läuft bis 1,5× dieser Länge, also nicht zu klein).
5. **Speichern & aufs Board** — `machine.json` + `$5 $20 $22 $23 $24 $25 $27
   $130..$133` + G54. Bleibt bis zur nächsten Kalibrierung.

Ab dann nach jedem Einschalten: grbl startet im Alarm, die GUI fährt die
Referenz automatisch und landet auf dem gespeicherten Arbeitsnull. Kein `$X`
mehr, kein Ecke anfahren. Softlimits sind aktiv: grbl lehnt Fahrten außerhalb
der Länge ab (error 15), zusätzlich zur Host-Prüfung in `foamcut check`/`run`.
Spricht während einer Fahrt trotzdem ein Schalter an, hält die GUI an,
setzt zurück und meldet es — dann stimmen Nullpunkt oder Länge nicht.

Achtung Kommandozeile: jedes Öffnen/Schließen des Ports setzt das Board zurück
(DTR), danach ist die Position wieder unbekannt. `foamcut home` allein bringt
also nichts Dauerhaftes; die GUI hält die Verbindung.

Kommandozeile: `foamcut homing set --enable --nc --offset V=1.5 --length X=160
Y=105 U=160 V=105`, `foamcut homing show`, `foamcut home`.

Die Phasen `reference` und `travel` von `foamcut setup` sind nur für Maschinen
ohne Schalter.

## Halber Weg auf einer Achse: Schritte/mm

Fährt eine Achse **bei jeder Geschwindigkeit gleich falsch** (z. B. nur den
halben Weg), stimmen die Schritte/mm nicht — fast immer, weil der Treiber in
einem anderen Mikroschritt läuft als angenommen (U war so: 1600 → 3200; Y/V
am 2026-09-23: 8704 → 17408). Sind die Fehler dagegen nur bei hohem Vorschub
da, verliert die Achse Schritte, dann ist die Schrittrate zu hoch.

```bash
foamcut machine set --steps Y=17408 --steps V=17408   # neu = alt * befohlen / gemessen
```

Der Wert landet in `machine.json` und beim nächsten Verbinden auf dem Board.
Achtung: doppelte Schritte/mm halbieren den möglichen Vorschub (20 kHz
Schrittbudget, `MAX_STEP_HZ`) — `machine set` sagt, worauf es kappt. Wer die
Geschwindigkeit behalten will, stellt stattdessen den Treiber zurück auf den
angenommenen Mikroschritt (Jumper MS1/MS2 unter dem Treiber) und lässt den
alten Wert stehen.

## The feed rate surprise

This build sets `N_AXIS_LINEAR = 4`, so grbl applies the feed rate to the
euclidean norm over **all four** axes. A move where both towers travel 100 mm
has a path length of 141 mm, so at `F300` each tower actually crosses the foam
at 212 mm/min, not 300. `foamcut check` reports this as a note on any file where it
happens. Account for it when you translate a cutting speed into an `F` word.

---

## Motor brummt, dreht aber nicht

Zuerst ausschliessen, dass es die Schrittfrequenz ist - der hwtest faehrt ohne
Rampe los, und ein knapp eingestellter Treiber verschluckt sich daran:

    foamcut bounce X --steps 3200 --step-us 2000 --no-guard   # 4,7 U/min

Dreht er langsam sauber, war es zu schnell: Vref hoch, dann wieder schneller.
Brummt er auch hier, ist es die Verdrahtung oder der Strom. Dass er ueberhaupt
brummt, ist dabei eine gute Nachricht - Enable, Step und Dir kommen am Treiber
an, die Pinbelegung stimmt also.

**Vref messen.** Multimeter an den Trimmer des A4988 gegen GND, Board bestromt,
Motor angeschlossen. Es gilt `Vref = I_soll * 8 * R_sense`; bei den ueblichen
0,1 Ohm sind das fuer 1,2 A rund 0,96 V. Nahe null heisst: der Motor bekommt
keinen Strom und brummt nur.

**Spulenpaare pruefen.** Vier Adern, zwei Spulen. Multimeter auf Ohm: genau
zwei Adernpaare haben ein paar Ohm zueinander, zwischen den Paaren misst du
unendlich. Diese Paare muessen im Stecker *nebeneinander* liegen, also Pin 1+2
eine Spule und Pin 3+4 die andere. Verschraenkt man sie (1+3 / 2+4), brummt der
Motor und dreht nicht - das ist der mit Abstand haeufigste Fall.

Ohne Multimeter: zwei Adern verdrillen und die Welle von Hand drehen. Wird sie
spuerbar schwergaengig, gehoeren die beiden zu einer Spule.

**Im Zeitlupentempo zusehen.** 160 Schritte bei 60 ms je Halbperiode sind
10 Vollschritte in gut 20 Sekunden - da siehst du jedem Schritt einzeln zu:

    foamcut bounce X --steps 160 --step-us 60000 --no-guard

Richtig verdrahtet rueckt die Welle sichtbar Schritt fuer Schritt weiter.
Verschraenkt pendelt sie nur hin und her.

---

## Board meldet sich nicht

Symptome, die zusammen auftreten und alle auf die *gleiche* Ursache zeigen:

* `ls /dev/ttyUSB*` zeigt den Port mal, mal nicht, und die Nummer wechselt
  (ttyUSB0 → ttyUSB1 → weg). In `lsusb` steigt die Device-Nummer bei jedem Mal.
* Das Board sendet nach einem DTR-Reset auf **keiner** Baudrate etwas
  (250000 / 115200 / 57600 alle 0 Bytes).
* `avrdude -c wiring` läuft in lauter `stk500v2_recv(): timeout`,
  `avrdude -c arduino` meldet `not in sync: resp=0x00`.

Das heißt: der CH340 (USB-Seriell-Wandler) bekommt Strom aus dem USB und meldet
sich, der ATmega2560 dahinter läuft nicht. Die Reihenfolge zum Prüfen:

1. **Netzteil an, Board-LEDs an?** Ohne Logikversorgung läuft nur der Wandler.
2. **USB-Kabel tauschen.** Ein Ladekabel ohne Datenadern oder ein zu langes /
   schlechtes Kabel lässt den CH340 genau so flattern. Direkt am Rechner
   anstecken, nicht über einen Hub.
3. **Alles abklemmen** — Motoren, Endschalter, Heizdraht — und nur USB plus
   Netzteil. Ein Kurzschluss an einem Treiber zieht die 5 V herunter und das
   Board bootet in einer Schleife.
4. **Reset-Taster** auf dem Board drücken und den Flash-Befehl im selben Moment
   starten, falls der Auto-Reset über DTR nicht verdrahtet ist.

Erst wenn `foamcut probe` eine Firmware-Zeile ausgibt, weitermachen.

    foamcut probe        # sagt, welcher Port da ist und welche Firmware antwortet
