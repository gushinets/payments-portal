from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint

from app.models import (
    CapabilityManifestProjection,
    CommercialMappingRevision,
    ExternalBillingCatalogProjection,
    ExternalBillingCustomer,
    ExternalBillingCustomerBindingState,
    ExternalCreateOperation,
    ExternalCreateOperationKind,
    PurchaseIntent,
    PurchaseIntentState,
)
from app.models._shared import PersistedEnumType


def _column_names(model: type) -> set[str]:
    return set(model.__table__.c.keys())


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
    return {index.name: tuple(column.name for column in index.columns) for index in model.__table__.indexes}


def _nullable_columns(model: type) -> set[str]:
    return {column.name for column in model.__table__.c if column.nullable}


def test_projection_and_mapping_columns_are_exact() -> None:
    assert _column_names(CapabilityManifestProjection) == {
        "projection_id",
        "tenant_id",
        "region",
        "schema_version",
        "manifest_version",
        "generated_at",
        "last_complete_sync_at",
        "manifest_document",
    }
    assert _column_names(ExternalBillingCatalogProjection) == {
        "projection_id",
        "external_billing_account_id",
        "schema_version",
        "catalog_version",
        "catalog_digest",
        "last_complete_sync_at",
        "catalog_document",
    }
    assert _column_names(CommercialMappingRevision) == {
        "mapping_revision_id",
        "external_billing_account_id",
        "billing_offer_id",
        "revision_number",
        "manifest_version",
        "catalog_version",
        "catalog_digest",
        "mapping_schema_version",
        "mapping_document",
        "published_at",
        "published_by_principal",
    }


def test_customer_purchase_and_create_operation_columns_are_exact() -> None:
    assert _column_names(ExternalBillingCustomer) == {
        "customer_id",
        "external_billing_account_id",
        "user_id",
        "billing_customer_key",
        "provider_customer_id",
        "binding_state",
        "binding_updated_at",
        "created_at",
    }
    assert _column_names(PurchaseIntent) == {
        "purchase_intent_id",
        "user_id",
        "external_billing_account_id",
        "customer_id",
        "product_id",
        "billing_offer_id",
        "mapping_revision_id",
        "accepted_commercial_fingerprint",
        "client_idempotency_key",
        "state",
        "accepted_snapshot_schema_version",
        "accepted_snapshot",
        "legal_acceptance_event_id",
        "created_at",
        "state_updated_at",
        "resolved_at",
    }


def test_nullable_storage_is_limited_to_approved_gated_and_lifecycle_slots() -> None:
    assert _nullable_columns(CapabilityManifestProjection) == set()
    assert _nullable_columns(ExternalBillingCatalogProjection) == {"catalog_version"}
    assert _nullable_columns(CommercialMappingRevision) == {"catalog_version"}
    assert _nullable_columns(ExternalBillingCustomer) == {"provider_customer_id"}
    assert _nullable_columns(PurchaseIntent) == {"resolved_at"}
    assert _nullable_columns(ExternalCreateOperation) == {
        "purchase_intent_id",
        "unknown_since",
        "unknown_recovery_deadline_at",
        "recovery_hint_schema_version",
        "recovery_hint_document",
        "bound_external_object_id",
        "resolved_at",
    }
    assert _column_names(ExternalCreateOperation) == {
        "create_operation_id",
        "operation_kind",
        "customer_id",
        "purchase_intent_id",
        "request_correlation_key",
        "operation_state",
        "unknown_since",
        "unknown_recovery_deadline_at",
        "recovery_hint_schema_version",
        "recovery_hint_document",
        "bound_external_object_id",
        "created_at",
        "updated_at",
        "resolved_at",
    }


def test_projection_mapping_and_customer_keys_are_exact() -> None:
    assert _unique_keys(CapabilityManifestProjection) == {("tenant_id", "region")}
    assert _unique_keys(ExternalBillingCatalogProjection) == {("external_billing_account_id",)}
    assert _unique_keys(CommercialMappingRevision) == {
        ("mapping_revision_id", "external_billing_account_id"),
        ("mapping_revision_id", "external_billing_account_id", "billing_offer_id"),
        ("external_billing_account_id", "billing_offer_id", "revision_number"),
    }
    assert _unique_keys(ExternalBillingCustomer) == {
        ("customer_id", "external_billing_account_id", "user_id"),
        ("external_billing_account_id", "user_id"),
        ("billing_customer_key",),
    }


