"""Translate storage availability failures without owning the outer transaction."""

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy.exc import OperationalError, TimeoutError


class DelegationUnavailableError(Exception):
    pass


@contextmanager
def delegation_storage_errors() -> Iterator[None]:
    try:
        yield
    except (OperationalError, TimeoutError):
        raise DelegationUnavailableError() from None
