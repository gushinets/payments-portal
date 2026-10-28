"""Server-scoped lookup for hints; a lookup never binds a provider object."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ExternalSubscription, ExternalBillingCustomer, PurchaseIntent, User


def subscription_for_hint(
    db: Session, *, account: str, tenant: str, region: str, provider_subscription_id: str
) -> tuple[ExternalSubscription, ExternalBillingCustomer, PurchaseIntent] | None:
    return db.execute(
        select(ExternalSubscription, ExternalBillingCustomer, PurchaseIntent)
        .join(User, User.id == ExternalSubscription.user_id)
        .join(ExternalBillingCustomer, ExternalBillingCustomer.customer_id == ExternalSubscription.customer_id)
        .join(PurchaseIntent, PurchaseIntent.purchase_intent_id == ExternalSubscription.purchase_intent_id)
        .where(
            ExternalSubscription.external_billing_account_id == account,
            ExternalSubscription.external_subscription_id == provider_subscription_id,
            User.tenant_id == tenant,
            User.region == region,
        )
    ).one_or_none()
