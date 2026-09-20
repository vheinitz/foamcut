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

## Sonstiges
- Karton-Prototypen-Bausatz (Lasercutter) parallel zum Schaumschneider.
- Winde mit Drehzahlregelung für reproduzierbare Rampenstarts.
