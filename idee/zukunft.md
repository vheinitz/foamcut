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
  Idee vom 2026-09-21 (Valentin), noch nicht bewertet.

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
- Empfehlung: Haltesteg für Formen ja (klein); „langsam für glatt“ als
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

## Sonstiges
- Karton-Prototypen-Bausatz (Lasercutter) parallel zum Schaumschneider.
- Winde mit Drehzahlregelung für reproduzierbare Rampenstarts.
