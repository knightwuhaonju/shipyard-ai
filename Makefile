PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
PYTEST_ARGS ?=

.PHONY: check dependency-check install-dev lint test typecheck

install-dev:
	$(PYTHON) -m pip install --disable-pip-version-check pip==25.0.1
	$(PYTHON) -m pip install --no-deps --requirement requirements-dev.lock
	$(PYTHON) -m pip install --no-deps --editable .

dependency-check:
	PIP_NO_CACHE_DIR=1 $(PYTHON) -m pip check

test:
	$(PYTHON) -m pytest $(PYTEST_ARGS)

lint:
	$(PYTHON) -m ruff check .

typecheck:
	$(PYTHON) -m mypy .

check: dependency-check test lint typecheck
