# Local API shortcuts require a Unix-compatible shell and virtualenv layout.
# Use WSL on Windows; cross-platform repository workflows use scripts/repo.py.
API_VENV := $(CURDIR)/.venv
API_VENV_BIN := $(API_VENV)/bin
API_PYTHON := $(API_VENV_BIN)/python
POETRY_API := VIRTUAL_ENV=$(API_VENV) PATH=$(API_VENV_BIN):$(PATH) \
	POETRY_VIRTUALENVS_CREATE=false poetry --directory apps/api

run_api:
	$(API_PYTHON) -m uvicorn app.main:app --host 0.0.0.0 --app-dir apps/api

test_api:
	$(API_PYTHON) -m pytest apps/api/tests

migrate_api:
	$(API_PYTHON) -m alembic -c apps/api/alembic.ini upgrade head

lock_api:
	$(POETRY_API) lock

$(API_PYTHON):
	python3 -m venv $(API_VENV)

install_api: $(API_PYTHON)
	$(POETRY_API) install --with dev --no-root --sync

build_api:
	docker compose build api
