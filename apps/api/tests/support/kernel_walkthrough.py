"""Explicit dev-only operator: real Kernel HTTP + isolated recorded LBX reads.

Never imported by app/. No in-process Kernel transport or outage fallback.
Preparation records the named SIMULATED approval independently of evaluation.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from datetime import date
from pathlib import Path

import httpx
from pydantic import ValidationError
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from app.cli import commercial_mappings as cli
from app.composition.mapping_operator import (
    FreshMappingEvaluation,
    MappingProposal,
    account_billing_date,
    authorize_operator,
    fresh_mapping_evaluation,
    load_operator_input,
)
from app.composition import mapping_operator
from app.core.errors import AppError
from app.infrastructure.operator_preflight import operator_preflight_lock
from app.core.settings import AppEnv, Settings
from app.domains.catalog.mapping_evidence import ApprovedMapping
from app.domains.catalog.publication import publish_mapping
from app.integrations.lbx.offer_inputs import SelectedOfferInputs
from apps.api.tests.support.commercial_mappings import reviewed_fixture
from apps.api.tests.support.lbx import ACCOUNT, PASSWORD, USERNAME
from apps.api.tests.support.lbx_selected_offer import SelectedOfferRecording, simulated_inputs, simulated_selection


def require_development_operator(configuration: Settings) -> str:
    if configuration.app_env != AppEnv.DEVELOPMENT:
        raise AppError("kernel_walkthrough_development_only")
    principal = authorize_operator(configuration)
    database = make_url(configuration.database_url)
    if (
        not re.fullmatch(r"payments_[0-9a-f]{8}", configuration.postgres_db)
        or database.get_backend_name() != "postgresql"
        or database.database != configuration.postgres_db
    ):
        raise AppError("kernel_walkthrough_worktree_database_required")
    if configuration.mapping_account_id != ACCOUNT:
        raise AppError("kernel_walkthrough_simulated_account_required")
    return principal


def prepare_inputs(directory: Path, *, effective_on: date | None = None) -> None:
    # This independent test approval uses only the named LBX recording, never
    # the current Kernel response or the attempted publication's evidence.
    with asyncio.Runner() as runner:
        selection = simulated_selection()
        if effective_on is not None:
            selection = selection.model_copy(update={"effective_on": effective_on})
        reviewed = runner.run(reviewed_fixture(selection=selection, revision="calendar-review-v2"))
    directory.mkdir(parents=True, exist_ok=True)
    for name, value in (
        ("proposal", reviewed.proposal),
        ("approval", reviewed.approval),
        ("inputs", simulated_inputs()),
    ):
        (directory / f"{name}.json").write_text(value.model_dump_json(indent=2) + "\n", encoding="utf-8")


async def evaluate_recorded_lbx(configuration: Settings, proposal_path: Path, principal: str) -> FreshMappingEvaluation:
    # Only the dev composition substitutes LBX transport/config. Kernel keeps
    # the actual container configuration and its ordinary HTTP transport.
    sources = Settings(
        **{
            **configuration.model_dump(),
            "lbx_base_url": "https://lbx-client.test",
            "lbx_external_billing_account_id": ACCOUNT,
            "lbx_server_username": USERNAME,
            "lbx_server_password": PASSWORD,
        }
    )
    return await fresh_mapping_evaluation(
        sources,
        proposal=load_operator_input(proposal_path, MappingProposal),
        approval=load_operator_input(configuration.mapping_approval_file, ApprovedMapping),
        source_inputs=load_operator_input(configuration.mapping_source_inputs_file, SelectedOfferInputs),
        principal=principal,
        lbx_transport=httpx.MockTransport(SelectedOfferRecording().respond),
    )


def execute(arguments: argparse.Namespace, configuration: Settings) -> str:
    principal = require_development_operator(configuration)
    if arguments.command == "prepare":
        prepare_inputs(
            arguments.output_dir,
            effective_on=account_billing_date(simulated_inputs(), account_id=ACCOUNT, now=mapping_operator.utc_now()),
        )
        return json.dumps({"evidence_mode": "SIMULATED", "prepared": True})
    if arguments.command == "query":
        # Existing DB-only CLI never creates a source/admission owner.
        return cli.execute(arguments, configuration)
    if arguments.command == "publish" and arguments.expected_previous_revision < 0:
        raise AppError("mapping_expected_revision_invalid")
    with operator_preflight_lock(configuration.mapping_operator_lock_file):
        with asyncio.Runner() as runner:
            fresh = runner.run(evaluate_recorded_lbx(configuration, arguments.proposal, principal))
        output = {
            "billing_offer_id": fresh.document.material.billing_offer_id,
            "evaluation": fresh.document.model_dump(mode="json"),
            "persisted": False,
        }
        if arguments.command == "publish":
            from app.core.database import SessionLocal

            result = publish_mapping(
                SessionLocal,
                evaluation=fresh.document,
                expected_previous_revision=arguments.expected_previous_revision,
                deadline=fresh.deadline,
                evidence_valid_until=fresh.evidence_valid_until,
                lock_timeout_seconds=configuration.mapping_lock_timeout_seconds,
                allow_simulated=True,
            )
            output.update(
                persisted=True,
                mapping_revision_id=str(result.stored.mapping_revision_id),
                revision_number=result.stored.revision_number,
                inserted=result.inserted,
                stored_document=result.stored.document.model_dump(mode="json"),
            )
        return json.dumps(output)


def main(argv: list[str] | None = None) -> int:
    parser = cli.parser()
    # Keep ordinary command arguments identical to the existing operator CLI.
    # Preparation is deliberately separate; dry-run/publish never self-approve.
    if argv is None:
        argv = sys.argv[1:]
    if argv and argv[0] == "prepare":
        parser = argparse.ArgumentParser(description="Prepare named SIMULATED walkthrough inputs")
        parser.add_argument("command", choices=("prepare",))
        parser.add_argument("--output-dir", type=Path, required=True)
    arguments = parser.parse_args(argv)
    try:
        output = execute(arguments, Settings())
    except AppError as error:
        print(json.dumps({"detail": {"code": error.code}}), file=sys.stderr)
        return 1
    except (ValidationError, OSError, ValueError):
        print('{"detail":{"code":"kernel_walkthrough_configuration_invalid"}}', file=sys.stderr)
        return 1
    except SQLAlchemyError:
        print('{"detail":{"code":"mapping_database_error"}}', file=sys.stderr)
        return 1
    # Development-only, UID-authorized result with the ordinary CLI's private
    # audit boundary, including reason/references; protect stdout accordingly.
    # Configured/recorded HTTP credentials are not serialized into the audit.
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
