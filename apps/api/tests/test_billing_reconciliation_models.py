from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint

from app.models import (
    BillingProductAccessScope,
    BillingStateObservation,
    BillingStateObservationKind,
    BillingWorkItem,
    ExternalBillingWebhookDelivery,
    ExternalSubscription,
    ExternalSubscriptionCommercialAccessStatus,
    ExternalSubscriptionFinancialAccessStatus,
    ExternalSubscriptionLifecycleStatus,
    ManualReviewCase,
    PurchasedAllowance,
)
from app.models._shared import PersistedEnumType


def _column_names(model: type) -> set[str]:
    return set(model.__table__.c.keys())


def _nullable_columns(model: type) -> set[str]:
    return {column.name for column in model.__table__.c if column.nullable}


def _unique_keys(model: type) -> set[tuple[str, ...]]:
    return {
        tuple(column.name for column in constraint.columns)
        for constraint in model.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }


def _foreign_keys(model: type) -> set[tuple[tuple[str, ...], tuple[str, ...], str | None]]:
    return {
        (
            tuple(element.parent.name for element in constraint.elements),
            tuple(element.target_fullname for element in constraint.elements),
            constraint.ondelete,
        )
        for constraint in model.__table__.constraints
        if isinstance(constraint, ForeignKeyConstraint)
    }


def _check_names(model: type) -> set[str]:
    return {
        constraint.name
        for constraint in model.__table__.constraints
        if isinstance(constraint, CheckConstraint) and constraint.name is not None
    }


def _indexes(model: type) -> dict[str, tuple[str, ...]]:
    return {
        index.name: tuple(column.name for column in index.columns)
        for index in model.__table__.indexes
    }


def test_target_reconciliation_model_columns_are_exact() -> None:
    assert _column_names(BillingProductAccessScope) == {
        "access_scope_id",
        "user_id",
        "product_id",
        "primary_subscription_id",
        "updated_at",
    }
    assert _column_names(ExternalSubscription) == {
        "subscription_id",
        "external_billing_account_id",
        "customer_id",
        "user_id",
        "product_id",
        "purchase_intent_id",
        "mapping_revision_id",
        "external_subscription_id",
        "external_agreement_id",
        "lifecycle_status",
        "financial_access_status",
        "commercial_access_status",
        "last_authoritative_read_at",
        "projection_valid_until",
        "reconciliation_lease_owner",
        "reconciliation_lease_expires_at",
        "reconciliation_fencing_token",
        "latest_observation_id",
        "created_at",
        "updated_at",
    }
    assert _column_names(BillingStateObservation) == {
        "observation_id",
        "observation_kind",
        "external_billing_account_id",
        "user_id",
        "product_id",
        "access_scope_id",
        "subscription_id",
        "purchase_intent_id",
        "work_item_id",
        "basis_observation_id",
        "observed_at",
        "effective_at",
        "evidence_schema_version",
        "evidence_document",
        "completeness_classification",
        "result_classification",
        "resulting_access_revision",
        "created_at",
    }
    assert _column_names(PurchasedAllowance) == {
        "allowance_id",
        "subscription_id",
        "source_component_id",
        "product_id",
        "metric_key",
        "quantity",
        "provider_cycle_key",
        "provider_cycle_start",
        "provider_cycle_end",
        "period_start",
        "period_end",
        "created_at",
    }
    assert _column_names(ExternalBillingWebhookDelivery) == {
        "delivery_id",
        "external_billing_account_id",
        "provider_event_id",
        "payload_hash",
        "correlation_schema_version",
        "correlation_document",
        "evidence_schema_version",
        "evidence_document",
        "processing_state",
        "received_at",
        "processing_started_at",
        "processed_at",
        "last_error_classification",
    }
    assert _column_names(BillingWorkItem) == {
        "work_item_id",
        "work_kind",
        "scope_kind",
        "scope_reference",
        "coalescing_key",
        "payload_schema_version",
        "payload_document",
        "priority",
        "next_attempt_at",
        "attempt_count",
        "work_state",
        "lease_owner",
        "lease_expires_at",
        "last_error_classification",
        "created_at",
        "updated_at",
    }
    assert _column_names(ManualReviewCase) == {
        "review_case_id",
        "reason_code",
        "scope_kind",
        "scope_reference",
        "evidence_schema_version",
        "evidence_document",
        "case_state",
        "created_at",
        "resolved_at",
        "resolved_by_principal",
        "resolution_schema_version",
        "resolution_document",
    }


