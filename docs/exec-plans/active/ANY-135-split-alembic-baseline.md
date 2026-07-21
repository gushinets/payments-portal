# ANY-135 - Split Alembic Baseline

Status: active
Owner: repository maintainers
Started: 2026-07-20

## Objective

Replace the monolithic initial Alembic revision with a single-head, linear,
domain-ordered baseline chain that preserves the current Payment Portal schema,
indexes, constraints, foreign keys, and deterministic legal/catalog seed data.

## Non-goals

- Adding subscription or entitlement tables.
- Adding production rollout, compatibility, or backfill logic while this
  baseline is still rewriteable.
- Importing mutable application models or seed helpers from migrations.

## Progress

- [x] Read root/API/data-model/workflow guidance.
- [x] Confirm work is on `ANY-135`, branched from `ANY-77`.
- [x] Split the migration into foundation, catalog, and commerce revisions.
- [x] Update migration tests to prove the complete revision chain.
- [x] Regenerate schema documentation and run focused checks.
- [x] Run canonical checks and record evidence.

## Decisions

- Keep legal seed data in the foundation/legal/provider revision.
- Keep deterministic catalog seed data in the catalog revision.
- Keep entrypoints, checkout, orders, payments, refunds, webhook inbox, and the
  temporary product access state in the commerce revision.
- Preserve one Alembic head so ANY-78 can append subscriptions and entitlements
  as the next forward revision.

## Validation Plan

- PostgreSQL Alembic integration test covers `base -> head -> base -> head`.
- Migration test asserts a linear script chain and expected revision order.
- Generated schema docs pass `npm run generate:check`.
- Run `npm run check:fast` and the broadest locally supported `npm run check`.

## Completion Evidence

- Rebased `ANY-135` onto `origin/main` after `origin/main` advanced to
  `ANY-77 - Implement Payment Portal catalog, plans, bundles, and limits (#13)`.
  Duplicate local ANY-77 commits were skipped or dropped as already upstream;
  final branch diff contains only ANY-135 migration split plus the checkout
  currency guard.
- `.venv/bin/python -m py_compile scripts/repo.py apps/api/tests/test_alembic_postgres.py apps/api/alembic/versions/*.py`:
  passed.
- `.venv/bin/python -m alembic -c apps/api/alembic.ini heads`: single head
  `20260707_0003`.
- `.venv/bin/python -m alembic -c apps/api/alembic.ini history`: linear chain
  `<base> -> 20260707_0001 -> 20260707_0002 -> 20260707_0003`.
- `PATH=.venv/bin:$PATH npm run generate`: passed with no generated schema diff.
- `PATH=.venv/bin:$PATH npm run generate:check`: passed.
- `.venv/bin/python -m pytest -p no:cacheprovider --ignore apps/api/tests/test_alembic_postgres.py apps/api/tests`:
  39 passed, 2 skipped.
- `PATH=.venv/bin:$PATH npm run check:fast`: passed.
- `PATH=.venv/bin:$PATH npm run check`: passed; PostgreSQL integration skipped
  because `TEST_POSTGRES_DATABASE_URL` was not set, and browser suite skipped
  because `RUN_E2E=true` was not set.
- Post-rebase focused checkout/currency tests:
  `.venv/bin/python -m pytest -p no:cacheprovider apps/api/tests/test_api.py -k 'checkout or currency'`
  passed with 10 passed.
- Post-rebase API suite:
  `.venv/bin/python -m pytest -p no:cacheprovider --ignore apps/api/tests/test_alembic_postgres.py apps/api/tests`
  passed with 42 passed, 2 skipped.
- Post-rebase `PATH=.venv/bin:$PATH npm run check:fast`: passed.
- Post-rebase `PATH=.venv/bin:$PATH npm run check`: passed; PostgreSQL
  integration skipped because `TEST_POSTGRES_DATABASE_URL` was not set, and
  browser suite skipped because `RUN_E2E=true` was not set.
- `.venv/bin/python -m pytest -p no:cacheprovider apps/api/tests/test_alembic_postgres.py`:
  2 skipped because `TEST_POSTGRES_DATABASE_URL` was not set.
- `git diff --check`: passed.
- Attempted PostgreSQL Alembic integration using the local `.env` database key:
  sandboxed run was blocked by local TCP restrictions; escalated run reached the
  host but failed with connection refused because the local database listener was
  not running.
