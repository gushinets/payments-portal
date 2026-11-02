"""Explicit manual Step 6 acceptance setup; never imported by Portal runtime.

Publish the already-declared SIMULATED approval/HTTP recordings through the
existing clients, evaluator and PostgreSQL publisher. This does not start the
standalone Kernel mock, replace production sources, or create/migrate a DB.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from collections.abc import Mapping
from typing import TYPE_CHECKING

import httpx
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from app.core.errors import AppError
from app.infrastructure.operator_preflight import operator_preflight_lock
from scripts import repo

if TYPE_CHECKING:
    from apps.api.tests.support.commercial_mappings import HistoricalOperatorSettings as Settings
    from app.domains.catalog.publication import PublicationResult


def publish_simulated_preview(
    runtime: Mapping[str, str], *, operator: Settings, expected_previous_revision: int
) -> PublicationResult:
    from apps.api.tests.support import v1_mapping_operator as mapping_operator
    from apps.api.tests.support.v1_mapping_operator import (
        account_billing_date,
        authorize_operator,
        fresh_mapping_evaluation,
    )
    from app.core.settings import AppEnv
    from app.domains.catalog.publication import publish_mapping

    if operator.app_env != AppEnv.DEVELOPMENT or runtime.get("APP_ENV") != AppEnv.DEVELOPMENT:
        raise AppError("catalog_preview_development_only")
    if type(expected_previous_revision) is not int or expected_previous_revision < 0:
        raise AppError("mapping_expected_revision_invalid")
    if not re.fullmatch(r"payments_[0-9a-f]{8}", runtime.get("POSTGRES_DB", "")):
        raise AppError("catalog_preview_worktree_database_required")
    if (
        not operator.mapping_account_id
        or operator.mapping_account_id != runtime.get("MAPPING_ACCOUNT_ID")
        or operator.instance_tenant_id != runtime.get("INSTANCE_TENANT_ID")
        or operator.instance_region != runtime.get("INSTANCE_REGION")
    ):
        raise AppError("catalog_preview_runtime_scope_mismatch")
    principal = authorize_operator(operator)

    # Test-only inputs stay outside app/ and both production images. The OS
    # principal is real; the independent fixture approval is visibly SIMULATED.
    from apps.api.tests.support.commercial_mappings import operator_settings, reviewed_fixture
    from apps.api.tests.support.kernel import manifest_fixture
    from apps.api.tests.support.lbx_selected_offer import SelectedOfferRecording, simulated_inputs, simulated_selection

    selection = simulated_selection()
    if operator.mapping_account_id != selection.external_billing_account_id:
        raise AppError("catalog_preview_simulated_account_required")
    selection = selection.model_copy(
        update={
            "effective_on": account_billing_date(
                simulated_inputs(), account_id=operator.mapping_account_id, now=mapping_operator.utc_now()
            )
        }
    )
    source_configuration = operator_settings(
        app_env=AppEnv.DEVELOPMENT,
        mapping_account_id=operator.mapping_account_id,
        mapping_operator_uids=operator.mapping_operator_uids,
        instance_tenant_id=operator.instance_tenant_id,
        instance_region=operator.instance_region,
    )
    with operator_preflight_lock(operator.mapping_operator_lock_file):
        with asyncio.Runner() as runner:
            reviewed = runner.run(reviewed_fixture(selection=selection, revision="calendar-review-v2"))
            evaluation = runner.run(
                fresh_mapping_evaluation(
                    source_configuration,
                    proposal=reviewed.proposal,
                    approval=reviewed.approval,
                    source_inputs=simulated_inputs(),
                    principal=principal,
                    kernel_transport=httpx.MockTransport(lambda request: httpx.Response(200, json=manifest_fixture())),
                    lbx_transport=httpx.MockTransport(SelectedOfferRecording().respond),
                )
            )
        # All source work has finished and closed before opening the working DB.
        engine = create_engine(repo.host_database_url_from_runtime(dict(runtime)), connect_args={"connect_timeout": 5})
        try:
            return publish_mapping(
                sessionmaker(bind=engine, autoflush=False),
                evaluation=evaluation.document,
                expected_previous_revision=expected_previous_revision,
                deadline=evaluation.deadline,
                evidence_valid_until=evaluation.evidence_valid_until,
                lock_timeout_seconds=operator.mapping_lock_timeout_seconds,
                allow_simulated=True,
            )
        finally:
            engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Publish the declared SIMULATED preview into the current dev worktree DB"
    )
    parser.add_argument("--expected-previous-revision", type=int, required=True)
    arguments = parser.parse_args(argv)
    try:
        if not repo.RUNTIME_ENV.is_file():
            raise AppError("catalog_preview_runtime_not_initialized")
        runtime = repo.read_runtime_env()
        # Settings is instantiated when its module is imported. Bootstrap the
        # existing host-API environment first, including the harness scope that
        # older local .env files may lack. Preserve explicit shell/.env values
        # and operator authorization; never invent a UID allowlist here.
        for name, value in repo.direct_api_environment().items():
            os.environ.setdefault(name, value)
        from apps.api.tests.support.commercial_mappings import HistoricalOperatorSettings as Settings

        result = publish_simulated_preview(
            runtime, operator=Settings(), expected_previous_revision=arguments.expected_previous_revision
        )
    except AppError as error:
        print(json.dumps({"detail": {"code": error.code}}), file=sys.stderr)
        return 1
    except (ValidationError, KeyError, ValueError):
        print('{"detail":{"code":"catalog_preview_configuration_invalid"}}', file=sys.stderr)
        return 1
    except SQLAlchemyError:
        print('{"detail":{"code":"catalog_preview_database_error"}}', file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "product_id": result.stored.document.material.technical.product_id,
                "mapping_revision_id": str(result.stored.mapping_revision_id),
                "revision_number": result.stored.revision_number,
                "evidence_mode": result.stored.document.evidence_mode,
                "inserted": result.inserted,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