def test_nullable_slots_are_limited_to_the_approved_contract() -> None:
    assert _nullable_columns(BillingProductAccessScope) == {"primary_subscription_id"}
    assert _nullable_columns(ExternalSubscription) == {
        "purchase_intent_id",
        "mapping_revision_id",
        "external_subscription_id",
        "external_agreement_id",
        "reconciliation_lease_owner",
        "reconciliation_lease_expires_at",
        "latest_observation_id",
    }
    assert _nullable_columns(BillingStateObservation) == {
        "user_id",
        "product_id",
        "access_scope_id",
        "subscription_id",
        "purchase_intent_id",
        "work_item_id",
        "basis_observation_id",
        "effective_at",
        "resulting_access_revision",
    }
    assert _nullable_columns(PurchasedAllowance) == {
        "provider_cycle_key",
        "provider_cycle_start",
        "provider_cycle_end",
    }
    assert _nullable_columns(ExternalBillingWebhookDelivery) == {
        "provider_event_id",
        "processing_started_at",
        "processed_at",
        "last_error_classification",
    }
    assert _nullable_columns(BillingWorkItem) == {
        "coalescing_key",
        "lease_owner",
        "lease_expires_at",
        "last_error_classification",
    }
    assert _nullable_columns(ManualReviewCase) == {
        "resolved_at",
        "resolved_by_principal",
        "resolution_schema_version",
        "resolution_document",
    }


def test_access_scope_subscription_and_observation_keys_are_exact() -> None:
    assert _unique_keys(BillingProductAccessScope) == {
        ("access_scope_id", "user_id", "product_id"),
        ("user_id", "product_id"),
    }
    assert _unique_keys(ExternalSubscription) == {
        ("subscription_id", "product_id"),
        ("subscription_id", "user_id", "product_id"),
        ("subscription_id", "external_billing_account_id", "user_id", "product_id"),
    }
    assert _unique_keys(BillingStateObservation) == {
        ("observation_id", "access_scope_id"),
        ("observation_id", "subscription_id"),
    }

    assert _foreign_keys(BillingProductAccessScope) == {
        (("user_id",), ("users.id",), "RESTRICT"),
        (
            ("primary_subscription_id", "user_id", "product_id"),
            (
                "external_subscriptions.subscription_id",
                "external_subscriptions.user_id",
                "external_subscriptions.product_id",
            ),
            "RESTRICT",
        ),
    }
    assert _foreign_keys(ExternalSubscription) == {
        (
            ("customer_id", "external_billing_account_id", "user_id"),
            (
                "external_billing_customers.customer_id",
                "external_billing_customers.external_billing_account_id",
                "external_billing_customers.user_id",
            ),
            "RESTRICT",
        ),
        (
            (
                "purchase_intent_id",
                "customer_id",
                "external_billing_account_id",
                "user_id",
                "product_id",
                "mapping_revision_id",
            ),
            (
                "purchase_intents.purchase_intent_id",
                "purchase_intents.customer_id",
                "purchase_intents.external_billing_account_id",
                "purchase_intents.user_id",
                "purchase_intents.product_id",
                "purchase_intents.mapping_revision_id",
            ),
            "RESTRICT",
        ),
        (
            ("mapping_revision_id", "external_billing_account_id"),
            (
                "commercial_mapping_revisions.mapping_revision_id",
                "commercial_mapping_revisions.external_billing_account_id",
            ),
            "RESTRICT",
        ),
        (
            ("latest_observation_id", "subscription_id"),
            (
                "billing_state_observations.observation_id",
                "billing_state_observations.subscription_id",
            ),
            "RESTRICT",
        ),
    }
    assert _foreign_keys(BillingStateObservation) == {
        (("user_id",), ("users.id",), "RESTRICT"),
        (
            ("access_scope_id", "user_id", "product_id"),
            (
                "billing_product_access_scopes.access_scope_id",
                "billing_product_access_scopes.user_id",
                "billing_product_access_scopes.product_id",
            ),
            "RESTRICT",
        ),
        (
            ("subscription_id", "external_billing_account_id", "user_id", "product_id"),
            (
                "external_subscriptions.subscription_id",
                "external_subscriptions.external_billing_account_id",
                "external_subscriptions.user_id",
                "external_subscriptions.product_id",
            ),
            "RESTRICT",
        ),
        (
            ("purchase_intent_id", "external_billing_account_id", "user_id", "product_id"),
            (
                "purchase_intents.purchase_intent_id",
                "purchase_intents.external_billing_account_id",
                "purchase_intents.user_id",
                "purchase_intents.product_id",
            ),
            "RESTRICT",
        ),
        (("work_item_id",), ("billing_work_items.work_item_id",), "SET NULL"),
        (
            ("basis_observation_id", "access_scope_id"),
            (
                "billing_state_observations.observation_id",
                "billing_state_observations.access_scope_id",
            ),
            "RESTRICT",
        ),
    }
    assert _foreign_keys(PurchasedAllowance) == {
        (
            ("subscription_id", "product_id"),
            (
                "external_subscriptions.subscription_id",
                "external_subscriptions.product_id",
            ),
            "RESTRICT",
        ),
    }


