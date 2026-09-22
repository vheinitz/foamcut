#!/usr/bin/env bash
# Fetch grbl-Mega-5X, apply the foamcut GT2560 / XYUV overlay, build, optionally flash.
#
#   ./build.sh              fetch + configure + build  -> vendor/grbl.hex
#   ./build.sh flash        the above, then flash via /dev/ttyUSB0
#   PORT=/dev/ttyACM0 ./build.sh flash
#   SERIAL=esp ./build.sh   grbl on UART1 for an ESP32/ESP3D in front of the
#                           board -> vendor/grbl-esp.hex (USB port silent!)
#   HW_LIMITS=1 ./build.sh  hard limits compiled in ($21=1 usable)
#
# The upstream commit is pinned so a rebuild months from now produces the same
# firmware. Bump GRBL_REF deliberately, then re-run: configure.py verifies that
# every line it patches still looks the way it expects.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENDOR="$HERE/vendor"
GRBL_URL="https://github.com/fra589/grbl-Mega-5X.git"
GRBL_REF="${GRBL_REF:-edge}"   # upstream default branch (grbl-Mega-5X 1.2i)
PORT="${PORT:-/dev/ttyUSB0}"
SERIAL="${SERIAL:-usb}"          # usb | esp
HW_LIMITS="${HW_LIMITS:-0}"
CONFIG_ARGS=(--serial "$SERIAL")
[ "$HW_LIMITS" = "1" ] && CONFIG_ARGS+=(--hw-limits)
HEX="$VENDOR/grbl.hex"
[ "$SERIAL" = "esp" ] && HEX="$VENDOR/grbl-esp.hex"

if [ ! -d "$VENDOR/.git" ]; then
  echo "==> cloning grbl-Mega-5X ($GRBL_REF)"
  git clone --depth 1 --branch "$GRBL_REF" "$GRBL_URL" "$VENDOR"
else
  echo "==> using existing checkout in vendor/ (delete it to re-fetch)"
fi

echo "==> restoring pristine sources"
git -C "$VENDOR" checkout -- grbl
rm -f "$VENDOR/grbl/cpu_map_gt2560.h"

echo "==> applying foamcut configuration"
"$HERE/configure.py" "$VENDOR" "${CONFIG_ARGS[@]}"

echo "==> building"
make -C "$VENDOR" clean >/dev/null 2>&1 || true
mkdir -p "$VENDOR/build"
make -C "$VENDOR" -j"$(nproc)"

echo
avr-size --format=avr --mcu=atmega2560 "$VENDOR/build/main.elf" 2>/dev/null || true
[ "$HEX" != "$VENDOR/grbl.hex" ] && cp "$VENDOR/grbl.hex" "$HEX"
echo "==> firmware at $HEX"

if [ "${1:-}" = "flash" ]; then
  echo "==> flashing $PORT"
  avrdude -v -p atmega2560 -c wiring -P "$PORT" -b 115200 -D -U "flash:w:$HEX:i"
fi
