run_api:
	uvicorn app.main:app  --host 0.0.0.0 --app-dir apps/api

test_api:
	python -m pytest apps/api/tests