def test_closed_and_open_vocabularies_are_explicit() -> None:
    enum_columns = {
        ExternalSubscription.__table__.c.lifecycle_status: ExternalSubscriptionLifecycleStatus,
        ExternalSubscription.__table__.c.financial_access_status: ExternalSubscriptionFinancialAccessStatus,
        ExternalSubscription.__table__.c.commercial_access_status: ExternalSubscriptionCommercialAccessStatus,
        BillingStateObservation.__table__.c.observation_kind: BillingStateObservationKind,
    }
    for column, enum_cls in enum_columns.items():
        assert isinstance(column.type, PersistedEnumType)
        assert column.type.enum_cls is enum_cls

    open_columns = (
        BillingStateObservation.__table__.c.completeness_classification,
        BillingStateObservation.__table__.c.result_classification,
        ExternalBillingWebhookDelivery.__table__.c.processing_state,
        BillingWorkItem.__table__.c.work_kind,
        BillingWorkItem.__table__.c.scope_kind,
        BillingWorkItem.__table__.c.work_state,
        ManualReviewCase.__table__.c.reason_code,
        ManualReviewCase.__table__.c.scope_kind,
        ManualReviewCase.__table__.c.case_state,
    )
    assert all(not isinstance(column.type, PersistedEnumType) for column in open_columns)


def test_step_4_safe_checks_are_exact() -> None:
    assert _check_names(BillingProductAccessScope) == set()
    assert _check_names(ExternalSubscription) == {
        "ck_external_subscriptions_purchase_mapping",
        "ck_external_subscriptions_lifecycle_status",
        "ck_external_subscriptions_financial_access_status",
        "ck_external_subscriptions_commercial_access_status",
        "ck_external_subscriptions_reconciliation_lease_pair",
        "ck_external_subscriptions_fencing_token_nonnegative",
    }
    assert _check_names(BillingStateObservation) == {
        "ck_billing_state_observations_provenance_exclusive",
        "ck_billing_state_observations_subject_shape",
        "ck_billing_state_observations_kind",
        "ck_billing_state_observations_kind_shape",
        "ck_billing_state_observations_evidence_schema_nonempty",
    }
    assert _check_names(PurchasedAllowance) == {
        "ck_purchased_allowances_quantity_nonnegative",
        "ck_purchased_allowances_provider_cycle_pair",
        "ck_purchased_allowances_period_order",
    }
    assert _check_names(ExternalBillingWebhookDelivery) == {
        "ck_external_billing_webhook_deliveries_hash_nonempty",
        "ck_external_billing_webhook_deliveries_corr_schema_nonempty",
        "ck_external_billing_webhook_deliveries_evidence_schema_nonempty",
    }
    assert _check_names(BillingWorkItem) == {
        "ck_billing_work_items_payload_schema_nonempty",
        "ck_billing_work_items_lease_pair",
    }
    assert _check_names(ManualReviewCase) == {
        "ck_manual_review_cases_evidence_schema_nonempty",
    }


