# Profilkoordinaten

295 Profile im Selig-Format (`.dat`: Name in Zeile 1, dann x/y-Paare von der
Hinterkante über die Oberseite zur Nase und über die Unterseite zurück,
Sehne = 1.0), geladen am 2026-09-13 von

    https://swarfer.co.za/rc/foils/coord.php

Das ist der Spiegel der UIUC Airfoil Coordinates Database, auf den auch das
4AxisFoamCutter-Projekt verweist. Hinweis von dort: nicht alle Profile taugen
im Modellmaßstab — manche sind für manntragende Flugzeuge gerechnet
(Stichwort Reynoldszahl).

Neu laden:

    grep -oE "href='coord/[^']+\.dat'" <(curl -sL https://swarfer.co.za/rc/foils/coord.php) \
      | sed "s|href='|https://swarfer.co.za/rc/foils/|; s|'$||" \
      | xargs -P 4 -I{} curl -sS -f -L -O "{}"
