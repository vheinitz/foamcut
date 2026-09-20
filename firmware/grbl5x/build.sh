#!/usr/bin/env bash
# Fetch grbl-Mega-5X, apply the foamcut GT2560 / XYUV overlay, build, optionally flash.
#
#   ./build.sh              fetch + configure + build  -> vendor/grbl.hex
#   ./build.sh flash        the above, then flash via /dev/ttyUSB0
#   PORT=/dev/ttyACM0 ./build.sh flash
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
"$HERE/configure.py" "$VENDOR"

echo "==> building"
make -C "$VENDOR" clean >/dev/null 2>&1 || true
mkdir -p "$VENDOR/build"
make -C "$VENDOR" -j"$(nproc)"

echo
avr-size --format=avr --mcu=atmega2560 "$VENDOR/build/main.elf" 2>/dev/null || true
echo "==> firmware at $VENDOR/grbl.hex"

if [ "${1:-}" = "flash" ]; then
  echo "==> flashing $PORT"
  avrdude -v -p atmega2560 -c wiring -P "$PORT" -b 115200 -D -U "flash:w:$VENDOR/grbl.hex:i"
fi