def test_lookup_indexes_cover_the_fixed_contract() -> None:
    assert _indexes(BillingProductAccessScope) == {
        "ix_billing_product_access_scopes_primary_subscription": ("primary_subscription_id",),
    }
    assert _indexes(ExternalSubscription) == {
        "uq_external_subscriptions_purchase_intent": ("purchase_intent_id",),
        "ix_external_subscriptions_account_customer": ("external_billing_account_id", "customer_id"),
        "ix_external_subscriptions_user_product_status": ("user_id", "product_id", "lifecycle_status"),
        "ix_external_subscriptions_customer_product_status": (
            "customer_id",
            "product_id",
            "lifecycle_status",
        ),
        "ix_external_subscriptions_purchase_provenance": (
            "purchase_intent_id",
            "customer_id",
            "mapping_revision_id",
        ),
        "ix_external_subscriptions_mapping_provenance": (
            "mapping_revision_id",
            "external_billing_account_id",
        ),
        "ix_external_subscriptions_external_id": ("external_subscription_id",),
        "ix_external_subscriptions_agreement_id": ("external_agreement_id",),
        "ix_external_subscriptions_lifecycle_status": ("lifecycle_status",),
        "ix_external_subscriptions_financial_status": ("financial_access_status",),
        "ix_external_subscriptions_commercial_status": ("commercial_access_status",),
        "ix_external_subscriptions_last_read": ("last_authoritative_read_at",),
        "ix_external_subscriptions_valid_until": ("projection_valid_until",),
        "ix_external_subscriptions_lease_expiry": ("reconciliation_lease_expires_at",),
        "ix_external_subscriptions_reconciliation_claim": (
            "projection_valid_until",
            "reconciliation_lease_expires_at",
        ),
        "ix_external_subscriptions_latest_observation": ("latest_observation_id",),
    }
    purchase_index = next(
        index
        for index in ExternalSubscription.__table__.indexes
        if index.name == "uq_external_subscriptions_purchase_intent"
    )
    assert purchase_index.unique
    assert purchase_index.dialect_options["postgresql"]["where"] is not None

    assert _indexes(BillingStateObservation) == {
        "ix_billing_state_observations_kind_time": ("observation_kind", "observed_at"),
        "ix_billing_state_observations_account_kind_time": (
            "external_billing_account_id",
            "observation_kind",
            "observed_at",
        ),
        "ix_billing_state_observations_user_product_time": ("user_id", "product_id", "observed_at"),
        "ix_billing_state_observations_scope_time": ("access_scope_id", "observed_at"),
        "ix_billing_state_observations_subscription_time": ("subscription_id", "observed_at"),
        "ix_billing_state_observations_purchase_time": ("purchase_intent_id", "observed_at"),
        "ix_billing_state_observations_work_item": ("work_item_id",),
        "ix_billing_state_observations_basis": ("basis_observation_id",),
        "ix_billing_state_observations_effective_at": ("effective_at",),
        "ix_billing_state_observations_completeness": ("completeness_classification",),
        "ix_billing_state_observations_result": ("result_classification",),
        "ix_billing_state_observations_scope_revision": (
            "access_scope_id",
            "resulting_access_revision",
        ),
    }
    assert _indexes(PurchasedAllowance) == {
        "ix_purchased_allowances_provider_cycle_key": ("provider_cycle_key",),
        "ix_purchased_allowances_subscription_cycle": ("subscription_id", "provider_cycle_key"),
        "ix_purchased_allowances_subscription_component_cycle": (
            "subscription_id",
            "source_component_id",
            "provider_cycle_key",
        ),
        "ix_purchased_allowances_product_metric": ("product_id", "metric_key"),
    }
    assert _indexes(ExternalBillingWebhookDelivery) == {
        "ix_external_billing_webhook_deliveries_account_received": (
            "external_billing_account_id",
            "received_at",
        ),
        "ix_external_billing_webhook_deliveries_processing_received": (
            "processing_state",
            "received_at",
        ),
        "ix_external_billing_webhook_deliveries_received_at": ("received_at",),
        "ix_external_billing_webhook_deliveries_provider_event": ("provider_event_id",),
        "ix_external_billing_webhook_deliveries_payload_hash": ("payload_hash",),
    }
    assert _indexes(BillingWorkItem) == {
        "ix_billing_work_items_kind_state_due": ("work_kind", "work_state", "next_attempt_at"),
        "ix_billing_work_items_scope": ("scope_kind", "scope_reference"),
        "ix_billing_work_items_coalescing_key": ("coalescing_key",),
        "ix_billing_work_items_priority_retry": ("work_state", "priority", "next_attempt_at"),
        "ix_billing_work_items_lease_expiry": ("lease_expires_at",),
        "ix_billing_work_items_claim_scan": (
            "work_state",
            "lease_expires_at",
            "priority",
            "next_attempt_at",
        ),
        "ix_billing_work_items_kind_state": ("work_kind", "work_state"),
    }
    assert _indexes(ManualReviewCase) == {
        "ix_manual_review_cases_reason_state": ("reason_code", "case_state"),
        "ix_manual_review_cases_scope": ("scope_kind", "scope_reference"),
        "ix_manual_review_cases_state": ("case_state",),
        "ix_manual_review_cases_state_created": ("case_state", "created_at"),
        "ix_manual_review_cases_resolved_by": ("resolved_by_principal",),
    }


