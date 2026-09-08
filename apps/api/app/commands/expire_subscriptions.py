"""Expire due subscriptions once for invocation by an external scheduler."""

from __future__ import annotations

import argparse
import logging
from collections.abc import Sequence
from uuid import uuid4

from app.core.database import SessionLocal
from app.core.observability import configure_logging
from app.domains.billing.service import (
    ExpireDueSubscriptionsCommand,
    expire_due_subscriptions,
)


MAX_BATCH_SIZE = 1000
logger = logging.getLogger(__name__)


def _batch_size(value: str) -> int:
    batch_size = int(value)
    if not 1 <= batch_size <= MAX_BATCH_SIZE:
        raise argparse.ArgumentTypeError(f"batch size must be between 1 and {MAX_BATCH_SIZE}")
    return batch_size


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--batch-size",
        type=_batch_size,
        default=ExpireDueSubscriptionsCommand.model_fields["batch_size"].default,
        help="maximum number of due subscriptions to expire (default: %(default)s)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    configure_logging()
    args = build_parser().parse_args(argv)
    command = ExpireDueSubscriptionsCommand(batch_size=args.batch_size)
    run_id = str(uuid4())
    logger.info(
        "subscription_expiry_run_started",
        extra={"structured": {"run_id": run_id, "batch_size": command.batch_size}},
    )
    with SessionLocal() as db:
        try:
            expired = expire_due_subscriptions(db, command)
        except Exception as error:
            logger.error(
                "subscription_expiry_run_failed",
                extra={
                    "structured": {
                        "run_id": run_id,
                        "batch_size": command.batch_size,
                        "error_type": type(error).__name__,
                    }
                },
            )
            raise
        for subscription in expired:
            logger.info(
                "subscription_expiry_transition_committed",
                extra={"structured": {"run_id": run_id, "subscription_id": str(subscription.id)}},
            )
        logger.info(
            "subscription_expiry_run_succeeded",
            extra={
                "structured": {
                    "run_id": run_id,
                    "batch_size": command.batch_size,
                    "expired_count": len(expired),
                }
            },
        )
    print(f"expired_subscriptions={len(expired)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
