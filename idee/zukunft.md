# Wohin es hinausgeht – Notizen (nicht umgesetzt)

Stand 2026-09-17. Nur Ideen zum Festhalten; Reihenfolge ohne Priorität.

## Rumpf schneiden
- Rumpfsegmente als Schaumblöcke mit dem Draht schneiden (Seitenriss + Aufriss
  als zwei Schnitte, Block dazwischen wenden).
- Aufnahmen für Flügelposition (hoch/mittel/tief), Leitwerksabstand und
  Ballast im Rumpf gleich mit einplanen (Stiftlöcher/Nuten im Schnitt).

## Ruderwerke
- Höhen-/Seitenleitwerk als eigene Profile (symmetrisch, NACA 00xx) mit
  Rudertrennung; Leitwerksflächen aus den Faustregeln (HLW 25 %, SLW 10 % der
  Tragfläche) direkt aus der Flügelspezifikation ableiten.
- Ruderscharnier (Folienscharnier / V-Nut) als Schnittoption.

## Flügel gleicher Fläche, unterschiedlicher Form
- Formfamilie bei fester Fläche S und Spannweite b: Rechteck (λ=1),
  Trapez (λ 0,5–0,7), Ellipsen-Näherung (mehrere Trapezsegmente),
  Vorwärts-/Rückwärtspfeilung.
- Generator: Eingabe S, b, λ → c_root, c_tip; Ausgabe als Segmentliste, die die
  Maschine (≤ 200 mm Tiefe, ≤ ~450 mm Panel) einzeln schneiden kann.

## Segmentierungsplanung
- Automatische Aufteilung eines Flügels in Segmente nach Blocklänge/Verfahrweg,
  mit Stiftlöchern (Spar-Schnitt) an den Trennstellen und Nummerierung.
- Übersicht/Schnittplan (welches Segment aus welchem Block, welche Seite),
  Materialbedarf.

## 5. Achse: Heißnadel-Gantry
- Dünner Heißstift/Heißnadel zwischen den Türmen statt Draht, leicht abnehmbar
  (z. B. an zwei starken Magneten geklemmt) → Maschine wird zum XY-Gantry für
  Flächenschnitte: Öffnungen/Zwischenräume in Flügeln ausschneiden, danach mit
  Folie bespannen (Rippenflügel-Optik, Gewicht sparen).
- Softwareseitig: 2-Achs-Modus (X/Y oder X/U synchron), 2D-Kontur aus
  SVG/DXF, Nadel-Ein/Austauchen als Z-Ersatz (Vorschub-Pause/Draht aus).
- Firmware bleibt unverändert; nur Host-Seite.

## Steuerung ohne Rechner
- WLAN-fähiger Controller am GT2560 (ESP32 als seriell-WLAN-Brücke, sonst
  Raspberry Pi mit dem Host), damit die Maschine draußen ohne angeschlossenen
  Laptop läuft; Programme per Browser/Handy übertragen und starten.
  Idee vom 2026-09-21 (Valentin). Umgesetzt am 2026-09-22 als ESP32 + ESP3D:
  grbl-Variante UART1, `tcp://`-Verbindung, Job-Kopfzeile, Programmseite
  `esp32/foamcut.html`, CLI `foamcut esp` – siehe `docs/esp32.md`; Hardware
  noch nicht angeschlossen, Prüfliste dort.

## Schnittbreite abhängig von Geschwindigkeit (und Leistung, Schaum, Temperatur)
Idee vom 2026-09-21 (Valentin): „Wenn man die Kalibrierung mit einem
Styroportyp vorm Schneiden macht, mit unterschiedlicher Geschwindigkeit
schneidet und dann die Schnitte misst, kann man die Parameter approximiert
anwenden und in Erzeugung von G-Code berücksichtigen … da wo eine Seite viel
kleiner, fährt der Draht viel langsamer und Schnitt wird noch größer → Teilende
kleiner.“