def test_purchase_relational_targets_and_foreign_keys_are_exact() -> None:
    assert _unique_keys(PurchaseIntent) == {
        ("external_billing_account_id", "user_id", "client_idempotency_key"),
        ("purchase_intent_id", "customer_id"),
        ("purchase_intent_id", "external_billing_account_id", "user_id", "product_id"),
        (
            "purchase_intent_id",
            "customer_id",
            "external_billing_account_id",
            "user_id",
            "product_id",
            "mapping_revision_id",
        ),
    }
    assert _foreign_keys(PurchaseIntent) == {
        (("user_id",), ("users.id",), "RESTRICT"),
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
            ("mapping_revision_id", "external_billing_account_id", "billing_offer_id"),
            (
                "commercial_mapping_revisions.mapping_revision_id",
                "commercial_mapping_revisions.external_billing_account_id",
                "commercial_mapping_revisions.billing_offer_id",
            ),
            "RESTRICT",
        ),
        (
            (
                "legal_acceptance_event_id",
                "user_id",
                "external_billing_account_id",
                "billing_offer_id",
                "accepted_commercial_fingerprint",
            ),
            (
                "legal_acceptance_events.id",
                "legal_acceptance_events.user_id",
                "legal_acceptance_events.external_billing_account_id",
                "legal_acceptance_events.billing_offer_id",
                "legal_acceptance_events.accepted_commercial_fingerprint",
            ),
            "RESTRICT",
        ),
    }
    assert _foreign_keys(ExternalCreateOperation) == {
        (("customer_id",), ("external_billing_customers.customer_id",), "RESTRICT"),
        (
            ("purchase_intent_id", "customer_id"),
            ("purchase_intents.purchase_intent_id", "purchase_intents.customer_id"),
            "RESTRICT",
        ),
    }
    assert _foreign_keys(ExternalBillingCustomer) == {
        (("user_id",), ("users.id",), "RESTRICT"),
    }


def test_closed_vocabularies_use_canonical_text_backed_enums() -> None:
    enum_columns = {
        ExternalBillingCustomer.__table__.c.binding_state: ExternalBillingCustomerBindingState,
        PurchaseIntent.__table__.c.state: PurchaseIntentState,
        ExternalCreateOperation.__table__.c.operation_kind: ExternalCreateOperationKind,
    }

    for column, enum_cls in enum_columns.items():
        assert isinstance(column.type, PersistedEnumType)
        assert column.type.enum_cls is enum_cls

    assert not isinstance(ExternalCreateOperation.__table__.c.operation_state.type, PersistedEnumType)
    assert ExternalBillingCustomer.__table__.c.binding_state.default.arg is ExternalBillingCustomerBindingState.UNBOUND
    assert PurchaseIntent.__table__.c.state.default.arg is PurchaseIntentState.CREATED


