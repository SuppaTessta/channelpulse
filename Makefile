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

.PHONY: setup lock up down dbt-debug api web lint test

setup:  ## create .venv + install Python and web deps
	$(BOOTSTRAP_PY) -m venv .venv
	$(PY) -m pip install -r requirements.txt
	npm --prefix web ci

lock:  ## re-pin constraints.txt after editing requirements.txt
	$(PY) -m pip freeze --exclude-editable > constraints.txt

up:  ## start Postgres and wait until healthy
	docker compose up -d --wait

down:
	docker compose down

dbt-debug:
	$(DBT) debug $(DBT_ARGS)

api:  ## dev server from .venv
	$(PY) -m uvicorn app.main:app --app-dir api --reload --reload-dir api --port $(API_PORT)

web:
	npm --prefix web run dev

lint:
	$(PY) -m ruff check .
	$(DBT) parse $(DBT_ARGS)
	npm --prefix web run lint

test:
	$(PY) -m pytest