Einschätzung (Claude, 2026-09-21):
- Physik: Kanalbreite wächst mit der Energie je Weg, grob `kerf ≈ a + b·P/v`.
  Beim Trapezflügel läuft die Endseite mit `v_tip = v_root · c_tip/c_root`
  (gleiche Zeit, kürzerer Umfang). Bei λ = 0,6 bekommt das Ende 1,67× Energie
  je mm; aus 1,0 mm Kerf werden dort erfahrungsgemäß eher 1,4–1,6 mm.
- Wirkung am JuFo-Flügel (Tiefe 160 mm, Dicke 10 % = 16 mm): Tiefe −0,5 mm
  (0,3 %, egal), Dicke −0,5 mm (3 %) – spürbar erst bei dünnen Profilen
  (≤ 8 %) oder starker Zuspitzung (λ < 0,5); dort wird auch die Endleiste
  fragil. Für Rechteckflügel und Formen mit gleich großen Seiten: nichts.
- Profis: ja, das gibt es. GMFC (Gilles Muller) rechnet den Kerf je Seite aus
  einer gemessenen Kerf-über-Geschwindigkeit-Tabelle; Jedicut hat Kerf je
  Seite; Industriemaschinen regeln eher den Drahtstrom mit der Bahngeschwindigkeit
  (konstante Energie je Weg). Letzteres hilft hier nicht: ein Draht, zwei
  Geschwindigkeiten – Leistung je Seite lässt sich nicht trennen, also bleibt
  nur die Geometriekorrektur je Seite.
- Umsetzung in foamcut ist klein: `_profile_mm()` nimmt den Kerf schon je
  Profil; nötig sind (1) Kalibrierschnitt: 2–3 gerade Schnitte bei v1, v2, v3
  (Freischnitt), Breiten messen, als `kerf_table` in machine.json, (2) im
  Generator Kerf je Seite aus `v_seite` interpoliert (linear in 1/v), (3) der
  Freischnitt-Dialog bekommt „Kalibrierung“. Grbl-seitig nichts.
- Empfehlung: erst machen, wenn ein Flügel mit λ < 0,6 oder ein dünnes
  Leitwerk gebraucht wird; bis dahin genügt der eine Kerf vom Maschinenblatt,
  gemessen bei der üblichen Geschwindigkeit.

## Langsam schneiden für glatte Oberfläche
Idee vom 2026-09-21 (Valentin): absichtlich langsamer fahren, damit die
Oberfläche länger schmilzt und glatter wird; G-Code soll das berücksichtigen
(größer schneiden) und Stege stehen lassen, damit das Teil nicht gleich absinkt.

Einschätzung (Claude, 2026-09-21):
- Begriff: Stehenbleibende Brücken heißen beim Schneiden „Haltestege“ (engl.
  tabs/bridges, wie beim Lasern); „Stützstrukturen“ sind 3D-Druck-Supports.
- Glatt wird XPS (Styrodur) durch langsam+heiß tatsächlich (verglaste Haut);
  EPS (Styropor) wird eher grubig, weil die Kugeln unterschiedlich schmelzen.
  Kosten: größerer Kerf, dünne Endleiste schmilzt weg, mehr Drahtdurchhang.
  „Größer schneiden“ ist dabei kein eigenes Feature, sondern genau der Kerf
  bei dieser Geschwindigkeit (siehe oben) – die Vorschubfelder gibt es schon.
- Haltestege: beim Flügel unnötig – der Kern liegt bis zum Schluss auf dem
  unteren Rest, der obere Rest liegt auf dem Kern, nichts fällt auf den Draht.
  Nützlich bei Formen mit Loch (Innenstück fällt beim Schließen der Kontur)
  und bei gestapelten Teilen. Umsetzung billig: Schließsegment um `steg` mm
  verkürzen, Steg per Hand brechen; ein Feld in [schnitt] der Form.
- Empfehlung: Haltesteg für Formen ja (klein; umgesetzt 2026-09-22 als `tab` für Kontur/Scheibe prismatisch); „langsam für glatt“ als
  Einstellung nur mit dem kalibrierten Kerf sinnvoll, sonst wird das Teil
  bloß kleiner. Für die Baukastenflügel eher Papier/Folie als Haut
  (distilled.md §5) statt Verglasung.

