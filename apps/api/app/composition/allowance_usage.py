"""Route an issued allowance by its immutable source/backend owner."""

from app.core.backend_consumers import BackendConsumer
from app.core.settings import Settings
from app.domains.billing.paid_allowances import allowance_ownership
from app.domains.billing.contracts import BillingRefused
from app.domains.catalog.technical_source import TechnicalOwnership
from app.models import PurchasedAllowance


def allowance_backend(configuration: Settings, allowance: PurchasedAllowance) -> BackendConsumer:
    return usage_backend(configuration, allowance_ownership(allowance), allowance.product_id)


def usage_backend(configuration: Settings, ownership: TechnicalOwnership, product_id: str) -> BackendConsumer:
    for consumer in configuration.backend_consumers:
        if ownership == TechnicalOwnership(consumer.technical_source_id, consumer.consumer_id):
            if product_id not in consumer.allowed_products:
                break
            return consumer
    raise BillingRefused("paid_usage_owner_unavailable", 503)
