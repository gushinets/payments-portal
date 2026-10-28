"""Redacted prepared-subscription evidence from verified billing reads."""

from app.domains.catalog.commercial_offer import canonical_decimal
from app.domains.purchases.contracts import EffectiveServiceEvidence, PreparedSubscriptionObservation, Purchase
from app.integrations.lbx.financial import Subscription


def prepared_subscription_observation(point: Subscription, purchase: Purchase) -> PreparedSubscriptionObservation:
    # Deliberately excludes balance, provider text and PII. Dates remain provider calendar evidence.
    return PreparedSubscriptionObservation(
        subscription_id=str(point.subscription_id),
        agreement_id=str(point.agreement_id),
        state=point.state,
        current_blocking=point.current_blocking,
        accepted_fingerprint=purchase.accepted.offer.fingerprint,
        period_id=point.period_id,
        period_type=point.period_type,
        period_length=point.period_length,
        currency=purchase.accepted.offer.money.currency,
        effective_recurring_amount=canonical_decimal(point.total_price),
        services=tuple(
            EffectiveServiceEvidence(
                service.tariff_service_id, canonical_decimal(service.multiplicator), canonical_decimal(service.price)
            )
            for service in point.services
        ),
        calendar={
            field: getattr(point, field)
            for field in (
                "subscription_start_date",
                "subscription_end_date",
                "subscription_instance_start_date",
                "subscription_instance_end_date",
                "last_tariffication_period_start",
                "last_tariffication_period_end",
            )
        },
    )