Messung 2026-09-22 (Valentin, Draht 15 Ω/m an 12 V, HEATER_1): 100 mm/min
statt 300 macht die Oberfläche **nicht** glatter, „eher rauer. Besser schnell
mit viel Power.“ Die Einschätzung oben („langsam+heiß = verglaste Haut“)
gilt für diesen Schaum/Draht also nicht; die Idee „langsam für glatt“ ist
damit vom Tisch. Was bleibt: Haltestege für Formen mit Loch.

## Freie 2D-Konturen und Scheiben aus STL
Idee vom 2026-09-23 (Valentin): „beliebige 2D-Formen ausschneiden: Buchstaben,
Freihandformen, Silhouetten, Skizzen … Achsen wie Gantry, Dicke egal … Eigener
Editor oder fertigen nutzen und als G-Code/Vektorgrafik importieren?“ Dazu
„3D-Form in Scheiben definierter Dicke schneiden und beliebige n-te schneiden
… riesige Flügel oder Rümpfe aus Styroporscheiben, Holzleisten, Bespannfolie
… Form als STL importierbar, hier definierbar wie dick die Scheibe und welche
gerade geschnitten werden muss.“

Einschätzung (Claude, 2026-09-23):
- Kein eigener Editor. Inkscape kann Text→Pfad, Bitmap nachzeichnen
  (Silhouetten, Skizzen), Freihand, Boolesche Operationen — das sind Jahre.
  Schnittstelle ist **SVG**, nicht G-Code: Laser-/Fräs-Postprozessoren heben
  zwischen Konturen ab (Laser aus, Eilgang) — ein Draht kann nicht abheben.
  Das Drahtspezifische bleibt bei foamcut: Kerf, Ein-/Auslauf von der
  Blockrückseite, Schlitz zu Innenkonturen (A, B, O), Reihenfolge, kein
  Eintauchen. Das Ring-Modell (shape.py) macht genau das schon für ein Loch.
- Neues Modell `.contour`: SVG-Datei + Maßstab + Lage im Block + Einlaufseite
  + Spiegeln; Pfade (Linien, Béziers) auf Polylinien plätten, Kerf-Offset,
  Lage prüfen gegen Verfahrweg (X ≤ 218, Y ≤ 130). Beide Seiten gleich
  (X=U, Y=V) — das ist ein Parallelschnitt (prismatisch), kein „Gantry“;
  Gantry bezeichnet die Bauform, nicht die Betriebsart. Aufwand ~1–2 Sitzungen,
  kleiner SVG-Parser reicht (kein svgpathtools nötig).
- STL-Scheiben: trimesh schneidet ein Netz mit Ebenen z = k·t und liefert die
  Konturen je Schnitt. Zwei Wege: (a) 3-Achs-Denke: Scheibe k = Kontur bei
  z_k, prismatisch → Treppen. (b) **Unser Vorteil**: Scheibe k als Loft
  zwischen Kontur z_k (Turm 1) und z_{k+1} (Turm 2) — wie das Formen-Modell
  mit Seiten A/B (`by_angle` für die Punktzuordnung) → glatte Regelfläche
  statt Treppen, ein Rumpf aus 40-mm-Scheiben sieht rund aus. Block = Scheibe,
  Konturen ≤ 218 × 130 mm je Seite; Rumpfquerschnitte passen, Flügel weiter
  mit dem Flügelmodell (das ist schon der Loft). Holmleisten brauchen Nuten
  vom Rand aus (Draht kann kein Loch ohne Schlitz), Position in allen Scheiben
  gleich, plus Nummerierung im G-Code-Kopf. Abhängigkeit trimesh + numpy.
  Aufwand ~2–3 Sitzungen nach dem SVG-Import, weil er dessen Kontur-Pipeline
  wiederverwendet.
- Reihenfolge: erst SVG-Kontur (prismatisch, sofort nützlich), dann
  STL-Scheiben mit Loft.
