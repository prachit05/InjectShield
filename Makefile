.PHONY: install dev down test lint format eval smoke deploy teardown

PY ?= .venv/bin/python

install:            ## create the venv and install everything for local dev
	python -m venv .venv
	$(PY) -m pip install -r requirements-dev.txt

dev:                ## run api + worker + postgres + localstack
	docker compose up --build

down:
	docker compose down -v

test:
	$(PY) -m pytest

lint:
	$(PY) -m ruff check .
	$(PY) -m ruff format --check .

format:
	$(PY) -m ruff check --fix .
	$(PY) -m ruff format .

eval:               ## precision / recall on tests/sample_prompts
	PYTHONPATH=shared:worker $(PY) -m injectshield_worker.evaluate tests/sample_prompts

smoke:              ## one prompt end to end (BASE_URL / TOKEN to target AWS)
	bash scripts/smoke.sh

deploy:             ## Phase 3-4
	bash scripts/deploy.sh

teardown:           ## Phase 3: run after every AWS session
	bash scripts/teardown.sh
