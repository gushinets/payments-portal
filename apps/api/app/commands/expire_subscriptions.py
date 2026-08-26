"""Expire due subscriptions once for invocation by an external scheduler."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from app.core.database import SessionLocal
from app.domains.billing.service import (
    ExpireDueSubscriptionsCommand,
    expire_due_subscriptions,
)


MAX_BATCH_SIZE = 1000


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
    args = build_parser().parse_args(argv)
    command = ExpireDueSubscriptionsCommand(batch_size=args.batch_size)
    with SessionLocal() as db:
        expired = expire_due_subscriptions(db, command)
        db.commit()
    print(f"expired_subscriptions={len(expired)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
