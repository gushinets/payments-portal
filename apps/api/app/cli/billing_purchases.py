"""Privileged local inspection, GET-only rechecks and narrow audited resolutions."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from app.composition.billing_operator import reconcile_purchase, resolve_review
from app.composition.mapping_operator import resolve_operator_principal
from app.composition.purchases import recover_financial
from app.composition.sources import source_resources
from app.core.errors import AppError
from app.core.settings import Settings
from app.domains.billing.operator_contracts import ResolutionRequest
from app.domains.billing.operator_diagnostics import inspect_evidence, inspect_operation
from app.domains.billing.access_invalidation import inspect_delivery
from app.domains.billing.late_purchase_reviews import ClosureEvidence, ClosureRequest, close_case
from app.domains.billing.terminal_resolution import TerminalEvidence, TerminalRequest, resolve_purchase
from app.infrastructure.sentry import Operation, report_exception


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    lookup = commands.add_parser("inspect-operation", help="Resolve a local Sentry operation reference without HTTP")
    lookup.add_argument("--operation-id", required=True, type=UUID)
    for command in ("inspect-invalidation", "retry-invalidation"):
        action = commands.add_parser(command, help="Inspect/retry parked local backend invalidation delivery")
        action.add_argument("--user-id", required=True, type=UUID)
        action.add_argument("--recipient-id", required=True)
    for command in ("inspect", "recover", "reconcile", "resolve-review", "resolve-purchase"):
        action = commands.add_parser(command)
        action.add_argument("--user-id", required=True, type=UUID)
        action.add_argument("--purchase-id", required=True, type=UUID)
        if command == "resolve-purchase":
            action.add_argument("--case-id", type=UUID)
            action.add_argument("--expected-digest", required=True)
            action.add_argument("--evidence-file", required=True, type=Path)
            action.add_argument("--reason", required=True)
            action.add_argument("--reference", required=True)
        if command == "resolve-review":
            action.add_argument(
                "--resolution", required=True, choices=("restore-original", "bind-original", "select-primary")
            )
            action.add_argument("--case-id", required=True, type=UUID)
            action.add_argument("--expected-case-digest", required=True)
            action.add_argument("--expected-observation-id", type=UUID)
            action.add_argument("--expected-reconciliation-fence", type=int)
            action.add_argument("--operation-id", type=UUID)
            action.add_argument("--expected-operation-fence", type=UUID)
            action.add_argument("--reason", required=True)
            action.add_argument("--reference", required=True)
    return result


def resolution_request(arguments: argparse.Namespace) -> ResolutionRequest:
    return ResolutionRequest.model_validate({key: value for key, value in vars(arguments).items() if key != "command"})


def terminal_request(arguments: argparse.Namespace) -> TerminalRequest | ClosureRequest:
    try:
        with arguments.evidence_file.open("rb") as stream:
            content = stream.read(32769)
        if len(content) > 32768:
            raise AppError("purchase_resolution_arguments_invalid")
        values = {
            key: value for key, value in vars(arguments).items() if key not in {"command", "evidence_file", "case_id"}
        }
        if arguments.case_id is not None:
            return ClosureRequest.model_validate(
                {**values, "case_id": arguments.case_id, "evidence": ClosureEvidence.model_validate_json(content)}
            )
        return TerminalRequest.model_validate({**values, "evidence": TerminalEvidence.model_validate_json(content)})
    except (OSError, ValidationError):
        raise AppError("purchase_resolution_arguments_invalid") from None


async def _run(arguments: argparse.Namespace, configuration: Settings, principal: str) -> Mapping[str, object]:
    # CLI serialization joins the typed delivery result and legacy command
    # documents; it does not consume or redefine those commands' nested shapes.
    from app.core.database import SessionLocal

    if arguments.command in ("inspect-invalidation", "retry-invalidation"):
        return await run_in_threadpool(
            inspect_delivery,
            SessionLocal,
            configuration,
            arguments.user_id,
            recipient_id=arguments.recipient_id,
            retry=arguments.command == "retry-invalidation",
        )
    if arguments.command == "resolve-purchase":
        request = terminal_request(arguments)
        if isinstance(request, ClosureRequest):
            result = await run_in_threadpool(close_case, SessionLocal, configuration, request, principal)
        else:
            result = await run_in_threadpool(resolve_purchase, SessionLocal, configuration, request, principal)
        return result.model_dump(mode="json")
    if arguments.command == "inspect-operation":
        return await run_in_threadpool(inspect_operation, SessionLocal, configuration, arguments.operation_id)
    if arguments.command == "inspect":
        return await run_in_threadpool(
            inspect_evidence, SessionLocal, configuration, arguments.user_id, arguments.purchase_id
        )
    request = resolution_request(arguments) if arguments.command == "resolve-review" else None
    async with source_resources(configuration) as sources:
        if request is not None:
            return await resolve_review(
                sources, configuration, factory=SessionLocal, request=request, principal=principal
            )
        if arguments.command == "recover":
            await recover_financial(
                sources,
                configuration,
                factory=SessionLocal,
                user_id=arguments.user_id,
                purchase_id=arguments.purchase_id,
            )
        else:
            await reconcile_purchase(
                sources,
                configuration,
                factory=SessionLocal,
                user_id=arguments.user_id,
                purchase_id=arguments.purchase_id,
            )
    return await run_in_threadpool(
        inspect_evidence, SessionLocal, configuration, arguments.user_id, arguments.purchase_id
    )


def main(argv: list[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    try:
        if arguments.command == "resolve-review":
            try:
                resolution_request(arguments)
            except ValidationError:
                raise AppError("billing_review_arguments_invalid") from None
        principal = resolve_operator_principal()
        configuration = Settings()
        with asyncio.Runner() as runner:
            result = runner.run(_run(arguments, configuration, principal))
        print(json.dumps({**result, "operator_principal": principal}))
        return 0
    except ValidationError:
        code = "purchase_configuration_invalid"
    except SQLAlchemyError:
        code = "purchase_database_error"
    except AppError as error:
        code = error.code
    except Exception as error:
        report_exception(error, operation=Operation.BILLING_OPERATOR)
        code = "purchase_internal_error"
    print(json.dumps({"detail": {"code": code}}), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
