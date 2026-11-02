"""Authorized financial inspect/recover. Recovery sends only bounded provider GETs."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from app.composition.mapping_operator import resolve_operator_principal
from app.composition.purchases import recover_financial
from app.composition.sources import source_resources
from app.core.errors import AppError
from app.core.settings import Settings
from app.domains.purchases.service import inspect_purchase


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("command", choices=("inspect", "recover"))
    result.add_argument("--user-id", required=True, type=UUID)
    result.add_argument("--purchase-id", required=True, type=UUID)
    return result


async def _run(arguments: argparse.Namespace, configuration: Settings) -> dict:
    from app.core.database import SessionLocal

    if arguments.command == "recover":
        async with source_resources(configuration) as sources:
            purchase = await recover_financial(
                sources,
                configuration,
                factory=SessionLocal,
                user_id=arguments.user_id,
                purchase_id=arguments.purchase_id,
            )
    else:
        purchase = await run_in_threadpool(
            inspect_purchase, SessionLocal, configuration, arguments.user_id, arguments.purchase_id
        )
    return {
        "purchase_intent_id": str(purchase.id),
        "state": purchase.state,
        "reason": purchase.reason,
        "scope_held": purchase.held,
        "operations": [
            {
                "create_operation_id": str(op.id),
                "kind": op.kind,
                "state": op.state,
                "bound": op.bound_id is not None,
                "receipt_saved": op.candidate_id is not None,
                "last_failure": {
                    "code": op.last_failure_code,
                    "http_status": op.last_failure[0],
                    "lbx_code": op.last_failure[1],
                    "reason": op.last_failure[2],
                }
                if op.last_failure
                else None,
                "deadline": op.deadline.isoformat() if op.deadline else None,
            }
            for op in purchase.operations
        ],
    }


def main(argv: list[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    try:
        principal = resolve_operator_principal()
        configuration = Settings()
        with asyncio.Runner() as runner:
            result = runner.run(_run(arguments, configuration))
        print(json.dumps({**result, "operator_principal": principal}))
        return 0
    except ValidationError:
        code = "purchase_configuration_invalid"
    except SQLAlchemyError:
        code = "purchase_database_error"
    except AppError as error:
        code = error.code
    print(json.dumps({"detail": {"code": code}}), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
