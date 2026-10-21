"""Stateless, private authoritative point proofs; no persistence or recovery.

POST receipts and list hints are never complete proofs. Account, seller,
calendar, connection and historical policy evidence come from the explicit
recorded profile / immutable selected terms, not invented LBX GET fields.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from pydantic import TypeAdapter

from app.domains.catalog.commercial_offer import SelectedCommercialOffer
from app.domains.purchases.preparation_contracts import PreparationProof, ProofState
from app.infrastructure.preflight import PreflightBudget
from app.integrations.lbx.client import LbxServerClient
from app.integrations.lbx.errors import LbxError, LbxPreparationBlocked, LbxResponseInvalid, LbxScopeMismatch
from app.integrations.lbx.preparation_dto import OpaqueKey, PostAgreement, PostSubscription
from app.integrations.lbx.preparation_profile import PreparationProfile


@dataclass(frozen=True, repr=False)
class PreparedCustomer:
    user_id: int
    billing_customer_key: str


@dataclass(frozen=True, repr=False)
class PreparedAgreement:
    agreement_id: int
    user_id: int
    organization_id: int
    account_id: str
    account_evidence_reference: str


@dataclass(frozen=True, repr=False)
class PreparedSubscription:
    subscription_id: int
    agreement_id: int
    user_id: int
    organization_id: int
    account_id: str
    currency: str
    recurring_amount_minor: int
    connection_amount_minor: int
    selected_evidence_digest: str
    state: int
    period_start: date
    period_end: date


@dataclass(frozen=True, repr=False)
class DiscoveryHints:
    # Zero is only an observed list result; never permission to replay a POST.
    candidate_ids: tuple[int, ...]


def _failure(error: LbxError) -> PreparationProof:
    if isinstance(error, LbxScopeMismatch):
        return PreparationProof(ProofState.IDENTITY_CONFLICT, "point_identity_conflict")
    if isinstance(error, (LbxResponseInvalid, LbxPreparationBlocked)):
        return PreparationProof(ProofState.INCOMPLETE, error.code)
    return PreparationProof(ProofState.UNRESOLVED, error.code)


def _minor(value: Decimal, scale: int) -> int:
    """Lossless scale conversion, independent of the ambient Decimal context."""
    parts = value.as_tuple()
    if not value.is_finite() or len(parts.digits) > 256 or abs(int(parts.exponent)) > 256:
        raise ValueError("unsupported amount")
    coefficient = int("".join(map(str, parts.digits)))
    exponent = int(parts.exponent) + scale
    if exponent >= 0:
        result = coefficient * 10**exponent
    else:
        result, remainder = divmod(coefficient, 10**-exponent)
        if remainder:
            raise ValueError("money scale mismatch")
    return -result if parts.sign else result


def _calendar_value(value: str) -> date:
    # LBX's naive calendar value is never labelled UTC or a natural cycle ID.
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", value):
        raise ValueError("invalid provider calendar value")
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").date()


class LbxPreparation:
    def __init__(self, client: LbxServerClient, profile: PreparationProfile) -> None:
        client.require_preparation_profile(profile)
        self._client = client
        self._profile = profile

    async def customer_hints(
        self, *, billing_customer_key: str, budget: PreflightBudget
    ) -> PreparationProof[DiscoveryHints]:
        try:
            ids = await self._client.discover_users(outer_id=billing_customer_key, budget=budget)
        except LbxError as error:
            return _failure(error)
        if len(ids) > 1:
            return PreparationProof(ProofState.IDENTITY_CONFLICT, "multiple_customer_candidates")
        return PreparationProof(ProofState.UNRESOLVED, "discovery_hints_require_point_proof", DiscoveryHints(ids))

    async def agreement_hints(
        self, *, user_id: int, billing_customer_key: str, budget: PreflightBudget
    ) -> PreparationProof[DiscoveryHints]:
        customer = await self.prove_customer(user_id=user_id, billing_customer_key=billing_customer_key, budget=budget)
        if customer.state != ProofState.COMPLETE_MATCH:
            return PreparationProof(customer.state, customer.reason)
        try:
            ids = await self._client.discover_agreements(user_id=user_id, budget=budget)
        except LbxError as error:
            return _failure(error)
        return PreparationProof(ProofState.UNRESOLVED, "discovery_hints_require_point_proof", DiscoveryHints(ids))

    async def prove_customer(
        self, *, user_id: int, billing_customer_key: str, budget: PreflightBudget
    ) -> PreparationProof[PreparedCustomer]:
        try:
            TypeAdapter(OpaqueKey).validate_python(billing_customer_key, strict=True)
        except ValueError:
            return PreparationProof(ProofState.INCOMPLETE, "customer_key_invalid")
        try:
            user = await self._client.get_user(user_id=user_id, budget=budget)
        except LbxError as error:
            return _failure(error)
        if user.outer_id is None:
            return PreparationProof(ProofState.INCOMPLETE, "customer_outer_id_missing")
        if user.outer_id != billing_customer_key:
            return PreparationProof(ProofState.IDENTITY_CONFLICT, "customer_outer_id_conflict")
        return PreparationProof(
            ProofState.COMPLETE_MATCH, "customer_point_match", PreparedCustomer(user_id, billing_customer_key)
        )

    async def prove_agreement(
        self,
        *,
        agreement_id: int,
        expected: PostAgreement,
        billing_customer_key: str,
        budget: PreflightBudget,
    ) -> PreparationProof[PreparedAgreement]:
        try:
            self._profile.require_agreement(expected)
            customer = await self.prove_customer(
                user_id=expected.user_id, billing_customer_key=billing_customer_key, budget=budget
            )
            if customer.state != ProofState.COMPLETE_MATCH:
                return PreparationProof(customer.state, customer.reason)
            agreement = await self._client.get_agreement(agreement_id=agreement_id, budget=budget)
        except LbxError as error:
            return _failure(error)
        if any(
            getattr(agreement, name) is None
            for name in (
                "user_id",
                "organization_id",
                "agreement_number",
                "agreement_link",
                "create_date",
                "is_offer",
                "debt_threshold",
                "credit",
                "currency_symbol",
                "balance",
            )
        ):
            return PreparationProof(ProofState.INCOMPLETE, "agreement_fields_missing")
        if "close_date" not in agreement.model_fields_set:
            return PreparationProof(ProofState.INCOMPLETE, "agreement_closure_unknown")
        if agreement.user_id != expected.user_id:
            return PreparationProof(ProofState.OWNER_CONFLICT, "agreement_owner_conflict")
        if agreement.organization_id != self._profile.organization_id:
            return PreparationProof(ProofState.OWNER_CONFLICT, "agreement_seller_conflict")
        if (
            any(
                getattr(agreement, name) != getattr(expected, name)
                for name in (
                    "agreement_number",
                    "agreement_link",
                    "create_date",
                    "is_offer",
                    "debt_threshold",
                )
            )
            or agreement.credit != 0
            or agreement.close_date not in {None, ""}
            or agreement.currency_symbol != self._profile.currency_symbol
        ):
            return PreparationProof(ProofState.MISMATCH, "agreement_material_conflict")
        # Account identity is checked credential/origin evidence, never a GET
        # field. The unique dedicated reference belongs to the caller's hold.
        return PreparationProof(
            ProofState.COMPLETE_MATCH,
            "agreement_point_match",
            PreparedAgreement(
                agreement_id,
                expected.user_id,
                self._profile.organization_id,
                self._profile.selection.external_billing_account_id,
                self._profile.account_evidence.reference,
            ),
        )

    async def prove_subscription(
        self,
        *,
        subscription_id: int,
        expected: PostSubscription,
        agreement: PostAgreement,
        billing_customer_key: str,
        offer: SelectedCommercialOffer,
        budget: PreflightBudget,
    ) -> PreparationProof[PreparedSubscription]:
        try:
            self._profile.require_subscription(expected, offer)
            owner = await self.prove_agreement(
                agreement_id=expected.agreement_id,
                expected=agreement,
                billing_customer_key=billing_customer_key,
                budget=budget,
            )
            if owner.state != ProofState.COMPLETE_MATCH:
                return PreparationProof(owner.state, owner.reason)
            subscription = await self._client.get_subscription(subscription_id=subscription_id, budget=budget)
        except LbxError as error:
            return _failure(error)
        if any(
            getattr(subscription, name) is None
            for name in (
                "agreement_id",
                "tariff_id",
                "period_id",
                "services",
                "total_price",
                "currency_symbol",
                "state",
                "current_blocking",
                "period_type",
                "period_length",
                "is_demo",
                "is_offer_agrm",
                "subscription_start_date",
                "last_tariffication_period_start",
                "last_tariffication_period_end",
                "subscription_end_date",
                "next_change_date",
            )
        ):
            return PreparationProof(ProofState.INCOMPLETE, "subscription_fields_missing")
        if subscription.agreement_id != expected.agreement_id:
            return PreparationProof(ProofState.OWNER_CONFLICT, "subscription_agreement_conflict")
        if (
            subscription.tariff_id != expected.tariff_id
            or subscription.period_id != expected.period_id
            or subscription.subscription_start_date != expected.subscription_start_date
            or subscription.currency_symbol != self._profile.currency_symbol
            or subscription.is_demo is not False
            or subscription.is_offer_agrm != agreement.is_offer
            or subscription.state not in self._profile.allowed_states
            or subscription.current_blocking not in self._profile.allowed_blocking
            or subscription.period_type != {"day": 1, "week": 2, "month": 3, "year": 4}.get(offer.terms.period.unit)
            or subscription.period_length != offer.terms.period.length
            or subscription.subscription_end_date != ""
            or subscription.next_change_date != ""
        ):
            return PreparationProof(ProofState.MISMATCH, "subscription_material_conflict")
        services = subscription.services
        assert services is not None
        if len(services) != 1:
            return PreparationProof(ProofState.MISMATCH, "subscription_service_composition_conflict")
        service = services[0]
        if any(
            getattr(service, name) is None
            for name in (
                "tariff_service_id",
                "multiplicator",
                "price",
                "bulk_service",
                "periodic_service",
            )
        ):
            return PreparationProof(ProofState.INCOMPLETE, "subscription_service_fields_missing")
        if (
            service.tariff_service_id != self._profile.selection.tariff_service_id
            or service.multiplicator != offer.terms.quantity.selected
            or not offer.terms.quantity.minimum <= service.multiplicator <= offer.terms.quantity.maximum
            or service.bulk_service is not False
            or service.periodic_service != 1
            or service.bulk_price not in {None, Decimal(0)}
        ):
            return PreparationProof(ProofState.MISMATCH, "subscription_service_conflict")
        currency = self._profile.inputs.currency
        assert currency is not None and service.price is not None and subscription.total_price is not None
        money = offer.terms.money
        try:
            scale = money.decimal_places if currency.source_units == "major" else 0
            # tariff_price is comparison-only. Only effective price can prove
            # the accepted recurring charge, even when the catalog still agrees.
            price_minor = _minor(service.price, scale)
            total_minor = _minor(subscription.total_price, scale)
            unit_minor = _minor(money.recurring_unit_amount, money.decimal_places)
            expected_minor = _minor(money.recurring_amount, money.decimal_places)
            connection_minor = _minor(money.connection_amount, money.decimal_places)
            assert subscription.last_tariffication_period_start is not None
            assert subscription.last_tariffication_period_end is not None
            period_start = _calendar_value(subscription.last_tariffication_period_start)
            period_end = _calendar_value(subscription.last_tariffication_period_end)
        except ValueError:
            return PreparationProof(ProofState.INCOMPLETE, "subscription_money_or_calendar_invalid")
        if (
            price_minor != unit_minor
            or total_minor != expected_minor
            or period_end < period_start
            or period_start < self._profile.selection.effective_on
        ):
            return PreparationProof(ProofState.MISMATCH, "subscription_effective_price_or_period_conflict")
        assert subscription.state is not None
        return PreparationProof(
            ProofState.COMPLETE_MATCH,
            "subscription_point_match",
            PreparedSubscription(
                subscription_id,
                expected.agreement_id,
                agreement.user_id,
                self._profile.organization_id,
                offer.scope.external_billing_account_id,
                money.currency,
                total_minor,
                connection_minor,
                offer.selected_evidence_digest,
                subscription.state,
                period_start,
                period_end,
            ),
        )

    async def discover(
        self, *, user_id: int, billing_customer_key: str, budget: PreflightBudget
    ) -> PreparationProof[DiscoveryHints]:
        customer = await self.prove_customer(user_id=user_id, billing_customer_key=billing_customer_key, budget=budget)
        if customer.state != ProofState.COMPLETE_MATCH:
            return PreparationProof(customer.state, customer.reason)
        try:
            ids = await self._client.discover_subscriptions(user_id=user_id, budget=budget)
        except LbxError as error:
            return _failure(error)
        return PreparationProof(ProofState.UNRESOLVED, "discovery_hints_require_point_proof", DiscoveryHints(ids))