def test_step_4_checks_and_indexes_cover_the_fixed_contract() -> None:
    assert _check_names(CommercialMappingRevision) == {
        "ck_commercial_mapping_revisions_revision_positive",
        "ck_commercial_mapping_revisions_schema_nonempty",
    }
    assert _check_names(ExternalBillingCustomer) == {
        "ck_external_billing_customers_key_nonempty",
        "ck_external_billing_customers_binding_state",
    }
    assert _check_names(PurchaseIntent) == {
        "ck_purchase_intents_fingerprint_nonempty",
        "ck_purchase_intents_idempotency_nonempty",
        "ck_purchase_intents_snapshot_schema_nonempty",
        "ck_purchase_intents_state",
    }
    assert _check_names(ExternalCreateOperation) == {
        "ck_external_create_operations_purchase_requirement",
        "ck_external_create_operations_kind",
        "ck_external_create_operations_correlation_nonempty",
        "ck_external_create_operations_unknown_pair",
        "ck_external_create_operations_unknown_deadline",
        "ck_external_create_operations_recovery_hint_pair",
    }

    assert _indexes(CapabilityManifestProjection) == {
        "ix_capability_manifest_projections_manifest_version": ("manifest_version",),
        "ix_capability_manifest_projections_last_sync": ("last_complete_sync_at",),
    }
    assert _indexes(ExternalBillingCatalogProjection) == {
        "ix_external_billing_catalog_projections_catalog_version": ("catalog_version",),
        "ix_external_billing_catalog_projections_catalog_digest": ("catalog_digest",),
        "ix_external_billing_catalog_projections_last_sync": ("last_complete_sync_at",),
    }
    assert _indexes(CommercialMappingRevision) == {
        "ix_commercial_mapping_revisions_publication": (
            "external_billing_account_id",
            "billing_offer_id",
            "published_at",
        ),
        "ix_commercial_mapping_revisions_manifest": (
            "external_billing_account_id",
            "billing_offer_id",
            "manifest_version",
        ),
        "ix_commercial_mapping_revisions_principal": ("published_by_principal",),
    }
    assert _indexes(ExternalBillingCustomer) == {
        "ix_external_billing_customers_provider_customer_id": ("provider_customer_id",),
        "ix_external_billing_customers_binding_state": ("binding_state",),
    }
    assert _indexes(PurchaseIntent) == {
        "ix_purchase_intents_user_product": ("user_id", "product_id"),
        "ix_purchase_intents_account_offer": (
            "external_billing_account_id",
            "billing_offer_id",
        ),
        "ix_purchase_intents_customer_purchase": ("customer_id", "purchase_intent_id"),
        "ix_purchase_intents_mapping_revision": ("mapping_revision_id",),
        "ix_purchase_intents_commercial_fingerprint": ("accepted_commercial_fingerprint",),
        "ix_purchase_intents_state": ("state",),
        "ix_purchase_intents_state_updated_at": ("state", "state_updated_at"),
    }
    assert _indexes(ExternalCreateOperation) == {
        "uq_external_create_operations_unresolved_customer": ("customer_id",),
        "ix_external_create_operations_customer_state": ("customer_id", "operation_state"),
        "ix_external_create_operations_purchase": ("purchase_intent_id",),
        "ix_external_create_operations_correlation": ("request_correlation_key",),
        "ix_external_create_operations_unknown_deadline": ("unknown_recovery_deadline_at",),
        "ix_external_create_operations_bound_object": ("bound_external_object_id",),
        "ix_external_create_operations_recovery_scan": (
            "operation_state",
            "unknown_recovery_deadline_at",
            "updated_at",
        ),
    }
    unresolved_customer = ExternalCreateOperation.__table__.indexes
    assert any(
        index.name == "uq_external_create_operations_unresolved_customer" and index.unique
        for index in unresolved_customer
    )


def test_gated_external_identifiers_remain_nullable_and_non_unique() -> None:
    gated_columns = (
        ExternalBillingCatalogProjection.__table__.c.catalog_version,
        CommercialMappingRevision.__table__.c.catalog_version,
        ExternalBillingCustomer.__table__.c.provider_customer_id,
        ExternalCreateOperation.__table__.c.bound_external_object_id,
    )

    assert all(column.nullable for column in gated_columns)
    assert all(not column.unique for column in gated_columns)
    assert ExternalCreateOperation.__table__.c.operation_state.nullable is False


def test_external_account_and_kernel_product_identities_are_not_foreign_keys() -> None:
    forbidden_target_tables = {"external_billing_accounts", "products", "plans"}
    foundation_models = (
        CapabilityManifestProjection,
        ExternalBillingCatalogProjection,
        CommercialMappingRevision,
        ExternalBillingCustomer,
        PurchaseIntent,
        ExternalCreateOperation,
    )

    targets = {
        foreign_key.target_fullname.split(".", 1)[0]
        for model in foundation_models
        for foreign_key in model.__table__.foreign_keys
    }
    assert targets.isdisjoint(forbidden_target_tables)