- Umgesetzt am 2026-09-22: Seiten „Kontur“ (`.contour`, SVG) und „Scheiben“
  (`.slices`, STL, verlaufend oder prismatisch), beide auch im Schachteln.
  Holmnut (oben/unten, Körperkoordinaten) und Haltesteg (`tab`, Kontur und
  prismatische Scheibe) ebenfalls drin.

## Drahttemperatur messen und regeln
Idee vom 2026-09-23 (Valentin): „die Temperatur zu messen und zu regeln.
Wäre es machbar? Wie bringe ich T-Sensor an dem Draht an?“

Einschätzung (Claude, 2026-09-23):
- **Kein Sensor am Draht.** Ein Thermoelement oder NTC am Draht hätte Masse
  und Zug am 0,3-mm-Draht, liegt auf Drahtpotential (PWM in den ADC), wandert
  durch den Schaum und misst ohnehin nur seine Kontaktstelle. IR-Sensor
  (MLX90614) scheidet aus, weil der Messfleck bei 5 cm rund 1 cm groß ist und
  der dünne Draht darin untergeht – gemessen wird der Hintergrund.
- **Der Draht ist sein eigener Sensor:** R = U/I, und R steigt mit der
  Temperatur. Haken: NiCr 80/20 hat absichtlich einen winzigen
  Temperaturkoeffizienten, α ≈ 1e-4/K → +250 K bringen nur +2,5 % Widerstand.
  Mit einem 16-bit-Strom-/Spannungsmesser (INA226 + Shunt 0,05 Ω) sind das
  noch ~20 K Auflösung: für eine Regelung genug, für eine Temperaturanzeige
  in °C zu wenig. **Edelstahldraht (V2A, ~10 Ω/m) hätte α ≈ 1e-3/K**, also
  zehnmal mehr Signal – wer ernsthaft regeln will, wechselt das Material.
- **Regelziel:** nicht Temperatur, sondern (1) konstante Leistung U·I statt
  konstanter PWM – gleicht Netzteil- und Spannungsschwankungen aus; (2)
  konstanter Widerstand = konstante Drahttemperatur (Prinzip der
  Hitzdraht-Anemometrie, CTA). Stufe 2 gleicht genau das aus, was draußen
  stört: Kühlung durch Wind, Kälte und durch den Schaum selbst.
- **Wo anschließen:** nicht am Draht, sondern in der Zuleitung – Shunt in
  Reihe, INA226 misst Drahtspannung und Strom. Am GT2560 liegt I2C auf
  EXP1 Pin 4/6 (D20 SDA, D21 SCL), aber grbl liest es nicht; die drei
  Thermistoreingänge (A8/A9/A10, TEMP_0/1/BED) sind frei, aber ebenfalls für
  grbl unsichtbar – nur mit Firmware-Umbau nutzbar (für die
  *Umgebungs*temperatur ein NTC dort wäre die einfachste Variante).
- **Eleganteste Bauform: ein eigenes kleines Drahtregler-Modul** (ESP32-C3
  oder Arduino Nano, MOSFET, Shunt, INA226) zwischen Netzteil und Draht. Es
  liest **den PWM-Tastgrad von D3 als Sollwert** und regelt die tatsächliche
  Leistung bzw. den Widerstand darauf. Dann ändert sich an foamcut, grbl und
  ESP3D *nichts*: `M3 S…` bleibt die Schnittstelle, nur die Bedeutung wird
  von „Tastgrad“ zu „Sollwert“. Materialkosten ~20 €.
- **Sicherheit:** Regler braucht Strombegrenzung, Watchdog (PWM weg → aus),
  Drahtbruch-Erkennung (I = 0 bei P > 0) und eine Obergrenze, sonst glüht der
  Draht bei einem Regelfehler durch; bei 24 V sind an 10 Ω 58 W möglich.
- Empfehlung: Stufe 1 (konstante Leistung) bringt schon den größten Teil und
  ist in einem Abend gebaut; Stufe 2 lohnt sich, wenn die Maschine wirklich
  draußen steht. Zusammen mit dem geschwindigkeitsabhängigen Kerf (oben) wäre
  das die Kombination, die reproduzierbare Schnitte ergibt.

