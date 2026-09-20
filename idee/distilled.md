# Flugzeugbaukasten – Destillat der ChatGPT-Diskussionen

Extrakt aus den 8 Chats des ChatGPT-Projekts „Flugzeugbaukasten“ (März/April 2026,
Export in `idee/chat_*.html`). Alles hier sind **Hinweise und Ideen aus der
Planungsphase** – Flügelmaße, Blöcke, Materialien sind frei wählbar; fest ist nur
die Maschine (XYUV-Schaumschneider, X/U 220 mm, Y/V 100 mm, Turmabstand 615 mm).

## 1. Projektidee (JuFo)

- Modularer **„Lego-Flugzeug“-Baukasten** für Jugend forscht (Sohn, 16/17 J.;
  ~1 Jahr, ~2 h/Woche). Ziel: Schüler erkunden schnell, *was fliegt und was nicht*.
- Austauschbar/verschiebbar: Flügelsegmente, Flügelposition (hoch/mittel/tief),
  Flügelwinkel/EWD, V-Form, Leitwerksgröße und -abstand, Schwerpunkt (Ballast),
  ggf. Doppeldecker-Abstand.
- **Segmente**: Positionierstifte (Holz/Kunststoff, leicht konisch) für exakte
  Ausrichtung + dünne wiederlösbare Montagestreifen / flache Neodym-Magnete
  (≤ 3×1 mm) auf den Endrippen. Alles ≤ 1–2 mm Aufbau.
- Verbinder/Halter 3D-gedruckt (PETG, 10–20 % Infill, 2–3 Perimeter, 0,8–1,2 mm
  Wand → 5–8 g je Teil, gesamt ~35–40 g); Holm (Balsa/Kiefer/Carbon) trägt die
  Kräfte, Druckteile nur Position/Kraftübertragung.
- Startvorrichtung: **Rampe 1–2 m**, Antrieb nur für die Rampe (Gummi oder
  drehzahlgeregelte Winde → reproduzierbare Starts, beliebiges
  Beschleunigungsprofil). Winde: bei 150 g, 4 m/s², Ø 100 mm Rad: M ≈ 0,03 N·m,
  n ≈ 760 U/min, v_ab ≈ 4 m/s nach 1 s.
- Tests indoor (Ventilator mit Strömungsgleichrichter, 1,5–2 m Abstand),
  Fliegen draußen auf Wiese/Hügel. Rechtlich: < 250 g, ohne Kamera → keine
  Registrierung; Minderjährige formal unter Aufsicht (Erwachsener in Sichtweite
  reicht, Eigenleistung für JuFo bleibt glaubwürdig).

## 2. Zielklasse des Modells

| Größe | Wert |
|---|---|
| Spannweite | 0,5–0,8 m (Start: **70 cm**) |
| Flügelfläche | 12–18 dm² (Start: **15 dm²**) |
| Gewicht | 120–200 g (Start: **150 g**) |
| Flächenbelastung | **8–12 g/dm²** (indoor eher 10–15) |
| Streckung AR = b²/S | 4–6 klein, 7–8 guter Anfängersegler |
| Mittlere Tiefe | ~20 cm (→ passt an die Maschine: max ~200 mm Profiltiefe) |
| Wurzel/Spitze | λ = c_tip/c_root ≈ 0,5–0,7 (Start 0,6); z. B. 26 → 16 cm |
| Profildicke | 8–12 % der Tiefe (Start 10 %); dicker = gutmütiger |
| Schwerpunkt | 28–33 % der Wurzeltiefe ab Nasenleiste (Start 30 %) |
| EWD | 2–3° (Flügel +3°, HLW 0°) |
| V-Form | 3–6° je Seite (Start 4–5°) |
| Höhenleitwerk | 20–30 % der Tragfläche (Start 25 %), V_h ≈ 0,5–0,7 |
| Seitenleitwerk | 8–12 % der Tragfläche (Start 10 %), V_v ≈ 0,03–0,05 |
| Rumpflänge | 0,7–0,85 × Spannweite (Start 0,8) |
| Leitwerkshebel | 2–3 × mittlere Tiefe |

Schnellstart-Prototyp: b 70 cm, S 15 dm², c 26/16 cm, Rumpf 55 cm, HLW 3,5 dm²,
SLW 1,5 dm², Dicke 2 cm, SP 8 cm ab Nasenleiste, V-Form 5°, EWD 2–3°.

## 3. Formeln (ASCII, Python-tauglich)

```
S        = b * c_mean                 # Fläche
c_mean   = (c_root + c_tip) / 2
lambda   = c_tip / c_root             # Zuspitzung
c_root   = 2*S / (b*(1+lambda))       # bei gegebener Fläche
AR       = b**2 / S                   # Streckung
L        = 0.5 * rho * v**2 * S * CL  # Auftrieb, rho ~1.2 kg/m^3, CL 0.5..1.2
v_ab     = sqrt(2*m*g / (rho*S*CL))   # Abhebegeschwindigkeit (~3-4 m/s bei 150 g/15 dm^2)
loading  = m_g / S_dm2                # Flächenbelastung g/dm^2
V_h      = S_h*l_h / (S*c_mean)       # Leitwerksvolumen horizontal
V_v      = S_v*l_v / (S*b)            # vertikal
EWD      = wing_angle - tail_angle
Re       = rho*v*l / mu               # <50k kritisch, 50-150k Modellflug
CL_platte ~ 2*pi*alpha                # flache Platte, alpha in rad
```

