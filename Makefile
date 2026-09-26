# All Python runs from the repo-root .venv (never system Python).
# Windows: GNU make via `winget install ezwinports.make`.
-include .env
export

ifeq ($(OS),Windows_NT)
  BOOTSTRAP_PY ?= py -3.12
  VENV_BIN := .venv/Scripts
else
  BOOTSTRAP_PY ?= python3.12
  VENV_BIN := .venv/bin
endif
# Quoted so cmd.exe (used on Windows for recipes with > | &&) doesn't read "/" as a switch.
PY := "$(VENV_BIN)/python"
DBT := "$(VENV_BIN)/dbt"
DBT_ARGS := --project-dir warehouse --profiles-dir warehouse
API_PORT ?= 8000
# The smoke test checks the API directly as well as through the dashboard (exported to recipes by `export`).
SMOKE_API_URL ?= http://127.0.0.1:$(API_PORT)

.PHONY: setup lock up down seed dbt detect roles semantic acceptance eval dbt-debug api web web-start smoke lint test

setup:  ## create .venv + install Python and web deps
	$(BOOTSTRAP_PY) -m venv .venv
	$(PY) -m pip install -r requirements.txt
	npm --prefix web ci

lock:  ## re-pin constraints.txt after editing requirements.txt
	$(PY) -m pip freeze --exclude-editable > constraints.txt

up:  ## start Postgres and wait until healthy
	docker compose up -d --wait

seed:  ## synthetic data -> raw schema at the pinned as-of (idempotent: rebuilds the schema)
	$(PY) generator/generate.py

dbt:  ## build + test the warehouse, run the pre-registered detectors, (re)apply the API's DB roles
	$(DBT) build --no-partial-parse $(DBT_ARGS)
	$(PY) -m detectors.run
	$(PY) api/app/admin.py roles

detect:  ## re-run the pre-registered detectors -> marts.mart_anomaly_flags + detectors/results/latest.json
	$(PY) -m detectors.run

roles:  ## least-privilege roles: agent (read marts) and ops (write traces); idempotent
	$(PY) api/app/admin.py roles

semantic:  ## re-parse warehouse/semantic_models into the API's shipped semantic manifest
	$(PY) api/app/admin.py semantic

acceptance:  ## black-box check of the planted anomalies against generator/ground_truth.yaml (slow: extra seeds)
	$(PY) generator/acceptance.py

eval:  ## golden-set eval of the Ask agent -> evals/results/latest.json (needs Anthropic credentials to score)
	$(PY) evals/run_eval.py

down:
	docker compose down

dbt-debug:
	$(DBT) debug $(DBT_ARGS)

api:  ## dev server from .venv
	$(PY) -m uvicorn app.main:app --app-dir api --reload --reload-dir api --port $(API_PORT)

web:  ## dev server (builds into web/.next-dev, so a production build can't swap files under it)
	npm --prefix web run dev

web-start:  ## production build, then serve it. Restart after every build: a server older than .next breaks pages (D28)
	npm --prefix web run build
	npm --prefix web run start

smoke:  ## browser smoke test of every page against the running API and dashboard (make api, make web-start)
	cd web && npx playwright test

lint:
	$(PY) -m ruff check .
	$(DBT) parse $(DBT_ARGS)
	npm --prefix web run lint

test:
	$(PY) -m pytest