### Nachtrag 2026-09-23: echter Fühler an den Thermistoreingängen
Einwand Valentin: „gt2560 hat doch bereits 3 Eingänge für T-Sensoren … T-Sensor
würde ich am Draht binden und mit einem gut isolierten Keramik- oder
Asbestgehäuse umschließen.“ Der Einwand trifft – die Widerstandsmessung ist bei
NiCr tatsächlich zu grob, ein echter Fühler ist genauer. Bedingungen:

- **Kein Asbest.** In der EU seit 2005 verboten, Bearbeiten und Verbauen ist
  strafbar und die Fasern sind krebserzeugend. Ersatz mit gleicher Wirkung:
  Keramikfaser (biolöslich, „Superwool“), Glasfaserschlauch (bis ~550 °C),
  Glimmerplättchen, Keramik-Perlrohr (Thermoelementperlen).
- **Der Fühler darf nicht in den Schnitt.** Alles am Draht ist dicker als der
  Draht und würde durch den Schaum pflügen. Also **außerhalb der Blockbreite**
  binden, dicht am Turm mit dem festen Draht; er fährt mit dem Draht mit und
  bleibt in der Luft. Kapsel leicht halten (< 2 g), sonst hängt der Draht
  durch – das Gewicht am anderen Turm spannt ihn nur.
- **Fühler:** PT1000 (Dünnschicht, bis 500 °C) passt am besten – die
  GT2560-Eingänge TEMP_0/1/BED (A8/A9/A10, PORTK Bit 0–2, in unserer grbl-Map
  frei) haben schon 4,7-kΩ-Pull-ups nach 5 V. PT1000 an diesem Teiler: 0,88 V
  bei 0 °C, 1,72 V bei 400 °C → am 10-bit-ADC ~2,3 K je Schritt. Der
  Drucker-NTC (100 kΩ) ist nur bis 300 °C spezifiziert und oben sehr flach;
  ein Typ-K-Element bräuchte einen Verstärker (AD8495, 5 mV/°C – ebenfalls
  analog anschließbar) oder SPI (MAX31855, dann kein Thermistoreingang).
  Zwischen Draht und Fühler ein Glimmerplättchen: der Draht führt PWM.
- **Was der Fühler misst:** die Temperatur der Kapsel neben dem Turm, nicht
  die der Schnittstelle. Absolut ist das falsch, als *Regelgröße* aber
  reproduzierbar; die Zeitkonstante der Kapsel liegt bei Sekunden, was für
  langsame Störungen (Kälte, Wind, Netzteil) genau reicht.
- **Kette bis zur Regelung, ohne neue Hardware am Rechner:**
  1. grbl liest den ADC und hängt ein Feld an den Statusbericht, z. B.
     `|WT:212.5` (report.c, dort wo `|FS:` entsteht; ~40 Zeilen plus ein
     `$`-Setting für Fühlertyp und Kalibrierung).
  2. `parse_status()` im Host nimmt das Feld auf, die Maschinenseite zeigt es.
  3. Der Host regelt mit den Echtzeitbytes für den Spindel-Override:
     0x9C/0x9D = ±1 %, 0x9A/0x9B = ±10 %, 0x99 = zurück auf 100 %. Die wirken
     **mitten im laufenden Programm**, ohne G-Code zu ändern – ein PI-Regler
     mit ein paar Prozent je Sekunde genügt. `sys.spindle_speed` im Bericht
     zeigt, was tatsächlich eingestellt ist.
  Damit bleibt die Architektur wie sie ist: Firmware misst, Host regelt.
- Aufwand: Fühler + Kapsel ~15 €, Firmware ein Abend, Host ein Abend. Der
  Weg ist dem Regler-Modul (oben) vorzuziehen, solange der PC mitläuft; ohne
  PC (ESP32) müsste der Regler in die Firmware wandern.

### Nachtrag 2026-09-23: selbst gewickelter Fühler?
Idee Valentin: „ich wickele mit Stück solchen Drahts mein Heissdraht, davor
jedoch erhitze ich es und stecke ins Wasser. Es oxidiert und bildet eine
Stromisolierung. Welchen Draht nehme ich dafür mit großer R-Schwankung von T?“

