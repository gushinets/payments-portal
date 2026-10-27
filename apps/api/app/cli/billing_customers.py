"""Privileged read-only customer diagnosis from durable CREATE evidence and LBX GETs."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.composition.customer_diagnostics import diagnose_customer
from app.composition.mapping_operator import resolve_operator_principal
from app.core.errors import AppError
from app.core.settings import Settings


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__)
    actions = command.add_subparsers(dest="command", required=True)
    diagnose = actions.add_parser("diagnose", help="Read state, saved CREATE results and live customer candidates")
    diagnose.add_argument("--user-id", required=True, type=UUID, help="Portal users.id; never email or LBX ID")
    return command


def main(argv: list[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    try:
        principal = resolve_operator_principal()
        configuration = Settings()
        from app.core.database import SessionLocal

        with asyncio.Runner() as runner:
            result = runner.run(diagnose_customer(configuration, factory=SessionLocal, user_id=arguments.user_id))
        print(json.dumps({**result, "operator_principal": principal}))
        return 0 if result["diagnosis"] in {"binding_verified", "not_provisioned"} else 2
    except ValidationError:
        code = "billing_customer_configuration_invalid"
    except SQLAlchemyError:
        code = "billing_customer_database_error"
    except AppError as error:
        code = error.code
    print(json.dumps({"detail": {"code": code}}), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
