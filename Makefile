.PHONY: test_db_up test_db_stop catalog_preview catalog_preview_publish

CATALOG_PREVIEW_PREVIOUS_REVISION ?= 0

test_db_up:
	python scripts/repo.py test-db up

test_db_stop:
	python scripts/repo.py test-db stop

# Explicit Unix/WSL SIMULATED preview; use the existing harness and publisher.
catalog_preview:
	MAPPING_ACCOUNT_ID=simulated-ru-lbx-account ./.venv/bin/python scripts/repo.py up --reuse
	$(MAKE) catalog_preview_publish

catalog_preview_publish:
	MAPPING_ACCOUNT_ID=simulated-ru-lbx-account MAPPING_OPERATOR_UIDS="[$$(id -u)]" PYTHONPATH=apps/api \
		./.venv/bin/python -m apps.api.tests.support.catalog_preview \
		--expected-previous-revision "$(CATALOG_PREVIEW_PREVIOUS_REVISION)"