- **Oxid als Isolator trägt nicht.** Abschrecken im Wasser sprengt den Zunder
  eher ab (Thermoschock), als dass es eine haftende Schicht bildet; Eisen- und
  Chromoxid sind bei Temperatur Halbleiter, keine Isolatoren. Die einzige
  brauchbare Eigenoxidschicht ist **Al₂O₃ auf Kanthal (FeCrAl)**, und die
  entsteht durch langsames Glühen bei ~1000 °C, nicht durch Abschrecken – beim
  Wickeln reißt sie an den Kontaktstellen trotzdem auf. Schon einige kΩ
  Nebenschluss zum PWM-Draht machen die Messung unbrauchbar. Also **Glimmer
  oder Glasfaserschlauch** zwischen Fühler und Draht, das ist dünn, sicher und
  kostet nichts.
- **Größter Temperaturkoeffizient bei bezahlbaren Drähten:** Nickel
  α ≈ 6000 ppm/K (+150 % bei +250 K!), Platin 3850 ppm/K (+96 %), Eisen
  ~5000, Kupfer 4300 (oxidiert über 200 °C), Edelstahl nur 1000 ppm/K.
  Nickeldraht wäre also das Material der Wahl – **aber**:
- **Die Länge killt die Idee.** Der Thermistoreingang des GT2560 hat einen
  4,7-kΩ-Pull-up; gut auflösbar ist ein Fühler von ~1 kΩ. Dafür bräuchte man
  bei 0,05 mm Nickeldraht **28 m** (Platin 18 m, Edelstahl 2,7 m). Ein paar
  Zentimeter um den Draht gewickelt ergeben 1–2 Ω, und 1–2 Ω an 4,7 kΩ sind
  im ADC nicht zu sehen – das bräuchte Brücke, Konstantstromquelle und
  Verstärker. Genau deshalb sind PT1000 **Dünnschicht-Mäander** und keine
  Wickel: 1 kΩ auf 2 × 2 mm.
- **Fazit:** Der Gedanke ist richtig (Draht als RTD), nur die Bauform nicht.
  Ein Dünnschicht-PT1000 (bis 500 °C, glaspassiviert = schon isoliert, ~2 €)
  bringt dasselbe in klein, linear und direkt am vorhandenen Eingang. Wer
  trotzdem selbst wickeln will: Nickeldraht **in Reihe zur Messbrücke**, nicht
  an den Thermistoreingang.

**Einkaufsliste, falls es gebaut wird** (Stand 2026-09-23, nichts davon
gekauft oder geprüft):
- Fühler: „PT1000 Dünnschicht Klasse B, 2 × 2 mm, bis 500 °C“ oder ein
  PT100-Sensorelement M222. **Keine keramischen PTC/Kaltleiter** (MZ-, PTC-
  „Posistor“-Serien): die sind Heizelemente und Schutzwiderstände, ihre
  Kennlinie ist bis zur Curie-Temperatur flach und springt dann um Zehnerpotenzen
  – damit lässt sich nichts messen. Prüfkriterium beim Kauf: gibt das
  Datenblatt eine R(T)-Tabelle oder -Kurve über den ganzen Bereich an?
- Isolation Draht ↔ Fühler: Glimmerplättchen (Mica) 0,1 mm.
- Kapsel: Keramikfaserpapier/-band (biolöslich, „Superwool“) 1–2 mm, außen
  Glasgewebeband (bis ~550 °C; selbstklebende Varianten halten nur ~200 °C,
  also besser binden statt kleben).
- Binden: Glasseidezwirn oder 0,2-mm-Edelstahldraht.
- Zuleitung: Keramik-Perlrohr oder Glasfaserschlauch über die Litzen,
  verdrillt und weg von der Heizdrahtleitung; ganze Kapsel unter 2 g.

## Sonstiges
- Karton-Prototypen-Bausatz (Lasercutter) parallel zum Schaumschneider.
- Winde mit Drehzahlregelung für reproduzierbare Rampenstarts.
