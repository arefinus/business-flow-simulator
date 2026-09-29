PYTHON ?= python
PKG = business_flow_simulator

.PHONY: setup smoke demo test evaluate figures fixture clean

setup:
	pip install -e . && pip install pytest

smoke:
	$(PYTHON) -m $(PKG) smoke --out build/smoke

demo:
	$(PYTHON) -m $(PKG) demo

test:
	$(PYTHON) -m pytest -q

evaluate:
	$(PYTHON) -m $(PKG) evaluate --events examples/output/event_log_baseline_rules_automation.json

figures:
	$(PYTHON) tools/render_figures.py

fixture:
	$(PYTHON) tools/make_fixture.py

clean:
	rm -rf build .pytest_cache src/$(PKG)/__pycache__ tests/__pycache__