Merksätze: Schwerpunkt geht vor Gewicht („lieber leicht kopflastig“); Fläche
allein reicht nicht – Streckung zählt; lang & schmal = langsam & stabil
(Hebelarm!), kurz & breit = schnell & wendig; Anstellwinkel bestimmt *wie viel*
Kraft, Profil *wohin* sie zeigt.

## 4. Aerodynamik-Erkenntnisse für die Experimente

- **Gleiche Fläche, andere Form** (Rechteck/Trapez/Ellipse, Spannweite vs.
  Tiefe) ist ein sauberes Experiment: Fläche vorher messen, gleiches Material,
  dann vergleicht man wirklich die Form.
- Flache Platte erzeugt Auftrieb allein durch Anstellwinkel; bei < 100 g dominiert
  der Anstellwinkel (~65 %) gegenüber dem Profil (~35 %), weil Re klein ist.
  Trotzdem: leicht gewölbt + dünn ist gutmütiger als flach.
- Unterseite flach („oben rund, unten flach“, Clark-Y-artig) reicht für langsame
  Segler; symmetrisch nur für Kunstflug.
- Stark verjüngt (λ < 0,5) → Spitzen reißen zuerst ab → Trudeln. Abhilfe:
  Schränkung (Washout) an der Spitze.
- Vorwärtspfeilung: gutes Langsamflugverhalten, aber aeroelastisch kritisch –
  mit Schaum nicht sinnvoll.
- Ente (Canard): beide Flächen tragen, kein Abtrieb am Heck → weniger Ballast,
  Schwerpunkt bei ~15–25 % (Start 20 %) statt 25–33 %; empfindlicher einzustellen.
  Dreiflächer möglich, aber komplex.
- Doppeldecker: Fläche = Summe, Abstand 0,6–0,8 × Tiefe, stabil, mehr Widerstand.
- Indoor: zu leichte Modelle „tanzen“ in der Luft – etwas Masse (≥ 120–150 g) und
  mittlere Größe (50–80 cm) machen Versuche reproduzierbar.

## 5. Materialien

| Material | Dichte | Bemerkung |
|---|---|---|
| EPS (Styropor) | 15–30 kg/m³ (~20 g/dm³) | leicht, weich, körnig; Kerne |
| XPS (Styrodur, blau) | 30–45 | glatter, steifer, spröde; Kerne/Profile – **Heißdraht** |
| Depron (extrudierter PS-Schaum) | ~40, 3–6 mm | glatt, biegsam, formbar; Beplankung, Leitwerke |
| Dekor-Deckenplatten | wie feines EPS/XPS | Baumarkt-Hack, spröde, oft beschichtet |
| Karton A3 1,8 mm | 4,6 g/dm² | billig, Lasercutter, ungiftig, Holzleim; braucht Rippen/Holm → **Prototypen-Bausatz aus Karton** |
| Balsa | 100–220 kg/m³ | Holme, Nasen-/Endleisten, 0,6–1 mm Streifen auf Rippen |
| Kiefer / Carbon | 400–550 / 1500+ | Holme |
| PLA/PETG | 1200–1300 | nur Verbinder (~8× schwerer als Balsa) |

Kleben auf Schaum: Weißleim, PU, Styroporkleber, Heißkleber vorsichtig – **kein**
Sekundenkleber/Lösungsmittel. Bespannung: Schrumpffolie (KAVAN/Oracover) bügeln
90–110 °C, schrumpfen 120–150 °C – **Styropor wird ab 70–80 °C weich**, also nur
mit Balsa/Papier-Schutzschicht oder Heißluft aus 30–60 cm; Reihenfolge
Nasenleiste → Endleiste → Holme → Randbogen, dann Felder, beide Seiten
abwechselnd, von der Mitte nach außen. Alternativ Packpapier + verdünnter
Holzleim (1:1) als steife Haut (+10–30 % Gewicht, 2–5× steifer).

## 6. Werkzeuge / Software

- NACA-4-Profile per Formel (m p tt: Wölbung %, Lage /10, Dicke %); Empfehlung
  NACA 2412 (gutmütig), 3412 (Kompromiss), 4412 (Auftrieb); Python-Skript mit
  benannten Konstanten und SVG/DXF-Export (ezdxf/svgwrite) liegt im Chat
  „Flugzeugparameter und NACA“; OpenSCAD-Rippen per Formel ebenfalls möglich.
  → In `foamcut` durch `airfoil/*.dat` + Wing-Generator abgedeckt.
- Ultraschall-Cutter (NeoBlade, ~130 €): gut für Supports/Pappe/Depron, für
  Balsa unnötig, Klinge wird warm, für Kinder nur mit Aufsicht; nicht unter den
  Tisch montieren.

## 7. Konsequenzen für `foamcut`

- Flügeltiefe ≤ 200 mm, Panel ≤ ~450 mm je Schnitt → Segmentschnitte sind der
  Normalfall; Segment-/Stiftlöcher-Workflow hat Vorrang.
- Formfamilien gleicher Fläche (Rechteck/Trapez/Ellipse-Approximation) als
  Generatoroption wären für die Experimente direkt nützlich.
- Flache Platte / dünne Profile (8–10 %) und Schränkung müssen sauber
  schneidbar sein (Kerf, Apex-Warnung bei starker Verjüngung).
- Aufspannung: Block liegt auf dem (höhen-/breitenverstellbaren) Tisch; die
  Software liefert je Schnitt Mindestblock, zulässigen Tischhöhenbereich und
  maximale Tischausdehnung (Stand 2026-09-17 umgesetzt).
