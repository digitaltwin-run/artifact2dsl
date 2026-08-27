SHELL := /bin/bash

.PHONY: test lint standard check wheel-smoke panel9

PYTHONPATH := src:packages/sch2dsl/src:packages/pcb2dsl/src:packages/svg2dsl/src:packages/cad2dsl/src:/home/tom/github/digitaltwin-run/twin-kicad/src
PANEL9_ARTIFACT_ROOT ?= /home/tom/github/maskservice/viewer/artifacts
PANEL9_NETLIST ?=

test:
	PYTHONPATH="$(PYTHONPATH)" python3 -m pytest -q

lint:
	PYTHONPATH="$(PYTHONPATH)" python3 -m ruff check src packages tests scripts

standard:
	python3 scripts/verify_conformance.py

check: test lint standard

wheel-smoke:
	python3 scripts/smoke_wheels.py

panel9:
	PANEL9_NETLIST="$(PANEL9_NETLIST)" PYTHONPATH="$(PYTHONPATH)" \
		python3 scripts/check_panel9.py --artifacts-root "$(PANEL9_ARTIFACT_ROOT)"
