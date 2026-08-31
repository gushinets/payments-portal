.PHONY: test_db_up test_db_stop

test_db_up:
	python scripts/repo.py test-db up

test_db_stop:
	python scripts/repo.py test-db stop
