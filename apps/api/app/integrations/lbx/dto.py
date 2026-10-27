"""Selected GET schemas from LBX Swagger 1.0.11, not Portal HTTP contracts.

Only identities/envelopes must be present at this transport boundary. Optional
commercial fields preserve absence as None; the Step 4 normalizer must refuse
incomplete evidence rather than interpreting None as zero/false/approval.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Generic, TypeVar

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, SecretStr, field_validator, model_validator


Identity = Annotated[int, Field(gt=0)]
NonnegativeInteger = Annotated[int, Field(ge=0)]


def _exact_number(value: Any) -> Decimal:
    # json.loads(parse_float=Decimal) is the ONLY numeric entry point. Strings,
    # bools and binary floats are not repaired into seemingly exact amounts.
    if type(value) is int:
        return Decimal(value)
    if isinstance(value, Decimal) and value.is_finite():
        return value
    raise ValueError("expected a finite JSON number")


def _calendar_date(value: Any) -> date:
    # E04 uses a provider-local midnight, not a UTC timestamp. Accept only
    # that documented representation and ISO dates; never truncate a time.
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}(?: 00:00:00)?", value):
        raise ValueError("expected a calendar date or provider-local midnight")
    return date.fromisoformat(value[:10])


ExactNumber = Annotated[Decimal, BeforeValidator(_exact_number)]
CalendarDate = Annotated[date, BeforeValidator(_calendar_date)]


class LbxDto(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True, hide_input_in_errors=True)


T = TypeVar("T")


class LbxEnvelope(LbxDto, Generic[T]):
    code: Annotated[int, Field(ge=200, le=200)]
    response: T


class LbxSession(LbxDto):
    token: SecretStr
    expires_in: Annotated[int, Field(gt=0)]

    @field_validator("token", mode="before")
    @classmethod
    def require_bearer_token(cls, value: Any) -> str:
        if not isinstance(value, str) or not value or any(not 33 <= ord(char) <= 126 for char in value):
            raise ValueError("expected a nonempty printable session token without whitespace")
        return value


class LbxAdditionalField(LbxDto):
    description: str | None = None
    name: str | None = None
    element_value: str | None = None
    list_element_id: Identity | None = None


class LbxTariff(LbxDto):
    tariff_id: Identity
    archive: int | None = None
    assigned: int | None = None
    currency_id: Identity | None = None
    balance_blocks: int | None = None
    block_to_close_days: NonnegativeInteger | None = None
    dynamic_rent: int | None = None
    dynamic_rent_unblock_type: int | None = None
    name: str | None = None
    link: str | None = None
    outer_id: str | None = None
    payment_type: int | None = None
    float_period: int | None = None
    assign_unavailable: int | None = None
    client_unavailable: int | None = None
    proportional_rent: int | None = None
    demo_period_length: NonnegativeInteger | None = None
    additional_fields: list[LbxAdditionalField] | None = None


class LbxTariffPeriod(LbxDto):
    tariff_period_id: Identity
    period_id: Identity
    hidden: bool | None = None
    period_type: int | None = None
    period_length: Annotated[int, Field(gt=0)] | None = None


class LbxDiscount(LbxDto):
    discount_id: Identity
    count: NonnegativeInteger | None = None
    new_price: ExactNumber | None = None
    new_bulk_price: ExactNumber | None = None
    rate: ExactNumber | None = None


class LbxInlinePrice(LbxDto):
    period_id: Identity
    price: ExactNumber | None = None
    bulk_price: ExactNumber | None = None
    connection_price: ExactNumber | None = None
    price_start_date: CalendarDate | None = None
    bulk_include_amount: NonnegativeInteger | None = None
    discounts: list[LbxDiscount] | None = None


class LbxPeriodDiscount(LbxDto):
    period_id: Identity
    discounts: list[LbxDiscount] | None = None


class LbxTariffService(LbxDto):
    tariff_id: Identity
    tariff_service_id: Identity
    # Observed 043 service-row metadata, never a substitute for service identity.
    record_id: Identity | None = None
    bulk_service: bool | None = None
    catalog_id: Identity | None = None
    catalog_service_id: Identity | None = None
    enabled_by_default: int | None = None
    # E04 returns JSON 1.0. Parse exact numbers here; supported integer
    # quantities are a commercial-profile decision in the normalizer.
    min_multiplicator: ExactNumber | None = None
    max_multiplicator: ExactNumber | None = None
    description: str | None = None
    full_description: str | None = None
    payment_object: int | None = None
    outer_id: str | None = None
    periodic_service: int | None = None
    hidden_for_user: int | None = None
    user_can_set_mul: int | None = None
    user_available: int | None = None
    archive: int | None = None
    prices: list[LbxInlinePrice] | None = None
    discounts: list[LbxPeriodDiscount] | None = None


class LbxServicePrice(LbxDto):
    price_id: Identity
    period_id: Identity
    start_date: CalendarDate | None = None
    start_date_year: Annotated[int, Field(ge=1, le=9999)] | None = None
    start_date_month: Annotated[int, Field(ge=1, le=12)] | None = None
    connection_price: ExactNumber | None = None
    bulk_price: ExactNumber | None = None
    price: ExactNumber | None = None
    bulk_include_amount: NonnegativeInteger | None = None
    period_type: int | None = None
    period_length: Annotated[int, Field(gt=0)] | None = None
    next_change_date: CalendarDate | None = None

    @model_validator(mode="after")
    def normalize_calendar_start(self) -> LbxServicePrice:
        # E05 identifies the start calendar month. This is schedule evidence,
        # never the beginning of a paid subscription or an assumed UTC instant.
        if self.start_date_year is not None and self.start_date_month is not None:
            start = date(self.start_date_year, self.start_date_month, 1)
            if self.start_date is not None and self.start_date != start:
                raise ValueError("conflicting price calendar starts")
            object.__setattr__(self, "start_date", start)
        elif self.start_date_year is not None or self.start_date_month is not None:
            if self.start_date is not None:
                raise ValueError("incomplete alternate price calendar start")
        return self
