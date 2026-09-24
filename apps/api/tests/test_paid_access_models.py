from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, UniqueConstraint

from app.models import AccessInvalidationOutbox, PaidAccessState


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


def _checks(model: type) -> dict[str, str]:
    return {
        constraint.name: str(constraint.sqltext)
        for constraint in model.__table__.constraints
        if isinstance(constraint, CheckConstraint) and constraint.name is not None
    }


def _indexes(model: type) -> dict[str, tuple[str, ...]]:
    return {
        index.name: tuple(column.name for column in index.columns)
        for index in model.__table__.indexes
    }


def test_paid_access_and_invalidation_columns_are_exact() -> None:
    assert _column_names(PaidAccessState) == {
        "paid_access_state_id",
        "tenant_id",
        "region",
        "user_id",
        "access_revision",
        "effective_state_schema_version",
        "effective_state_document",
        "committed_at",
    }
    assert _column_names(AccessInvalidationOutbox) == {
        "outbox_id",
        "tenant_id",
        "region",
        "user_id",
        "pending_revision",
        "delivered_revision",
        "attempt_count",
        "next_attempt_at",
        "last_error_classification",
        "created_at",
        "updated_at",
    }


def test_paid_access_scope_is_identical_and_canonical() -> None:
    models = (PaidAccessState, AccessInvalidationOutbox)
    expected_foreign_key = {
        (
            ("user_id", "tenant_id", "region"),
            ("users.id", "users.tenant_id", "users.region"),
            "RESTRICT",
        )
    }

    for model in models:
        assert _unique_keys(model) == {("tenant_id", "region", "user_id")}
        assert _foreign_keys(model) == expected_foreign_key
        assert all(
            model.__table__.c[column_name].nullable is False
            for column_name in ("tenant_id", "region", "user_id")
        )
        for foreign_key in model.__table__.foreign_keys:
            assert foreign_key.column.table.metadata is model.__table__.metadata


def test_only_approved_nullable_slot_and_revision_checks_exist() -> None:
    assert _nullable_columns(PaidAccessState) == set()
    assert _nullable_columns(AccessInvalidationOutbox) == {"last_error_classification"}
    assert _checks(PaidAccessState) == {}
    assert _checks(AccessInvalidationOutbox) == {
        "ck_access_invalidation_outbox_pending_revision_positive": "pending_revision > 0",
        "ck_access_invalidation_outbox_revision_order": "pending_revision >= delivered_revision",
    }

    assert PaidAccessState.__table__.c.access_revision.default is None
    assert AccessInvalidationOutbox.__table__.c.pending_revision.default is None
    assert AccessInvalidationOutbox.__table__.c.delivered_revision.default.arg == 0
    assert AccessInvalidationOutbox.__table__.c.attempt_count.default.arg == 0


def test_invalidation_outbox_has_due_delivery_index() -> None:
    assert _indexes(AccessInvalidationOutbox) == {
        "ix_access_invalidation_outbox_next_attempt_at": ("next_attempt_at",),
    }


def test_paid_access_storage_remains_provider_neutral() -> None:
    forbidden_fragments = ("provider", "external", "status", "remaining")
    paid_access_columns = _column_names(PaidAccessState)

    assert all(
        fragment not in column_name
        for column_name in paid_access_columns
        for fragment in forbidden_fragments
    )
