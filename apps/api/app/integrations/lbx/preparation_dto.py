"""Private Swagger 1.0.11 preparation types; never Portal HTTP schemas.

Requests deliberately expose only the selected non-payment CREATE subset.
Absent GET fields remain absent evidence. No names or legal data are invented.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Generic, Literal, TypeVar

from pydantic import Field, field_validator, model_validator

from app.integrations.lbx.dto import (
    CalendarDate,
    ExactNumber,
    Identity,
    LbxAdditionalField,
    LbxDto,
    NonnegativeInteger,
)


OpaqueKey = Annotated[str, Field(min_length=1, max_length=256, pattern=r"^[!-~]+$")]


class PrivateDto(LbxDto):
    def __repr__(self) -> str:
        return f"{type(self).__name__}(<private>)"

    def __str__(self) -> str:
        return self.__repr__()


T = TypeVar("T")


class CreateEnvelope(PrivateDto, Generic[T]):
    code: Literal[200, 201]
    response: T


class PostUser(PrivateDto):
    type: Literal[1, 2]
    outer_id: OpaqueKey
    sole_proprietor: bool | None = None
    organization: str | None = None
    user_surname: str | None = None
    user_name: str | None = None
    user_patronymic: str | None = None
    email: str | None = None

    @field_validator("type", mode="before")
    @classmethod
    def require_integer_type(cls, value: Any) -> Any:
        if type(value) is not int:
            raise ValueError("integer customer type required")
        return value


class UserAddress(PrivateDto):
    type: int | None = None
    address: str | None = None


class UserInfo(PrivateDto):
    user_id: Identity
    outer_id: str | None = None
    type: int | None = None
    sole_proprietor: bool | None = None
    organization: str | None = None
    user_surname: str | None = None
    user_name: str | None = None
    user_patronymic: str | None = None
    email: str | None = None
    inn: str | None = None
    kpp: str | None = None
    ogrn: str | None = None
    ogrn_date: str | None = None
    okpo: str | None = None
    ceo: str | None = None
    act_on_what: str | None = None
    accountant: str | None = None
    passport_series: str | None = None
    passport_number: str | None = None
    passport_issue_place: str | None = None
    passport_issue_department: str | None = None
    passport_issue_date: str | None = None
    birth_place: str | None = None
    birth_date: str | None = None
    bik: str | None = None
    bank_name: str | None = None
    branch_bank_name: str | None = None
    correspondent_account: str | None = None
    bank_account: str | None = None
    phone: str | None = None
    mobile: str | None = None
    contact_person: str | None = None
    login: str | None = None
    # A nonempty password is refused by the client, never returned or logged.
    password: str | None = None
    descr: str | None = None
    days_for_paying_orders: int | None = None
    edo_id: str | None = None
    personal_manager: int | None = None
    non_resident: bool | None = None
    edo_type: int | None = None
    addresses: list[UserAddress] | None = None
    additional_fields: list[LbxAdditionalField] | None = None
    personal_manager_name: str | None = None


class PostAgreement(PrivateDto):
    user_id: Identity
    organization_id: Identity
    agreement_link: Annotated[str, Field(min_length=1)]
    agreement_number: OpaqueKey
    create_date: date
    is_offer: bool
    debt_threshold: ExactNumber

    @model_validator(mode="after")
    def prohibit_debt(self) -> PostAgreement:
        if self.debt_threshold != 0:
            raise ValueError("credit is not authorized")
        return self


class AgreementInfo(PrivateDto):
    agreement_id: Identity
    user_id: Identity | None = None
    organization_id: Identity | None = None
    agreement_link: str | None = None
    agreement_number: str | None = None
    create_date: CalendarDate | None = None
    is_offer: bool | None = None
    pay_code: str | None = None
    debt_threshold: ExactNumber | None = None
    balance: ExactNumber | None = None
    credit: ExactNumber | None = None
    currency_symbol: str | None = None
    close_date: str | None = None
    additional_fields: list[LbxAdditionalField] | None = None


class NewServiceInfo(PrivateDto):
    tariff_service_id: Identity
    multiplicator: Annotated[int, Field(gt=0)]
    # No modifier: the accepted selected offer does not authorize overrides.


class PostSubscription(PrivateDto):
    agreement_id: Identity
    tariff_id: Identity
    period_id: Identity
    subscription_start_date: Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2} 00:00:00$")]
    activate_by_balance: bool
    demo_period_length: NonnegativeInteger
    activate_manually: bool
    outer_id: OpaqueKey
    services: Annotated[list[NewServiceInfo], Field(min_length=1, max_length=1)] | None


class SubServiceInfo(PrivateDto):
    service_id: Identity
    tariff_service_id: Identity | None = None
    multiplicator: NonnegativeInteger | None = None
    price: ExactNumber | None = None
    tariff_price: ExactNumber | None = None
    bulk_service: bool | None = None
    bulk_price: ExactNumber | None = None
    tariff_bulk_price: ExactNumber | None = None
    service_description: str | None = None
    outer_id: str | None = None
    time_from: str | None = None
    tar_name: str | None = None
    weight: int | None = None
    periodic_service: int | None = None
    hidden_for_user: int | None = None
    is_taxed: bool | None = None
    bulk_include_amount: NonnegativeInteger | None = None


class SubscriptionInfo(PrivateDto):
    subscription_id: Identity
    agreement_id: Identity | None = None
    tariff_id: Identity | None = None
    period_id: Identity | None = None
    subscription_instance_id: Identity | None = None
    subscription_start_date: str | None = None
    subscription_end_date: str | None = None
    subscription_instance_start_date: str | None = None
    subscription_instance_end_date: str | None = None
    last_tariffication_period_start: str | None = None
    last_tariffication_period_end: str | None = None
    next_change_date: str | None = None
    state: int | None = None
    current_blocking: int | None = None
    period_type: int | None = None
    period_length: int | None = None
    is_demo: bool | None = None
    is_offer_agrm: bool | None = None
    agreement_number: str | None = None
    total_price: ExactNumber | None = None
    balance: ExactNumber | None = None
    currency_symbol: str | None = None
    outer_id: str | None = None
    description: str | None = None
    err_details: str | None = None
    tariff_descr: str | None = None
    services: list[SubServiceInfo] | None = None


class CreatedUser(PrivateDto):
    user_id: Identity


class CreatedAgreement(PrivateDto):
    agreement_id: Identity


class CreatedSubscription(PrivateDto):
    subscription_id: Identity
