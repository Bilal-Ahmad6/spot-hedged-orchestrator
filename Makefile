PY ?= python

.PHONY: setup doctor lint fmt test smoke prices trace sim matrix verify report clean

setup:
	$(PY) -m pip install -e ".[dev,k8s]"

doctor:
	$(PY) -m spothedge doctor

lint:
	$(PY) -m ruff check src tests

fmt:
	$(PY) -m ruff format src tests

test:
	$(PY) -m pytest

smoke: doctor lint test

prices:
	$(PY) -m spothedge prices fetch --out prices/base.yaml

trace:
	$(PY) -m spothedge trace build --out experiments/traces/demand_30d.csv

sim:
	$(PY) -m spothedge sim run --config configs/base.yaml

matrix:
	$(PY) -m spothedge sim matrix --matrix experiments/configs/primary.yaml

verify:
	$(PY) -m spothedge verify

report:
	$(PY) -m spothedge report build

clean:
	rm -rf build dist .pytest_cache .ruff_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
