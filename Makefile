# foamcut - GT2560 XYUV hot wire cutter bring-up project
#
#   make test          offline test suite (no hardware)
#   make hwtest-flash  flash the hardware self test firmware
#   make grbl-flash    build and flash the 4 axis grbl
#
PORT ?= /dev/ttyUSB0
# revA = GT2560 Rev.A / Rev.A+, v3 = GT2560 V3
REV  ?= revA

PY := python3

.PHONY: help deps test hwtest hwtest-flash monitor grbl grbl-flash gcode clean

help:
	@sed -n '1,8s/^#\s\?//p' $(MAKEFILE_LIST)
	@echo
	@echo "  PORT=$(PORT)  REV=$(REV)"

deps:
	$(PY) -m pip install -e host[test]

test:
	PYTHONPATH=host $(PY) -m pytest host/tests -q

# --- hardware self test firmware ------------------------------------------
hwtest:
	cd firmware/hwtest && pio run -e $(REV)

hwtest-flash:
	cd firmware/hwtest && pio run -e $(REV) -t upload --upload-port $(PORT)

monitor:
	cd firmware/hwtest && pio device monitor -b 115200 -p $(PORT)

# --- grbl-Mega-5X, 4 axis, GT2560 -----------------------------------------
grbl:
	./firmware/grbl5x/build.sh

grbl-flash:
	PORT=$(PORT) ./firmware/grbl5x/build.sh flash

# --- regenerate the generated test programs -------------------------------
gcode:
	PYTHONPATH=host $(PY) -m foamcut.cli gen square --size 50 --feed 300 -o gcode/01_square.nc
	PYTHONPATH=host $(PY) -c "from foamcut import gcode as g, pathlib; \
	  pathlib.Path('gcode/02_taper.nc').write_text(g.gen_taper(60,30,40,300))"
	PYTHONPATH=host $(PY) -m foamcut.cli check gcode/01_square.nc
	PYTHONPATH=host $(PY) -m foamcut.cli check gcode/02_taper.nc

clean:
	rm -rf firmware/hwtest/.pio host/**/__pycache__ host/.pytest_cache .pytest_cache
	@echo "firmware/grbl5x/vendor kept; delete it by hand to re-fetch grbl"
