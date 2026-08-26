"""Provider-neutral subscription lifecycle public facade."""

from app.domains.billing.service.commands import (
    ActivatePaidPeriodCommand,
    ApplyProviderSubscriptionStateCommand,
    ApplyRefundCommand,
    ApplyRenewalPaymentCommand,
    EnableAutomaticRenewalCommand,
    ExpireDueSubscriptionsCommand,
    LifecycleCommand,
    RequestCancellationCommand,
    StartTrialCommand,
)
from app.domains.billing.service.lifecycle import (
    activate_paid_period,
    start_trial,
)
from app.domains.billing.service.lifecycle_operations import (
    apply_provider_subscription_state,
    apply_refund,
    apply_renewal_payment,
    enable_automatic_renewal,
    expire_due_subscriptions,
    request_cancellation,
)
from app.domains.billing.service.state_machine import (
    SubscriptionLifecycleError,
    ensure_subscription_status_transition,
    subscription_status_from_provider_state,
)

__all__ = [
    "ActivatePaidPeriodCommand",
    "ApplyProviderSubscriptionStateCommand",
    "ApplyRefundCommand",
    "ApplyRenewalPaymentCommand",
    "EnableAutomaticRenewalCommand",
    "ExpireDueSubscriptionsCommand",
    "LifecycleCommand",
    "RequestCancellationCommand",
    "StartTrialCommand",
    "SubscriptionLifecycleError",
    "activate_paid_period",
    "apply_provider_subscription_state",
    "apply_refund",
    "apply_renewal_payment",
    "enable_automatic_renewal",
    "ensure_subscription_status_transition",
    "expire_due_subscriptions",
    "request_cancellation",
    "start_trial",
    "subscription_status_from_provider_state",
]
