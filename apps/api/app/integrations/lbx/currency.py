"""Account-scoped provider denomination; never infer ISO currency from an ID."""

from enum import StrEnum
from typing import Literal

from pydantic import Field

from app.integrations.lbx.offer_inputs import OfferInput


class CurrencyCode(StrEnum):
    RUB = "RUB"


class LbxCurrencyMapping(OfferInput):
    external_billing_account_id: str = Field(min_length=1)
    currency_id: int = Field(gt=0)
    iso_currency: CurrencyCode
    source_units: Literal["major", "minor"]
    decimal_places: int = Field(ge=0, le=36)