def test_provider_specific_identity_and_later_runtime_rules_remain_deferred() -> None:
    provider_identity_columns = (
        ExternalSubscription.__table__.c.external_subscription_id,
        ExternalSubscription.__table__.c.external_agreement_id,
        PurchasedAllowance.__table__.c.provider_cycle_key,
        ExternalBillingWebhookDelivery.__table__.c.provider_event_id,
    )
    assert all(column.nullable for column in provider_identity_columns)
    assert all(not column.unique for column in provider_identity_columns)
    provider_identity_names = {column.name for column in provider_identity_columns}
    provider_identity_indexes = (
        index
        for model in (
            ExternalSubscription,
            PurchasedAllowance,
            ExternalBillingWebhookDelivery,
        )
        for index in model.__table__.indexes
        if {column.name for column in index.columns} <= provider_identity_names
    )
    assert all(not index.unique for index in provider_identity_indexes)
    assert ExternalSubscription.__table__.c.reconciliation_fencing_token.default.arg == 0
    assert BillingWorkItem.__table__.c.priority.default.arg == 0
    assert BillingWorkItem.__table__.c.attempt_count.default.arg == 0
    assert "remaining" not in PurchasedAllowance.__table__.c
    checks = (
        constraint
        for constraint in BillingWorkItem.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    )
    assert not any("attempt_count" in str(constraint.sqltext) for constraint in checks)


def test_all_new_foreign_key_targets_resolve_in_current_metadata() -> None:
    models = (
        BillingProductAccessScope,
        ExternalSubscription,
        BillingStateObservation,
        PurchasedAllowance,
        ExternalBillingWebhookDelivery,
        BillingWorkItem,
        ManualReviewCase,
    )

    for model in models:
        for foreign_key in model.__table__.foreign_keys:
            assert foreign_key.column.table.metadata is model.__table__.metadata
