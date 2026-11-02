"""Product-head CAS and immutable v2 revisions; network I/O has already finished."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.domains.catalog.commercial_offer import CommercialEvidenceMode, CommercialScope, commercial_digest
from app.domains.catalog.mapping_evidence import MappingEvidenceMode, MappingRefused
from app.domains.catalog.product_link import LINK_SCHEMA, ProductLinkDocument, ProductLinkRequest
from app.domains.catalog.publication import (
    MappingCommitUncertain,
    MappingRevisionConflict,
    SessionFactory,
    StoredMapping,
    _check_deadline,
    validate_stored_mapping,
)
from app.infrastructure.persistence.commercial_mappings import (
    MappingStorageBusy,
    MappingStorageDeadline,
    bound_publication_transaction,
    lock_mapping_scope,
    require_publication_isolation,
)
from app.infrastructure.persistence.billing_connections import ConnectionScopeBusy, lock_connection_scope
from app.infrastructure.queries.billing_customers import connection_accounts
from app.infrastructure.queries.commercial_mappings import (
    find_mapping_revision,
    connection_heads,
    find_offer_history,
    find_product_head,
    has_foreign_customer_binding,
    has_other_offer_product,
    product_head_revision,
    retained_product_mappings,
)
from app.models import CommercialMappingRevision, CommercialProductHead


@dataclass(frozen=True)
class StoredProductLink:
    mapping_revision_id: UUID
    # PRODUCT sequence; row.revision_number remains the offer history sequence.
    revision_number: int
    offer_revision_number: int
    document: ProductLinkDocument


@dataclass(frozen=True)
class LinkPublicationResult:
    stored: StoredProductLink
    inserted: bool
    recovered_commit: bool = False


def validate_product_link(row: CommercialMappingRevision, *, scope: CommercialScope) -> StoredProductLink:
    try:
        document = ProductLinkDocument.model_validate_json(json.dumps(row.mapping_document))
    except (ValidationError, ValueError, TypeError, RecursionError):
        raise MappingRefused("mapping_stored_evidence_invalid") from None
    if (
        row.mapping_schema_version != LINK_SCHEMA
        or document.scope != scope
        or row.external_billing_account_id != scope.external_billing_account_id
        or row.billing_offer_id != document.selection.billing_offer_id
        or row.catalog_digest != document.identity_digest
        or row.catalog_version is not None
        or row.manifest_version != document.manifest_version
        or row.published_at != document.published_at
        or row.published_by_principal != document.publisher_principal
        or row.revision_number <= 0
        or document.product_revision_number is None
    ):
        raise MappingRefused("mapping_stored_scope_or_evidence_mismatch")
    return StoredProductLink(row.mapping_revision_id, document.product_revision_number, row.revision_number, document)


def query_product_link(
    session_factory: SessionFactory,
    *,
    scope: CommercialScope,
    product_id: str,
    deadline: float | None = None,
    lock_timeout_seconds: float = 2.0,
    provider_origin: str | None = None,
    legacy_account_id: str | None = None,
    require_unique_offer: bool = False,
) -> StoredProductLink | None:
    with session_factory() as db:
        if deadline is not None:
            bound_publication_transaction(db, deadline=deadline, lock_timeout_seconds=lock_timeout_seconds)
        scope = resolve_connection_scope(
            db, scope=scope, provider_origin=provider_origin, legacy_account_id=legacy_account_id, deadline=deadline
        )
        require_compatible_connection(db, scope=scope, product_id=product_id, deadline=deadline)
        head = find_product_head(db, account_id=scope.external_billing_account_id, product_id=product_id)
        if head is None:
            return None
        if deadline is not None:
            bound_publication_transaction(db, deadline=deadline, lock_timeout_seconds=lock_timeout_seconds)
        row = product_head_revision(db, head)
        if row is None:
            raise MappingRefused("mapping_current_head_invalid")
        stored = validate_product_link(row, scope=scope)
        if stored.document.lbx_evidence_mode != CommercialEvidenceMode.CONFIGURED_SOURCE:
            raise MappingRefused("mapping_live_lbx_required")
        if stored.document.selection.product_id != product_id or stored.revision_number != head.revision_number:
            raise MappingRefused("mapping_current_head_invalid")
        if require_unique_offer:
            require_offer_product_owner(db, scope=scope, selection=stored.document.selection)
        return stored


def require_offer_product_owner(db: Session, *, scope: CommercialScope, selection: ProductLinkRequest) -> None:
    if has_other_offer_product(
        db,
        account_id=scope.external_billing_account_id,
        offer_id=selection.billing_offer_id,
        product_id=selection.product_id,
    ):
        raise MappingRefused("mapping_offer_product_conflict")


def resolve_connection_scope(
    db: Session,
    *,
    scope: CommercialScope,
    provider_origin: str | None,
    legacy_account_id: str | None,
    deadline: float | None,
) -> CommercialScope:
    """Retain a proven existing storage scope, without an account registry.

    An old credential hash is recognized only by the previous exact derivation.
    After authorized publication records its origin, credentials are irrelevant.
    Multiple proven scopes are a conflict; synthetic/invalid heads prove nothing.
    """
    if provider_origin is None:
        return scope
    # Customer-only openings and publication share the same origin evidence.
    # Validate commercial documents below without making account-only reads
    # depend on the health of unrelated product links.
    accounts = connection_accounts(db, provider_origin)
    for head in connection_heads(
        db,
        account_id=scope.external_billing_account_id,
        provider_origin=provider_origin,
        legacy_account_id=legacy_account_id,
    ):
        if deadline is not None:
            _check_deadline(deadline)
        if head.provider_origin not in (None, provider_origin):
            raise MappingRefused("mapping_existing_connection_scope_conflict")
        row = product_head_revision(db, head)
        if row is None:
            raise MappingRefused("mapping_current_head_invalid")
        existing_scope = replace(scope, external_billing_account_id=head.external_billing_account_id)
        stored = validate_product_link(row, scope=existing_scope)
        if (
            stored.document.lbx_evidence_mode != CommercialEvidenceMode.CONFIGURED_SOURCE
            or stored.document.selection.product_id != head.product_id
            or stored.revision_number != head.revision_number
        ):
            raise MappingRefused("mapping_current_head_invalid")
        accounts.add(head.external_billing_account_id)
    if len(accounts) > 1:
        raise MappingRefused("mapping_existing_connection_scope_conflict")
    return replace(scope, external_billing_account_id=next(iter(accounts))) if accounts else scope


def require_compatible_connection(
    db: Session, *, scope: CommercialScope, product_id: str, deadline: float | None = None
) -> None:
    """Do not hide a real conflicting binding behind an apparently unmapped product.

    Unknown credential-hashed history has no recoverable provider origin.
    Only the resolver's proven scope can authorize current use; local history
    stays readable and synthetic v1 history remains inert.
    """
    if has_foreign_customer_binding(db, account_id=scope.external_billing_account_id):
        raise MappingRefused("mapping_existing_connection_scope_conflict")
    for historic in retained_product_mappings(db, product_id=product_id):
        if deadline is not None:
            _check_deadline(deadline)
        other_scope = CommercialScope(scope.tenant_id, scope.region, historic.external_billing_account_id)
        if historic.mapping_schema_version == LINK_SCHEMA:
            validate_product_link(historic, scope=other_scope)
            real_binding = True
        else:
            try:
                previous = validate_stored_mapping(
                    historic, scope=other_scope, offer_id=historic.billing_offer_id, allow_simulated=True
                )
            except MappingRefused:
                continue
            real_binding = previous.document.evidence_mode != MappingEvidenceMode.SIMULATED
        if real_binding and historic.external_billing_account_id != scope.external_billing_account_id:
            raise MappingRefused("mapping_existing_connection_scope_conflict")


def query_link_history(
    session_factory: SessionFactory,
    *,
    scope: CommercialScope,
    offer_id: str,
    revision: int | None,
) -> StoredProductLink | StoredMapping:
    """Explicit history can read v1 without adopting it as a current v2 link.

    A removed old manual scope may be read from validated historical documents,
    only in this deployment tenant/region. Ambiguity is never resolved at random.
    """
    if not offer_id.strip() or (revision is not None and revision <= 0):
        raise MappingRefused("mapping_query_invalid")
    with session_factory() as db:
        candidates: dict[str, StoredProductLink | StoredMapping] = {}
        for row in find_offer_history(db, offer_id=offer_id, revision=revision):
            if row.external_billing_account_id in candidates:
                continue
            historic_scope = CommercialScope(scope.tenant_id, scope.region, row.external_billing_account_id)
            stored = (
                validate_product_link(row, scope=historic_scope)
                if row.mapping_schema_version == LINK_SCHEMA
                else validate_stored_mapping(row, scope=historic_scope, offer_id=offer_id, allow_simulated=True)
            )
            candidates[row.external_billing_account_id] = stored
        if scope.external_billing_account_id in candidates:
            return candidates[scope.external_billing_account_id]
        if len(candidates) != 1:
            raise MappingRefused("mapping_history_ambiguous" if candidates else "mapping_not_found")
        return next(iter(candidates.values()))


def _lock_connection(db: Session, scope: CommercialScope, provider_origin: str | None) -> None:
    if provider_origin is None:
        return  # Retained unproven publication helpers cannot attach origin proof.
    try:
        lock_connection_scope(db, tenant_id=scope.tenant_id, region=scope.region, provider_origin=provider_origin)
    except ConnectionScopeBusy:
        raise MappingStorageBusy() from None
    except DBAPIError as error:
        if getattr(error.orig, "sqlstate", None) == "57014":
            raise MappingStorageDeadline() from None
        raise


def publish_product_link(
    session_factory: SessionFactory,
    *,
    evaluation: ProductLinkDocument,
    expected_previous_revision: int,
    deadline: float,
    lock_timeout_seconds: float,
    provider_origin: str | None = None,
    legacy_account_id: str | None = None,
) -> LinkPublicationResult:
    if type(expected_previous_revision) is not int or expected_previous_revision < 0:
        raise MappingRefused("mapping_expected_revision_invalid")
    _check_deadline(deadline)
    scope, selection = evaluation.scope, evaluation.selection
    if evaluation.lbx_evidence_mode != CommercialEvidenceMode.CONFIGURED_SOURCE:
        raise MappingRefused("mapping_live_lbx_required")
    attempted_id = uuid4()
    uncertain = False
    with session_factory() as db:
        require_publication_isolation(db)
        bound_publication_transaction(db, deadline=deadline, lock_timeout_seconds=lock_timeout_seconds)
        _lock_connection(db, scope, provider_origin)
        _check_deadline(deadline)
        scope = resolve_connection_scope(
            db, scope=scope, provider_origin=provider_origin, legacy_account_id=legacy_account_id, deadline=deadline
        )
        if scope != evaluation.scope:
            # Preserve original account FKs and association identity. Only the
            # fresh evaluation changes; no immutable stored document is edited.
            evaluation = evaluation.model_copy(update={"scope": scope})
            evaluation = evaluation.model_copy(
                update={"identity_digest": commercial_digest(evaluation.identity_json())}
            )
        # Use the resolved account, matching purchase acceptance's product lock.
        lock_mapping_scope(
            db, account_id=scope.external_billing_account_id, offer_id="product-head:v2:" + selection.product_id
        )
        require_compatible_connection(db, scope=scope, product_id=selection.product_id, deadline=deadline)
        head = find_product_head(db, account_id=scope.external_billing_account_id, product_id=selection.product_id)
        latest = None
        if head is not None:
            row = product_head_revision(db, head)
            if row is None:
                raise MappingRefused("mapping_current_head_invalid")
            latest = validate_product_link(row, scope=scope)
            if (
                latest.document.selection.product_id != selection.product_id
                or latest.revision_number != head.revision_number
            ):
                raise MappingRefused("mapping_current_head_invalid")
        # Serialize first claims across products and check even an unchanged link.
        lock_mapping_scope(db, account_id=scope.external_billing_account_id, offer_id=selection.billing_offer_id)
        require_offer_product_owner(db, scope=scope, selection=selection)
        if latest is not None and latest.document.identity_digest == evaluation.identity_digest:
            _check_deadline(deadline)
            if provider_origin is not None and head.provider_origin is None:
                head.provider_origin = provider_origin
                bound_publication_transaction(db, deadline=deadline, lock_timeout_seconds=lock_timeout_seconds)
                try:
                    db.commit()
                except DBAPIError:
                    # No association is replayed. Query can inspect whether the
                    # origin proof committed before another credential rotation.
                    raise MappingCommitUncertain() from None
            return LinkPublicationResult(latest, False)
        previous_number = 0 if latest is None else latest.revision_number
        if expected_previous_revision != previous_number:
            raise MappingRevisionConflict()
        offer_row = find_mapping_revision(
            db, account_id=scope.external_billing_account_id, offer_id=selection.billing_offer_id
        )
        offer_revision = 1 if offer_row is None else offer_row.revision_number + 1
        document = evaluation.model_copy(
            update={"published_at": datetime.now(UTC), "product_revision_number": previous_number + 1}
        )
        row = CommercialMappingRevision(
            mapping_revision_id=attempted_id,
            external_billing_account_id=scope.external_billing_account_id,
            billing_offer_id=selection.billing_offer_id,
            revision_number=offer_revision,
            manifest_version=document.manifest_version,
            catalog_version=None,
            catalog_digest=document.identity_digest,
            mapping_schema_version=LINK_SCHEMA,
            mapping_document=document.model_dump(mode="json"),
            published_at=document.published_at,
            published_by_principal=document.publisher_principal,
        )
        db.add(row)
        db.flush()
        if head is None:
            head = CommercialProductHead(
                external_billing_account_id=scope.external_billing_account_id,
                product_id=selection.product_id,
                provider_origin=provider_origin,
                mapping_revision_id=attempted_id,
                revision_number=previous_number + 1,
            )
            db.add(head)
        else:
            if provider_origin is not None:
                head.provider_origin = provider_origin
            head.mapping_revision_id = attempted_id
            head.revision_number = previous_number + 1
        bound_publication_transaction(db, deadline=deadline, lock_timeout_seconds=lock_timeout_seconds)
        db.flush()
        saved = validate_product_link(row, scope=scope)
        _check_deadline(deadline)
        try:
            db.commit()
        except DBAPIError as error:
            state = getattr(error.orig, "sqlstate", None)
            if state is not None and not (
                error.connection_invalidated or state.startswith("08") or state in {"57P01", "57P02"}
            ):
                raise
            uncertain = True
        else:
            return LinkPublicationResult(saved, True)
    if uncertain:
        try:
            recovered = query_link_history(
                session_factory, scope=scope, offer_id=selection.billing_offer_id, revision=offer_revision
            )
            if isinstance(recovered, StoredProductLink) and recovered.mapping_revision_id == attempted_id:
                return LinkPublicationResult(recovered, False, True)
        except (DBAPIError, MappingRefused):
            pass
    raise MappingCommitUncertain()
