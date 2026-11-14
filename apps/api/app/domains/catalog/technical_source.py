"""Technical ownership read view; never inject defaults into retained evidence."""

from dataclasses import dataclass
from typing import Annotated

from pydantic import Field

SourceIdentifier = Annotated[str, Field(pattern=r"^[a-z][a-z0-9-]{0,63}$")]


@dataclass(frozen=True)
class TechnicalOwnership:
    technical_source_id: str
    backend_consumer_id: str


LEGACY_KERNEL_OWNERSHIP = TechnicalOwnership("platform-kernel", "platform-kernel")
