"""Privileged local inspection, GET-only rechecks and narrow audited resolutions."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
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
from app.domains.billing.operator_diagnostics import inspect_evidence
from app.infrastructure.sentry import Operation, report_exception


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    for command in ("inspect", "recover", "reconcile", "resolve-review"):
        action = commands.add_parser(command)
        action.add_argument("--user-id", required=True, type=UUID)
        action.add_argument("--purchase-id", required=True, type=UUID)
        if command == "resolve-review":
            action.add_argument("--resolution", required=True, choices=("restore-original", "bind-original"))
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


async def _run(arguments: argparse.Namespace, configuration: Settings, principal: str) -> dict:
    from app.core.database import SessionLocal

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
