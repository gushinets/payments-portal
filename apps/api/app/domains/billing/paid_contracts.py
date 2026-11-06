"""Portal-internal effective paid contents; deliberately not the B10 HTTP wire."""

from pydantic import BaseModel, ConfigDict, Field

from app.domains.billing.paid_cycles import CalendarEvidence

EFFECTIVE_SCHEMA = "paid-effective-state:v1"


class PaidGrant(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    product_id: str
    valid_until: str | None = None


class EffectiveAllowance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    allowance_id: str
    product_id: str
    metric_key: str
    unit: str
    quantity: int = Field(strict=True, ge=0)
    cycle: CalendarEvidence
    period_start: str | None = None
    period_end: str | None = None


class EffectiveState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    grants: tuple[PaidGrant, ...] = ()
    allowances: tuple[EffectiveAllowance, ...] = ()


def canonical_state(states: list[EffectiveState]) -> EffectiveState:
    grants = {grant.product_id: grant for state in states for grant in state.grants}
    allowances = [item for state in states for item in state.allowances if item.product_id in grants]
    counts: dict[tuple[str, str], int] = {}
    for item in allowances:
        key = (item.product_id, item.metric_key)
        counts[key] = counts.get(key, 0) + 1
    return EffectiveState(
        grants=tuple(grants[key] for key in sorted(grants)),
        allowances=tuple(
            sorted(
                (item for item in allowances if counts[(item.product_id, item.metric_key)] == 1),
                key=lambda item: (item.product_id, item.metric_key, item.allowance_id),
            )
        ),
    )
