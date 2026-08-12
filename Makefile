POETRY_API = POETRY_VIRTUALENVS_CREATE=false poetry --directory apps/api

run_api:
	uvicorn app.main:app  --host 0.0.0.0 --app-dir apps/api

test_api:
	python -m pytest apps/api/tests

migrate_api:
	python -m alembic -c apps/api/alembic.ini upgrade head

lock_api:
	$(POETRY_API) lock

install_api:
	$(POETRY_API) install --with dev --no-root --sync

build_api:
	docker compose build api
