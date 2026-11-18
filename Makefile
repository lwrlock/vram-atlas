CC ?= gcc
CFLAGS ?= -O2 -Wall -Wextra -D_GNU_SOURCE

.PHONY: all test clean

all: vram-atlas-probe

vram-atlas-probe: src/native/accel_probe.c
	$(CC) $(CFLAGS) -o $@ $<

test: all
	/usr/bin/python3 -m py_compile src/vram_atlas/*.py
	./vram-atlas-probe --sample-ms 80 --json >/dev/null
	PYTHONPATH=src /usr/bin/python3 -m unittest discover -s tests -v

clean:
	rm -f vram-atlas-probe
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
