"""Synchronous application orchestration; all source HTTP precedes this boundary."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.domains.catalog.commercial_offer import CommercialScope
from app.domains.catalog.mapping_evidence import (
    MAPPING_SCHEMA,
    MappingDocument,
    MappingEvidenceMode,
    MappingRefused,
    require_replacement_approval,
)
from app.infrastructure.persistence.commercial_mappings import (
    MappingStorageDeadline,
    bound_publication_transaction,
    lock_mapping_scope,
    require_publication_isolation,
)
from app.infrastructure.queries.commercial_mappings import find_mapping_revision, mapping_revision_history
from app.models import CommercialMappingRevision


class MappingRevisionConflict(MappingRefused):
    def __init__(self) -> None:
        super().__init__("mapping_revision_conflict")


class MappingCommitUncertain(MappingRefused):
    def __init__(self) -> None:
        super().__init__("mapping_commit_uncertain_query_required")


SessionFactory = Callable[[], Session]


@dataclass(frozen=True)
class StoredMapping:
    mapping_revision_id: UUID
    revision_number: int
    document: MappingDocument


@dataclass(frozen=True)
class PublicationResult:
    stored: StoredMapping
    evaluation: MappingDocument
    inserted: bool
    recovered_commit: bool = False


def validate_stored_mapping(
    row: CommercialMappingRevision, *, scope: CommercialScope, offer_id: str, allow_simulated: bool
) -> StoredMapping:
    """Shared operator/catalog/admission selection policy, without CLI auth.

    Call only on the already selected latest (or explicitly historical) row.
    Unproven scope/schema/mode never authorizes falling back to older evidence.
    """
    try:
        document = MappingDocument.model_validate_json(json.dumps(row.mapping_document))
    except (ValidationError, ValueError, TypeError, OverflowError, RecursionError):
        raise MappingRefused("mapping_stored_evidence_invalid") from None
    if (
        row.mapping_schema_version != MAPPING_SCHEMA
        or document.material.scope != scope
        or row.external_billing_account_id != scope.external_billing_account_id
        or row.billing_offer_id != offer_id
        or document.material.billing_offer_id != offer_id
        or row.catalog_digest != document.material.selected_evidence_digest
        or row.catalog_version is not None
        or row.manifest_version != document.manifest_version
        or row.published_by_principal != document.publisher_principal
        or row.published_at != document.published_at
        or row.revision_number <= 0
    ):
        raise MappingRefused("mapping_stored_scope_or_evidence_mismatch")
    if document.evidence_mode == MappingEvidenceMode.SIMULATED and not allow_simulated:
        raise MappingRefused("mapping_simulation_forbidden")
    return StoredMapping(row.mapping_revision_id, row.revision_number, document)


def query_mapping(
    session_factory: SessionFactory,
    *,
    scope: CommercialScope,
    offer_id: str,
    revision: int | None = None,
    allow_simulated: bool = False,
) -> StoredMapping:
    """DB-only. No source configuration, resource owner or admission required."""
    if not offer_id.strip() or (revision is not None and (type(revision) is not int or revision <= 0)):
        raise MappingRefused("mapping_query_invalid")
    with session_factory() as db:
        row = find_mapping_revision(
            db, account_id=scope.external_billing_account_id, offer_id=offer_id, revision=revision
        )
        if row is None:
            raise MappingRefused("mapping_not_found")
        return validate_stored_mapping(row, scope=scope, offer_id=offer_id, allow_simulated=allow_simulated)


def _check_deadline(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise MappingStorageDeadline()


def utc_now() -> datetime:
    return datetime.now(UTC)


def publish_mapping(
    session_factory: SessionFactory,
    *,
    evaluation: MappingDocument,
    expected_previous_revision: int,
    deadline: float,
    evidence_valid_until: datetime,
    lock_timeout_seconds: float,
    allow_simulated: bool = False,
    clock: Callable[[], datetime] | None = None,
) -> PublicationResult:
    """Lock -> re-read -> equality/CAS -> append, in one short PG transaction.

    deadline is the same operation's absolute monotonic work deadline, never a
    renewed DB timeout. No session or connection survives back into source I/O.
    evidence_valid_until is an independent, exclusive account-calendar lease.
    """
    if type(expected_previous_revision) is not int or expected_previous_revision < 0:
        raise MappingRefused("mapping_expected_revision_invalid")
    scope, offer_id = evaluation.material.scope, evaluation.material.billing_offer_id
    if evaluation.evidence_mode == MappingEvidenceMode.SIMULATED and not allow_simulated:
        raise MappingRefused("mapping_simulation_forbidden")
    now = clock if clock is not None else utc_now

    def check_publication_window() -> None:
        _check_deadline(deadline)
        instant = now()
        if evidence_valid_until.utcoffset() is None or instant.utcoffset() is None:
            raise MappingRefused("mapping_clock_invalid")
        if instant >= evidence_valid_until:
            raise MappingRefused("mapping_publication_evidence_expired")

    # Source cleanup is complete. Refuse before constructing a DB capability.
    check_publication_window()
    attempted_revision: int | None = None
    commit_uncertain = False
    with session_factory() as db:
        try:
            require_publication_isolation(db)
            bound_publication_transaction(db, deadline=deadline, lock_timeout_seconds=lock_timeout_seconds)
            lock_mapping_scope(db, account_id=scope.external_billing_account_id, offer_id=offer_id)
            _check_deadline(deadline)
            row = find_mapping_revision(db, account_id=scope.external_billing_account_id, offer_id=offer_id)
            latest = (
                None
                if row is None
                else validate_stored_mapping(row, scope=scope, offer_id=offer_id, allow_simulated=True)
            )
            check_publication_window()
            # Equality precedes CAS: identical retries with the previous expected
            # number return immutable history and a separate current evaluation.
            if latest is not None and latest.document.material_fingerprint == evaluation.material_fingerprint:
                check_publication_window()
                return PublicationResult(latest, evaluation, inserted=False)
            latest_number = 0 if latest is None else latest.revision_number
            if latest_number != expected_previous_revision:
                raise MappingRevisionConflict()
            for historic_row in mapping_revision_history(
                db, account_id=scope.external_billing_account_id, offer_id=offer_id
            ):
                check_publication_window()
                historic = validate_stored_mapping(historic_row, scope=scope, offer_id=offer_id, allow_simulated=True)
                require_replacement_approval(historic.document, evaluation)
            check_publication_window()
            attempted_revision = latest_number + 1
            published = evaluation.model_copy(update={"published_at": now()})
            row = CommercialMappingRevision(
                external_billing_account_id=scope.external_billing_account_id,
                billing_offer_id=offer_id,
                revision_number=attempted_revision,
                manifest_version=published.manifest_version,
                catalog_version=None,
                catalog_digest=published.material.selected_evidence_digest,
                mapping_schema_version=MAPPING_SCHEMA,
                mapping_document=published.model_dump(mode="json"),
                published_at=published.published_at,
                published_by_principal=published.publisher_principal,
            )
            db.add(row)
            bound_publication_transaction(db, deadline=deadline, lock_timeout_seconds=lock_timeout_seconds)
            db.flush()
            saved = validate_stored_mapping(row, scope=scope, offer_id=offer_id, allow_simulated=allow_simulated)
            check_publication_window()
            try:
                db.commit()
            except DBAPIError as error:
                state = getattr(error.orig, "sqlstate", None)
                if state is not None and not (
                    error.connection_invalidated or state.startswith("08") or state in {"57P01", "57P02"}
                ):
                    # A definite server rejection (for example serialization
                    # failure) remains the original DB error, not lost-ACK proof.
                    raise
                # A lost commit acknowledgement does not establish rollback.
                commit_uncertain = True
            else:
                return PublicationResult(saved, evaluation, inserted=True)
        finally:
            # Close releases the transaction/lock on all definite refusal paths.
            # An uncertain COMMIT is resolved below using a new authoritative read.
            db.close()
    if commit_uncertain:
        try:
            recovered = query_mapping(
                session_factory,
                scope=scope,
                offer_id=offer_id,
                revision=attempted_revision,
                allow_simulated=allow_simulated,
            )
        except (DBAPIError, MappingRefused):
            raise MappingCommitUncertain() from None
        if recovered.document.material_fingerprint == evaluation.material_fingerprint:
            return PublicationResult(recovered, evaluation, inserted=False, recovered_commit=True)
    raise MappingCommitUncertain()
